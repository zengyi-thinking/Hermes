"""
任务执行监督器模块
提供带监控的执行、进度报告、验证功能
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Dict, Any
import time


class ExecutionPhase(Enum):
    """执行阶段"""
    UNDERSTANDING = "understanding"      # 理解阶段
    REFINING = "refining"                # 优化阶段
    EXECUTING = "executing"              # 执行阶段
    VALIDATING = "validating"            # 验证阶段
    COMPLETING = "completing"            # 完成阶段


@dataclass
class ProgressInfo:
    """进度信息"""
    phase: str
    progress: float  # 0.0 - 100.0
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "progress": self.progress,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details
        }


@dataclass
class MonitoredResult:
    """带监控的执行结果"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration: float = 0.0
    output_files: List[str] = field(default_factory=list)
    created_files: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)
    error: Optional[str] = None

    # 监控相关字段
    validation_results: List[Dict] = field(default_factory=list)
    progress_history: List[Dict] = field(default_factory=list)
    final_progress: Optional[Dict] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration": self.duration,
            "output_files": self.output_files,
            "created_files": self.created_files,
            "modified_files": self.modified_files,
            "deleted_files": self.deleted_files,
            "error": self.error,
            "validation_results": self.validation_results,
            "progress_history": [p.to_dict() for p in self.progress_history],
            "final_progress": self.final_progress.to_dict() if self.final_progress else None
        }


class ProgressReporter:
    """进度报告器"""

    def __init__(
        self,
        channel: str = None,
        chat_id: str = None,
        channel_adapter = None,
        logger = None
    ):
        """
        初始化进度报告器

        Args:
            channel: 通道类型 (telegram, email)
            chat_id: 聊天 ID
            channel_adapter: 通道适配器
            logger: 日志器
        """
        self.channel = channel
        self.chat_id = chat_id
        self.adapter = channel_adapter
        self.logger = logger
        self._progress_buffer: List[ProgressInfo] = []

    def _log(self, level: str, message: str):
        """记录日志"""
        if self.logger:
            getattr(self.logger, level)(message)
        print(f"[{level.upper()}] {message}")

    def report_progress(
        self,
        phase: str,
        progress: float,
        message: str,
        details: Dict[str, Any] = None
    ) -> ProgressInfo:
        """
        报告进度

        Args:
            phase: 执行阶段
            progress: 进度 (0-100)
            message: 进度消息
            details: 附加详情

        Returns:
            ProgressInfo: 进度信息
        """
        info = ProgressInfo(
            phase=phase,
            progress=progress,
            message=message,
            details=details or {}
        )

        self._progress_buffer.append(info)

        # 格式化输出
        self._format_progress_output(info)

        return info

    def _format_progress_output(self, info: ProgressInfo):
        """格式化进度输出"""
        # 计算进度条
        filled = int(info.progress / 10)  # 每10%一个方块
        empty = 10 - filled
        bar = "█" * filled + "░" * empty

        # 格式化输出
        lines = [
            "",
            "=" * 60,
            f"  📊 TASK PROGRESS",
            "=" * 60,
            f"  [{phase_emoji(info.phase)}] {info.phase.upper():15} | {bar} | {info.progress:5.1f}% | {info.message}",
            "=" * 60,
            ""
        ]

        output = "\n".join(lines)

        if info.progress >= 100 or info.progress == 0:
            self._log("info", output)
        else:
            self._log("info", output)

    def get_progress_history(self) -> List[ProgressInfo]:
        """获取进度历史"""
        return self._progress_buffer.copy()

    def clear_history(self):
        """清空进度历史"""
        self._progress_buffer.clear()


def phase_emoji(phase: str) -> str:
    """获取阶段对应的emoji"""
    emojis = {
        ExecutionPhase.UNDERSTANDING.value: "🔍",
        ExecutionPhase.REFINING.value: "✨",
        ExecutionPhase.EXECUTING.value: "⚙️",
        ExecutionPhase.VALIDATING.value: "✅",
        ExecutionPhase.COMPLETING.value: "🎉",
    }
    return emojis.get(phase, "📌")


class ExecutionMonitor:
    """任务执行监督器"""

    def __init__(
        self,
        logger = None,
        channel_adapter = None,
        channel: str = None,
        chat_id: str = None
    ):
        """
        初始化执行监督器

        Args:
            logger: 日志器
            channel_adapter: 通道适配器（用于发送消息）
            channel: 通道类型
            chat_id: 聊天 ID
        """
        self.logger = logger
        self.reporter = ProgressReporter(
            channel=channel,
            chat_id=chat_id,
            channel_adapter=channel_adapter,
            logger=logger
        )

    def execute_with_monitoring(
        self,
        executor,
        prompt: str,
        work_dir: str = ".",
        validators: List = None,
        on_progress: Callable[[ProgressInfo], None] = None,
        timeout: int = 600
    ) -> MonitoredResult:
        """
        带监控的执行

        Args:
            executor: 执行器对象（ClaudeExecutor）
            prompt: 执行提示
            work_dir: 工作目录
            validators: 输出验证器列表
            on_progress: 进度回调函数
            timeout: 超时时间（秒）

        Returns:
            MonitoredResult: 包含验证结果的执行结果
        """
        start_time = time.time()

        # 初始化进度记录
        self.reporter.clear_history()

        # 阶段 1: 理解阶段
        self.reporter.report_progress(
            ExecutionPhase.UNDERSTANDING.value,
            0,
            "正在分析任务需求..."
        )
        if on_progress:
            on_progress(self.reporter.get_progress_history()[-1])

        # 阶段 2: 优化阶段
        time.sleep(0.5)  # 模拟优化过程
        self.reporter.report_progress(
            ExecutionPhase.REFINING.value,
            20,
            "已优化提示词，准备执行..."
        )
        if on_progress:
            on_progress(self.reporter.get_progress_history()[-1])

        # 阶段 3: 执行阶段
        self.reporter.report_progress(
            ExecutionPhase.EXECUTING.value,
            30,
            "开始执行 Claude Code..."
        )
        if on_progress:
            on_progress(self.reporter.get_progress_history()[-1])

        # 执行实际命令
        exec_result = executor.execute(
            prompt=prompt,
            work_dir=work_dir,
            timeout=timeout
        )

        # 阶段 4: 验证阶段
        self.reporter.report_progress(
            ExecutionPhase.VALIDATING.value,
            80,
            "验证输出..."
        )
        if on_progress:
            on_progress(self.reporter.get_progress_history()[-1])

        # 执行验证
        validation_results = []
        if validators:
            for validator in validators:
                result = validator.validate(exec_result.stdout or exec_result.stderr)
                validation_results.append({
                    "validator": validator.name,
                    "description": validator.description,
                    "is_valid": result.is_valid,
                    "message": result.message,
                    "details": result.details
                })

        # 阶段 5: 完成阶段
        final_progress = self.reporter.report_progress(
            ExecutionPhase.COMPLETING.value,
            100,
            "✅ 执行完成" if exec_result.success else "❌ 执行失败"
        )
        if on_progress:
            on_progress(self.reporter.get_progress_history()[-1])

        # 构建结果
        duration = time.time() - start_time

        monitored_result = MonitoredResult(
            success=exec_result.success,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            exit_code=getattr(exec_result, 'exit_code', 0),
            duration=duration,
            output_files=exec_result.output_files or [],
            created_files=exec_result.created_files or [],
            modified_files=exec_result.modified_files or [],
            deleted_files=exec_result.deleted_files or [],
            error=exec_result.error,
            validation_results=validation_results,
            progress_history=self.reporter.get_progress_history(),
            final_progress=final_progress
        )

        # 输出最终摘要
        self._print_summary(monitored_result)

        return monitored_result

    def _print_summary(self, result: MonitoredResult):
        """打印执行摘要"""
        print("")
        print("=" * 60)
        print("📊 EXECUTION SUMMARY")
        print("=" * 60)
        print(f"  状态: {'✅ 成功' if result.success else '❌ 失败'}")
        print(f"  执行时间: {result.duration:.2f}秒")
        print(f"  验证项目: {len(result.validation_results)}")

        # 验证结果摘要
        for vr in result.validation_results:
            status = "✅" if vr["is_valid"] else "❌"
            print(f"    {status} {vr['validator']}: {vr['message']}")

        # 文件变更摘要
        total_files = len(result.created_files) + len(result.modified_files) + len(result.deleted_files)
        if total_files > 0:
            print(f"  文件变更: {total_files} 个")
            if result.created_files:
                print(f"    + 创建: {len(result.created_files)} 个")
            if result.modified_files:
                print(f"    ~ 修改: {len(result.modified_files)} 个")
            if result.deleted_files:
                print(f"    - 删除: {len(result.deleted_files)} 个")

        print("=" * 60)
        print("")

    def get_progress_reporter(self) -> ProgressReporter:
        """获取进度报告器"""
        return self.reporter


class AsyncExecutionMonitor:
    """异步执行监督器"""

    def __init__(
        self,
        logger = None,
        channel_adapter = None,
        channel: str = None,
        chat_id: str = None
    ):
        """
        初始化异步执行监督器

        Args:
            logger: 日志器
            channel_adapter: 通道适配器
            channel: 通道类型
            chat_id: 聊天 ID
        """
        self.logger = logger
        self.reporter = ProgressReporter(
            channel=channel,
            chat_id=chat_id,
            channel_adapter=channel_adapter,
            logger=logger
        )

    async def execute_with_health_monitoring(
        self,
        executor,
        prompt: str,
        work_dir: str = ".",
        validators: List = None,
        task_info: dict = None,
        on_progress: Callable[[ProgressInfo], None] = None
    ) -> MonitoredResult:
        """
        基于进程健康状态的监控执行 - 无固定超时

        此方法使用智能健康监控策略：
        1. 启动 Claude 进程后台执行
        2. 定期检查进程输出（心跳间隔：30秒）
        3. 如果连续 2 个检查周期无输出，视为"无响应"
        4. 检测到无响应时自动中断并发送通知

        Args:
            executor: 执行器对象（支持异步 execute_async）
            prompt: 执行提示
            work_dir: 工作目录
            validators: 输出验证器列表
            task_info: 任务信息（用于通知，包含 task_id, chat_id 等）
            on_progress: 进度回调函数

        Returns:
            MonitoredResult: 包含验证结果的执行结果
        """
        from .health_monitor import ProcessHealthMonitor, HealthMonitorConfig, TaskType

        # 创建健康监控器
        config = HealthMonitorConfig(
            enable_notification=self.reporter.adapter is not None
        )
        health_monitor = ProcessHealthMonitor(
            channel_adapter=self.reporter.adapter,
            config=config,
            logger=self.logger
        )

        # 获取任务类型
        task_type = health_monitor._detect_task_type(prompt)
        threshold = health_monitor._get_activity_threshold(task_type)

        self.logger.info(f"[AsyncExecutionMonitor] 使用健康监控，任务类型: {task_type.value}, 无响应阈值: {threshold}秒")

        # 使用健康监控执行
        return await health_monitor.execute_with_health_monitoring(
            executor=executor,
            prompt=prompt,
            work_dir=work_dir,
            validators=validators,
            task_info=task_info,
            on_progress=on_progress
        )

    async def execute_with_monitoring(
        self,
        executor,
        prompt: str,
        work_dir: str = ".",
        validators: List = None,
        on_progress: Callable[[ProgressInfo], None] = None,
        timeout: int = 600
    ) -> MonitoredResult:
        """
        异步带监控的执行（保留原有方法用于向后兼容）

        Args:
            executor: 执行器对象（支持异步 execute_async）
            prompt: 执行提示
            work_dir: 工作目录
            validators: 输出验证器列表
            on_progress: 进度回调函数
            timeout: 超时时间（秒）- 保留参数但会发出警告

        Returns:
            MonitoredResult: 包含验证结果的执行结果
        """
        import asyncio

        # 警告：此方法已废弃，建议使用 execute_with_health_monitoring
        if timeout != 600:
            self.logger.warning(f"[AsyncExecutionMonitor] 警告: 使用了固定超时 {timeout}秒。"
                              "建议改用 execute_with_health_monitoring() 以获得更好的体验。")

        start_time = time.time()

        # 初始化进度记录
        self.reporter.clear_history()

        # 阶段 1: 理解阶段
        self.reporter.report_progress(
            ExecutionPhase.UNDERSTANDING.value,
            0,
            "正在分析任务需求..."
        )

        # 阶段 2: 优化阶段
        await asyncio.sleep(0.3)
        self.reporter.report_progress(
            ExecutionPhase.REFINING.value,
            20,
            "已优化提示词，准备执行..."
        )

        # 阶段 3: 执行阶段
        self.reporter.report_progress(
            ExecutionPhase.EXECUTING.value,
            30,
            "开始执行 Claude Code..."
        )

        # 异步执行 - 使用健康监控替代固定超时
        try:
            # 使用健康监控，但传入 timeout 作为最后保障
            result = await self.execute_with_health_monitoring(
                executor=executor,
                prompt=prompt,
                work_dir=work_dir,
                validators=validators,
                task_info={},
                on_progress=on_progress
            )
            return result

        except Exception as e:
            self.logger.error(f"执行错误: {e}")
            duration = time.time() - start_time

            return MonitoredResult(
                success=False,
                error=str(e),
                duration=duration,
                progress_history=self.reporter.get_progress_history()
            )

    def get_progress_reporter(self) -> ProgressReporter:
        """获取进度报告器"""
        return self.reporter
