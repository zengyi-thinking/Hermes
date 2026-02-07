"""
GitHub Pages 集成
支持将报告推送到 GitHub 仓库并触发 Pages 部署
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import base64
import hashlib
import json
import time

import requests

from ..utils.logger import get_logger
from config.reporter import ReportConfig, GitHubConfig


class GitHubPusher:
    """
    GitHub Pages 部署器

    功能：
    - 将 HTML 报告推送到 GitHub 仓库
    - 支持通过 GitHub API 提交文件
    - 返回 GitHub Pages 访问链接
    """

    def __init__(self, config: ReportConfig = None, github_config: GitHubConfig = None):
        self.config = config or ReportConfig()
        self.gh_config = github_config or GitHubConfig(
            repo=self.config.github_repo,
            token=self.config.github_token,
            branch=self.config.github_branch
        )
        self.log = get_logger("github_pusher")

        # GitHub API 基础地址
        self.api_base = "https://api.github.com"

        # 验证配置
        if self.config.mode.value == "github-pages":
            if not self.gh_config.repo:
                raise ValueError("GitHub repository is required for github-pages mode")
            if not self.gh_config.token:
                raise ValueError("GitHub token is required for github-pages mode")

    def push_report(
        self,
        html_content: str,
        task_id: str,
        commit_message: str = None
    ) -> Tuple[str, bool]:
        """
        推送报告到 GitHub

        Args:
            html_content: HTML 内容
            task_id: 任务 ID
            commit_message: 提交消息，为空时使用默认消息

        Returns:
            (访问链接, 是否成功)
        """
        if not self.gh_config.token:
            self.log.error("GitHub token not configured")
            return "", False

        try:
            # 构建文件名
            filename = f"{self.config.reports_path}{task_id}.html"

            # 获取仓库信息
            repo_info = self._get_repo_info()
            if not repo_info:
                return "", False

            owner, repo = repo_info

            # 获取文件的 SHA（如果存在）
            sha = self._get_file_sha(owner, repo, filename)

            # 构建提交消息
            if commit_message is None:
                commit_message = f"{self.gh_config.commit_message_prefix} {task_id}"

            # 提交文件
            success = self._create_or_update_file(
                owner=owner,
                repo=repo,
                path=filename,
                content=html_content,
                message=commit_message,
                sha=sha
            )

            if success:
                url = self._get_pages_url(task_id)
                self.log.info(f"Pushed report to GitHub: {url}")
                return url, True
            else:
                return "", False

        except Exception as e:
            self.log.error(f"Failed to push report to GitHub: {e}")
            return "", False

    def push_report_file(
        self,
        file_path: str,
        task_id: str = None,
        commit_message: str = None
    ) -> Tuple[str, bool]:
        """
        推送本地文件到 GitHub

        Args:
            file_path: 本地文件路径
            task_id: 任务 ID，为空时从文件名提取
            commit_message: 提交消息

        Returns:
            (访问链接, 是否成功)
        """
        file_path = Path(file_path)
        if not file_path.exists():
            self.log.error(f"File not found: {file_path}")
            return "", False

        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取任务 ID
        if task_id is None:
            task_id = file_path.stem

        return self.push_report(content, task_id, commit_message)

    def delete_report(self, task_id: str, commit_message: str = None) -> bool:
        """
        删除 GitHub 上的报告

        Args:
            task_id: 任务 ID
            commit_message: 提交消息

        Returns:
            是否成功
        """
        if not self.gh_config.token:
            self.log.error("GitHub token not configured")
            return False

        try:
            filename = f"{self.config.reports_path}{task_id}.html"
            repo_info = self._get_repo_info()
            if not repo_info:
                return False

            owner, repo = repo_info

            # 获取文件的 SHA
            sha = self._get_file_sha(owner, repo, filename)
            if not sha:
                self.log.warning(f"File not found on GitHub: {filename}")
                return True  # 文件不存在也算成功

            # 删除文件
            url = f"{self.api_base}/repos/{owner}/{repo}/contents/{filename}"

            if commit_message is None:
                commit_message = f"docs: Remove task report {task_id}"

            response = requests.delete(
                url,
                headers={
                    "Authorization": f"token {self.gh_config.token}",
                    "Accept": "application/vnd.github.v3+json"
                },
                json={
                    "message": commit_message,
                    "sha": sha
                }
            )

            if response.status_code in [200, 204]:
                self.log.info(f"Deleted report from GitHub: {task_id}")
                return True
            else:
                self.log.error(f"Failed to delete report: {response.text}")
                return False

        except Exception as e:
            self.log.error(f"Failed to delete report from GitHub: {e}")
            return False

    def _get_repo_info(self) -> Optional[Tuple[str, str]]:
        """获取仓库信息"""
        repo = self.gh_config.repo
        if "/" not in repo:
            self.log.error(f"Invalid repository format: {repo}")
            return None

        parts = repo.split("/", 1)
        return parts[0], parts[1]

    def _get_file_sha(self, owner: str, repo: str, path: str) -> Optional[str]:
        """获取文件的 SHA"""
        url = f"{self.api_base}/repos/{owner}/{repo}/contents/{path}"

        response = requests.get(
            url,
            headers={
                "Authorization": f"token {self.gh_config.token}",
                "Accept": "application/vnd.github.v3+json"
            }
        )

        if response.status_code == 200:
            return response.json().get("sha")
        return None

    def _create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        sha: str = None
    ) -> bool:
        """创建或更新文件"""
        url = f"{self.api_base}/repos/{owner}/{repo}/contents/{path}"

        # Base64 编码内容
        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

        payload = {
            "message": message,
            "content": encoded_content
        }

        # 如果文件已存在，添加 SHA
        if sha:
            payload["sha"] = sha

        response = requests.put(
            url,
            headers={
                "Authorization": f"token {self.gh_config.token}",
                "Accept": "application/vnd.github.v3+json"
            },
            json=payload
        )

        if response.status_code in [200, 201]:
            return True
        else:
            self.log.error(f"Failed to create/update file: {response.text}")
            return False

    def _get_pages_url(self, task_id: str) -> str:
        """生成 GitHub Pages 访问链接"""
        # GitHub Pages URL 格式
        repo = self.gh_config.repo
        return f"https://{repo}/raw/{self.gh_config.branch}/{self.config.reports_path}{task_id}.html"

    def get_workflow_status(self, run_id: int) -> Optional[dict]:
        """获取工作流状态"""
        if not self.gh_config.token:
            return None

        repo_info = self._get_repo_info()
        if not repo_info:
            return None

        owner, repo = repo_info
        url = f"{self.api_base}/repos/{owner}/{repo}/actions/runs/{run_id}"

        response = requests.get(
            url,
            headers={
                "Authorization": f"token {self.gh_config.token}",
                "Accept": "application/vnd.github.v3+json"
            }
        )

        if response.status_code == 200:
            return response.json()
        return None


class GitHubWorkflowRunner:
    """GitHub Actions 工作流运行器"""

    def __init__(self, config: ReportConfig = None, github_config: GitHubConfig = None):
        self.config = config or ReportConfig()
        self.gh_config = github_config or GitHubConfig(
            repo=self.config.github_repo,
            token=self.config.github_token
        )
        self.log = get_logger("github_workflow")

    def trigger_deployment(self) -> Optional[int]:
        """
        触发 GitHub Actions 部署工作流

        Returns:
            工作流运行 ID
        """
        if not self.gh_config.token:
            self.log.error("GitHub token not configured")
            return None

        repo_info = self._get_repo_info()
        if not repo_info:
            return None

        owner, repo = repo_info
        url = f"{self.api_base}/repos/{owner}/{repo}/actions/workflows/deploy-reports.yml/dispatches"

        response = requests.post(
            url,
            headers={
                "Authorization": f"token {self.gh_config.token}",
                "Accept": "application/vnd.github.v3+json"
            },
            json={"ref": self.gh_config.branch}
        )

        if response.status_code in [200, 204]:
            # 等待工作流创建完成
            time.sleep(2)
            # 获取最新的运行 ID
            runs = self._get_latest_runs()
            if runs:
                return runs[0].get("id")
            return None
        else:
            self.log.error(f"Failed to trigger workflow: {response.text}")
            return None

    def _get_repo_info(self) -> Optional[Tuple[str, str]]:
        """获取仓库信息"""
        repo = self.gh_config.repo
        if "/" not in repo:
            return None
        return repo.split("/", 1)

    def _get_latest_runs(self, count: int = 1) -> list:
        """获取最新的工作流运行"""
        if not self.gh_config.token:
            return []

        repo_info = self._get_repo_info()
        if not repo_info:
            return []

        owner, repo = repo_info
        url = f"{self.api_base}/repos/{owner}/{repo}/actions/workflows/deploy-reports.yml/runs"

        response = requests.get(
            url,
            headers={
                "Authorization": f"token {self.gh_config.token}",
                "Accept": "application/vnd.github.v3+json"
            }
        )

        if response.status_code == 200:
            return response.json().get("workflow_runs", [])[:count]
        return []
