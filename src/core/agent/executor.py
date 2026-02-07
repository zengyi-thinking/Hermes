"""
Claude CLI 执行器
"""
import subprocess
import shutil
import os
import re
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime

from ..state.schemas import ExecutionResult


@dataclass
class ExecutorConfig:
    """执行器配置"""
    cli_path: str = "claude"
    work_dir: str = "."
    timeout: int = 600
    non_interactive: bool = True
    git_bash_path: str = ""  # Windows 上 git-bash 的路径


class ClaudeExecutor:
    """
    Claude Code CLI 执行器

    使用 claude -p (print mode) 进行非交互式命令执行
    """

    # Windows 上常见的 git-bash 路径
    WINDOWS_GIT_BASH_PATHS = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"D:\software\Git\bin\bash.exe",  # 用户安装位置
        r"C:\Git\bin\bash.exe",
    ]

    def __init__(self, config: ExecutorConfig = None):
        self.config = config or ExecutorConfig()
        self._claude_path: Optional[str] = None
        self._git_bash_path: Optional[str] = None
        self._logger = None

    def _get_logger(self):
        """获取或创建 logger"""
        if self._logger is None:
            from ..utils.logger import get_logger
            self._logger = get_logger("executor")
        return self._logger

    def _debug_log(self, message: str):
        """记录调试日志"""
        try:
            self._get_logger().info(message)
        except Exception:
            pass  # 如果 logger 不可用，忽略

    def _find_git_bash(self) -> Optional[str]:
        """查找 git-bash 路径 (Windows)"""
        if self._git_bash_path:
            return self._git_bash_path

        # 1. 先检查环境变量
        bash_path = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH") or os.environ.get("CLAUDE_CODE_BASH_PATH")
        if bash_path and Path(bash_path).exists():
            self._git_bash_path = bash_path
            return self._git_bash_path

        # 2. 检查配置
        if self.config.git_bash_path and Path(self.config.git_bash_path).exists():
            self._git_bash_path = self.config.git_bash_path
            return self._git_bash_path

        # 3. 搜索常见路径
        for path in self.WINDOWS_GIT_BASH_PATHS:
            if Path(path).exists():
                self._git_bash_path = path
                return self._git_bash_path

        # 4. 尝试 where bash
        bash_where = shutil.which("bash")
        if bash_where:
            self._git_bash_path = bash_where
            return self._git_bash_path

        return None

    def _find_claude_cli(self) -> str:
        """查找 Claude CLI 路径"""
        if self._claude_path:
            return self._claude_path

        cli_path = self.config.cli_path

        # 检查是否是完整路径
        if Path(cli_path).exists():
            self._claude_path = cli_path
            return self._claude_path

        # 从环境变量检查
        claude_path = shutil.which("claude")
        if claude_path:
            self._claude_path = claude_path
            return self._claude_path

        # 常见安装路径
        common_paths = [
            # Windows
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Claude" / "claude.exe",
            Path("C:/Program Files/Claude/claude.exe"),
            Path("C:/Program Files (x86)/Claude/claude.exe"),
            Path.home() / ".local/bin/claude",
            # Linux/Mac
            Path("/usr/local/bin/claude"),
            Path("/usr/bin/claude"),
            Path.home() / "Library" / "Application Support" / "Claude" / "claude",
        ]

        for path in common_paths:
            if path.exists():
                self._claude_path = str(path)
                return self._claude_path

        # 返回原值，让运行时决定
        return cli_path

    def _is_windows(self) -> bool:
        """检查是否是 Windows 系统"""
        return os.name == 'nt'

    def execute(
        self,
        prompt: str,
        work_dir: str = None,
        timeout: int = None,
        session_name: str = None
    ) -> ExecutionResult:
        """
        执行 Claude Code 命令

        Args:
            prompt: 要执行的指令
            work_dir: 工作目录
            timeout: 超时时间（秒）- 为 None 时使用 ProcessHealthMonitor 控制，不再强制超时
            session_name: 会话名称（用于恢复上下文）

        Returns:
            ExecutionResult: 执行结果
        """
        start_time = datetime.now()

        work_dir = Path(work_dir) if work_dir else Path(self.config.work_dir)
        # timeout=None 表示由健康监控器控制，不使用固定超时
        timeout = timeout if timeout is not None else self.config.timeout

        # 构建命令
        cmd = self._build_command(prompt, session_name)

        # 设置环境变量
        env = {
            **os.environ,
            "CLAUDE_NO_INTERACTIVE": "1",
            "CLAUDE_LOG_FILE": "",
            "TERM": "xterm-256color",
        }

        # Windows 上使用 git-bash 运行
        if self._is_windows():
            git_bash = self._find_git_bash()
            if git_bash:
                # 通过 git-bash 运行
                env["CHERE_INVOKER"] = "1"  # 不要改变目录
                env["MSYS2_PATH_TYPE"] = "minimal"
                # 设置 Claude 需要的 git-bash 路径 (Windows 路径格式)
                env["CLAUDE_CODE_GIT_BASH_PATH"] = git_bash.replace('/', '\\')

                # 转换工作目录为 bash 路径
                bash_work_dir = self._to_bash_path(str(work_dir))

                # 构建 git-bash 命令
                bash_cmd = [
                    git_bash,
                    "-lc",
                    f'cd "{bash_work_dir}" && {" ".join(self._escape_arg(arg) for arg in cmd)}'
                ]
                cmd = bash_cmd
                # 不使用 shell=True
                use_shell = False
            else:
                use_shell = True
        else:
            use_shell = False

        try:
            # 添加调试日志
            self._debug_log(f"Executing command: {cmd}")
            self._debug_log(f"Work dir: {work_dir}")

            result = subprocess.run(
                cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                encoding="utf-8",
                errors="replace",
                shell=use_shell
            )

            self._debug_log(f"Return code: {result.returncode}")
            self._debug_log(f"Stdout: {result.stdout[:500] if result.stdout else 'empty'}")
            if result.stderr:
                self._debug_log(f"Stderr: {result.stderr[:500]}")

            duration = (datetime.now() - start_time).total_seconds()

            # 解析输出文件（带类型）
            output = result.stdout + result.stderr
            created_files, modified_files, deleted_files = self._extract_file_changes(output)
            all_files = created_files + modified_files + deleted_files

            return ExecutionResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration=duration,
                output_files=all_files,
                created_files=created_files,
                modified_files=modified_files,
                deleted_files=deleted_files
            )

        except subprocess.TimeoutExpired:
            duration = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                success=False,
                error="Command timed out",
                exit_code=-1,
                duration=duration
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                success=False,
                error=str(e),
                exit_code=-1,
                duration=duration
            )

    def _escape_arg(self, arg: str) -> str:
        """转义参数 - 确保在 bash 中安全执行"""
        if not arg:
            return arg

        # 使用 $'...' 语法转义特殊字符
        # 这个语法可以处理引号、换行等特殊字符
        escaped = arg.replace('\\', '\\\\')
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace('`', '\\`')
        escaped = escaped.replace('$', '\\$')
        escaped = escaped.replace('\n', '\\n')
        escaped = escaped.replace('\r', '\\r')
        escaped = escaped.replace('\t', '\\t')

        return f"$'{escaped}'"

    def _to_bash_path(self, windows_path: str) -> str:
        """将 Windows 路径转换为 git-bash 路径格式"""
        if not windows_path:
            return windows_path

        # 替换盘符
        if windows_path[1:2] == ':':
            drive = windows_path[0].lower()
            rest = windows_path[2:].replace('\\', '/')
            return f'/{drive}/{rest}'
        return windows_path

    def _build_command(
        self,
        prompt: str,
        session_name: str = None
    ) -> list:
        """构建命令"""
        claude_path = self._find_claude_cli()

        cmd = [
            self._to_bash_path(claude_path),
            "-p",  # print mode (non-interactive)
        ]

        # 添加会话参数
        if session_name:
            cmd.extend(["--continue", f"--session={session_name}"])

        # 添加提示 (作为最后一个参数)
        cmd.append(prompt)

        return cmd

    def _extract_output_files(self, output: str) -> list:
        """从输出中提取生成的文件（兼容旧接口）"""
        created, modified, deleted = self._extract_file_changes(output)
        return created + modified + deleted

    def _extract_file_changes(self, output: str) -> tuple:
        """
        从输出中提取带类型的文件变更

        Returns:
            tuple: (created_files, modified_files, deleted_files)
        """
        created = []
        modified = []
        deleted = []

        # 创建模式
        created_patterns = [
            r'[Cc]reated\s+[\'"]?([^\s\'"\'")]+\.[a-zA-Z0-9_]+[\'"]?',
            r'[Nn]ew\s+file[:\s]+([^\s]+)',
            r'[Ww]rote\s+to\s+([^\s]+)',
            r'[Ss]aved\s+([^\s]+)',
            r'([a-zA-Z0-9_\-/]+\.[a-zA-Z0-9_]+)\s+created',
        ]

        # 修改模式
        modified_patterns = [
            r'[Mm]odified\s+([^\s]+)',
            r'[Uu]pdated\s+([^\s]+)',
            r'[Cc]hanged\s+([^\s]+)',
        ]

        # 删除模式
        deleted_patterns = [
            r'[Dd]eleted\s+([^\s]+)',
            r'[Rr]emoved\s+([^\s]+)',
        ]

        for pattern in created_patterns:
            matches = re.findall(pattern, output)
            for match in matches:
                # 清理匹配结果
                file_path = match.strip().strip("'\"")
                if file_path and not file_path.startswith('http'):
                    created.append(file_path)

        for pattern in modified_patterns:
            matches = re.findall(pattern, output)
            for match in matches:
                file_path = match.strip().strip("'\"")
                if file_path and not file_path.startswith('http'):
                    modified.append(file_path)

        for pattern in deleted_patterns:
            matches = re.findall(pattern, output)
            for match in matches:
                file_path = match.strip().strip("'\"")
                if file_path and not file_path.startswith('http'):
                    deleted.append(file_path)

        # 去重
        created = list(dict.fromkeys(created))
        modified = list(dict.fromkeys(modified))
        deleted = list(dict.fromkeys(deleted))

        return created, modified, deleted

    async def execute_async(
        self,
        prompt: str,
        work_dir: str = None,
        timeout: int = None
    ) -> ExecutionResult:
        """
        异步执行命令（包装同步方法）

        Args:
            prompt: 要执行的指令
            work_dir: 工作目录
            timeout: 超时时间（秒）

        Returns:
            ExecutionResult: 执行结果
        """
        # 使用 run_in_executor 替代 asyncio.to_thread，提供更好的兼容性
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.execute(prompt, work_dir, timeout)
        )

    def get_version(self) -> Optional[str]:
        """获取 Claude CLI 版本"""
        try:
            cmd = [self._find_claude_cli(), "--version"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout.strip() or result.stderr.strip()
        except Exception:
            return None

    def test_execution(self, work_dir: str = None) -> Tuple[bool, str]:
        """
        测试 Claude 是否能正常执行

        Returns:
            (success, message)
        """
        # 测试 1: 检查 Claude 路径
        claude_path = self._find_claude_cli()
        if not claude_path:
            return False, "找不到 Claude CLI"

        # 测试 2: 检查 git-bash (Windows)
        if self._is_windows():
            git_bash = self._find_git_bash()
            if not git_bash:
                return False, "Windows 上找不到 git-bash，请安装 Git for Windows"
            # 测试 git-bash 是否可用
            try:
                bash_test = subprocess.run(
                    [git_bash, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if bash_test.returncode != 0:
                    return False, f"git-bash 测试失败: {bash_test.stderr}"
            except Exception as e:
                return False, f"git-bash 不可用: {e}"

        # 测试 3: 尝试执行简单命令
        result = self.execute(
            "Hello, this is a test. Please just reply with 'TEST OK'.",
            work_dir=work_dir or ".",
            timeout=30
        )

        if result.success:
            return True, f"Claude 执行正常\n{result.stdout[:200]}"
        else:
            return False, f"Claude 执行失败:\n{result.stderr[:300]}"

    def get_environment_info(self) -> dict:
        """获取环境信息"""
        return {
            "platform": "Windows" if self._is_windows() else "Linux/Mac",
            "claude_path": self._find_claude_cli(),
            "claude_version": self.get_version(),
            "git_bash_path": self._find_git_bash() if self._is_windows() else None,
            "work_dir": self.config.work_dir,
            "timeout": self.config.timeout,
        }
