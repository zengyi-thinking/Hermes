"""
HTML 报告生成器
生成美观的任务完成可视化报告
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import html
import json

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.state.schemas import TaskInfo, ExecutionResult, RefinedResult
from ..utils.logger import get_logger
from config.reporter import ReportConfig, ReportTheme


class HTMLReportGenerator:
    """
    HTML 报告生成器

    功能：
    - 使用 Jinja2 模板生成现代化 HTML 报告
    - 支持深色/浅色主题自适应
    - 响应式布局
    - 包含任务信息、执行结果、时间线、统计等
    """

    def __init__(self, config: ReportConfig = None):
        self.config = config or ReportConfig()
        self.log = get_logger("html_reporter")

        # 初始化 Jinja2 环境
        template_dir = Path(self.config.template_dir)
        if template_dir.exists():
            self.jinja_env = Environment(
                loader=FileSystemLoader(str(template_dir)),
                autoescape=select_autoescape(['html', 'xml'])
            )
        else:
            self.jinja_env = None
            self.log.warning(f"Template directory not found: {template_dir}")

    def generate(
        self,
        task: TaskInfo,
        refined: RefinedResult,
        exec_result: ExecutionResult,
        output_path: Optional[str] = None
    ) -> str:
        """
        生成 HTML 报告

        Args:
            task: 任务信息
            refined: 优化结果
            exec_result: 执行结果
            output_path: 输出路径，为空时使用默认路径

        Returns:
            报告文件路径
        """
        if not self.jinja_env:
            raise RuntimeError("Jinja2 environment not initialized")

        # 确定输出路径
        if output_path is None:
            output_path = self.config.get_output_path(task.task_id)

        # 渲染模板
        template = self.jinja_env.get_template("task_summary.html")
        html_content = template.render(
            task=task,
            refined=refined,
            exec_result=exec_result,
            config=self.config,
            theme=self._detect_theme(),
            stats=self._calculate_stats(task, refined, exec_result),
            timeline=self._build_timeline(task, exec_result),
            now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        # 保存文件
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        self.log.info(f"Generated HTML report: {output_file}")

        return str(output_file)

    def generate_with_stats(
        self,
        task: TaskInfo,
        exec_result: ExecutionResult,
        output_path: Optional[str] = None
    ) -> str:
        """
        生成带统计信息的完整报告

        Args:
            task: 任务信息
            exec_result: 执行结果
            output_path: 输出路径

        Returns:
            报告文件路径
        """
        # 创建空的 RefinedResult 用于兼容
        refined = RefinedResult(
            refined_prompt="",
            confidence=0.0,
            intent_type="unknown"
        )
        return self.generate(task, refined, exec_result, output_path)

    def generate_inline(
        self,
        task: TaskInfo,
        refined: RefinedResult,
        exec_result: ExecutionResult
    ) -> str:
        """
        生成内联 HTML（不保存文件）

        Args:
            task: 任务信息
            refined: 优化结果
            exec_result: 执行结果

        Returns:
            HTML 内容字符串
        """
        if not self.jinja_env:
            raise RuntimeError("Jinja2 environment not initialized")

        template = self.jinja_env.get_template("task_summary.html")
        html_content = template.render(
            task=task,
            refined=refined,
            exec_result=exec_result,
            config=self.config,
            theme=self._detect_theme(),
            stats=self._calculate_stats(task, refined, exec_result),
            timeline=self._build_timeline(task, exec_result),
            now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        return html_content

    def _detect_theme(self) -> str:
        """检测主题"""
        if self.config.theme == ReportTheme.AUTO:
            # 可以通过检测系统偏好来自动选择
            return "light"  # 默认浅色主题
        return self.config.theme.value

    def _calculate_stats(
        self,
        task: TaskInfo,
        refined: RefinedResult,
        exec_result: ExecutionResult
    ) -> dict:
        """计算统计数据"""
        # 统计文件数 - 优先使用带类型的字段
        if hasattr(exec_result, 'all_files'):
            all_files = exec_result.all_files
        else:
            output_files = exec_result.output_files or []
            task_files = task.output_files or []
            all_files = list(set(output_files + task_files))  # 去重

        stats = {
            "duration_seconds": 0,
            "file_count": len(all_files),
            "created_count": len(getattr(exec_result, 'created_files', [])),
            "modified_count": len(getattr(exec_result, 'modified_files', [])),
            "deleted_count": len(getattr(exec_result, 'deleted_files', [])),
            "confidence_percent": 0,
            "status": "success" if exec_result.success else "failed"
        }

        # 计算执行时长 - 优先使用 exec_result.duration
        if exec_result.duration and exec_result.duration > 0:
            stats["duration_seconds"] = int(exec_result.duration)
        elif task.started_at and task.completed_at:
            # 备选方案：从 datetime 计算
            try:
                duration = (task.completed_at - task.started_at).total_seconds()
                stats["duration_seconds"] = int(duration)
            except (TypeError, AttributeError):
                pass

        # 置信度 - 优先使用 refined.confidence
        if refined and hasattr(refined, 'confidence') and refined.confidence:
            stats["confidence_percent"] = int(refined.confidence * 100)
        elif task.confidence:
            stats["confidence_percent"] = int(task.confidence * 100)

        return stats

    def _build_timeline(
        self,
        task: TaskInfo,
        exec_result: ExecutionResult
    ) -> List[dict]:
        """构建时间线"""
        timeline = []

        # 任务创建
        timeline.append({
            "time": task.created_at.strftime('%H:%M:%S'),
            "label": "任务创建",
            "icon": "📥",
            "description": f"任务 ID: {task.task_id[:12]}..."
        })

        # 开始执行
        if task.started_at:
            timeline.append({
                "time": task.started_at.strftime('%H:%M:%S'),
                "label": "开始执行",
                "icon": "▶️",
                "description": f"由 {task.sender} 发起"
            })

        # 执行完成
        if task.completed_at:
            timeline.append({
                "time": task.completed_at.strftime('%H:%M:%S'),
                "label": "任务完成",
                "icon": "✅" if exec_result.success else "❌",
                "description": f"执行 {'成功' if exec_result.success else '失败'} - 耗时 {int(exec_result.duration)}秒"
            })

        return timeline

    def cleanup_old_reports(self, days: int = None) -> int:
        """
        清理旧报告

        Args:
            days: 保留天数

        Returns:
            删除的文件数量
        """
        days = days or self.config.retention_days
        if days <= 0:
            return 0

        output_dir = Path(self.config.output_dir)
        if not output_dir.exists():
            return 0

        cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)
        deleted_count = 0

        for file_path in output_dir.glob("*.html"):
            if file_path.stat().st_mtime < cutoff_time:
                file_path.unlink()
                deleted_count += 1
                self.log.info(f"Cleaned up old report: {file_path}")

        return deleted_count


class ReportLinkShortener:
    """链接缩短服务（占位实现）"""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or "https://your-shortener.com"

    def shorten(self, long_url: str) -> str:
        """
        缩短链接

        Args:
            long_url: 原始链接

        Returns:
            缩短后的链接
        """
        # 占位实现，实际使用时可以接入短链接服务
        return long_url
