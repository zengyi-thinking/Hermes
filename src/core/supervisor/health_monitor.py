"""
进程健康监控模块
基于进程健康状态的监控 - 智能判断，无固定超时
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional, Dict, Any
from enum import Enum

from .executor_monitor import MonitoredResult, ProgressReporter, ExecutionPhase


class TaskType(Enum):
    """任务类型枚举"""
    FILE_OPERATION = "file_operation"      # 文件操作
    CODE_GENERATION = "code_generation"    # 代码生成
    ANALYSIS = "analysis"                   # 代码分析
    REFACTORING = "refactoring"             # 重构任务
    SEARCH = "search"                       # 搜索任务
    UNKNOWN = "unknown"                     # 未知类型


@dataclass
class HealthMonitorConfig:
    """健康监控配置"""
    # 任务类型对应的无响应判断时间（秒）
    thresholds: Dict[str, int] = field(default_factory=lambda: {
        "file_operation": 60,      # 文件操作：60秒无输出视为无响应
        "code_generation": 120,    # 代码生成：120秒
        "analysis": 180,           # 代码分析：180秒
        "refactoring": 240,        # 重构任务：240秒
        "search": 90,              # 搜索任务：90秒
        "unknown": 120             # 默认：120秒
    })
    # 心跳间隔（秒）
    heartbeat_interval: int = 30
    # 是否启用 Telegram 通知
    enable_notification: bool = True


class ProcessHealthMonitor:
    """
    基于进程健康状态的监控器 - 智能判断，无固定超时

    监控策略：
    1. 启动 Claude 进程后台执行
    2. 定期检查进程输出（心跳间隔：默认30秒）
    3. 如果连续 2 个检查周期无输出，视为"无响应"
    4. 检测到无响应时自动中断并发送通知
    """

    def __init__(
        self,
        channel_adapter=None,
        config: HealthMonitorConfig = None,
        logger=None
    ):
        """
        初始化健康监控器

        Args:
            channel_adapter: 通道适配器（用于发送 Telegram 通知）
            config: 健康监控配置
            logger: 日志器
        """
        self.config = config or HealthMonitorConfig()
        self.channel_adapter = channel_adapter
        self.logger = logger
        self.reporter = ProgressReporter(
            channel="telegram" if channel_adapter else None,
            channel_adapter=channel_adapter,
            logger=logger
        )

    def _log(self, level: str, message: str):
        """记录日志"""
        if self.logger:
            getattr(self.logger, level)(message)
        print(f"[{level.upper()}] [HealthMonitor] {message}")

    def _detect_task_type(self, prompt: str) -> TaskType:
        """
        从 prompt 中智能推断任务类型

        Args:
            prompt: 任务提示词

        Returns:
            TaskType: 推断的任务类型
        """
        prompt_lower = prompt.lower()

        # 检测代码生成（FastAPI/Flask/Django 等框架项目）
        if any(kw in prompt_lower for kw in ["创建", "生成", "write", "create", "generate"]):
            if any(kw in prompt_lower for kw in ["fastapi", "flask", "django", "fastapi项目", "web项目"]):
                return TaskType.CODE_GENERATION
            return TaskType.FILE_OPERATION

        # 检测代码分析
        if any(kw in prompt_lower for kw in ["分析", "review", "analyze", "检查", "审查"]):
            return TaskType.ANALYSIS

        # 检测重构
        if any(kw in prompt_lower for kw in ["重构", "refactor", "优化", "optimize", "重写"]):
            return TaskType.REFACTORING

        # 检测搜索
        if any(kw in prompt_lower for kw in ["搜索", "search", "查找", "find", "定位"]):
            return TaskType.SEARCH

        return TaskType.UNKNOWN

    def _get_activity_threshold(self, task_type: TaskType) -> int:
        """
        根据任务类型获取无响应判断时间

        Args:
            task_type: 任务类型

        Returns:
            int: 无响应判断时间（秒）
        """
        return self.config.thresholds.get(task_type.value, self.config.thresholds["unknown"])

    async def _send_health_alert(
        self,
        task_info: dict,
        last_activity_time: float,
        inactive_seconds: int
    ):
        """发送进程健康告警通知"""
        if not self.channel_adapter or not self.config.enable_notification:
            return

        try:
            last_time_str = datetime.fromtimestamp(last_activity_time).strftime("%H:%M:%S")
            task_id = task_info.get("task_id", "unknown")

            message = (
                f"⚠️ **进程监控告警**\n\n"
                f"任务可能陷入循环或卡住：\n"
                f"- 任务ID: `{task_id}`\n"
                f"- 任务类型: `{task_info.get('task_type', 'unknown')}`\n"
                f"- 最后活动时间: `{last_time_str}`\n"
                f"- 距今无活动: `{inactive_seconds}`秒\n\n"
                f"系统将自动中断此任务。"
            )

            # 发送通知
            chat_id = task_info.get("chat_id")
            if chat_id:
                if hasattr(self.channel_adapter, 'send_markdown'):
                    await self.channel_adapter.send_markdown(chat_id, message)
                elif hasattr(self.channel_adapter, 'send'):
                    await self.channel_adapter.send(chat_id, message)

            self._log("info", f"健康告警已发送：{inactive_seconds}秒无活动")

        except Exception as e:
            self._log("error", f"发送健康告警失败: {e}")

    async def _send_task_interrupted_notification(
        self,
        task_info: dict,
        reason: str,
        duration: float
    ):
        """发送任务被中断的通知"""
        if not self.channel_adapter or not self.config.enable_notification:
            return

        try:
            task_id = task_info.get("task_id", "unknown")

            message = (
                f"🛑 **任务监控通知**\n\n"
                f"任务已自动中断：\n"
                f"- 任务ID: `{task_id}`\n"
                f"- 中断原因: `{reason}`\n"
                f"- 任务类型: `{task_info.get('task_type', 'unknown')}`\n"
                f"- 已执行时间: `{duration:.1f}`秒\n\n"
                f"如需继续，请重新发送任务指令。"
            )

            chat_id = task_info.get("chat_id")
            if chat_id:
                if hasattr(self.channel_adapter, 'send_markdown'):
                    await self.channel_adapter.send_markdown(chat_id, message)
                elif hasattr(self.channel_adapter, 'send'):
                    await self.channel_adapter.send(chat_id, message)

        except Exception as e:
            self._log("error", f"发送中断通知失败: {e}")

    async def execute_with_health_monitoring(
        self,
        executor,
        prompt: str,
        work_dir: str = ".",
        validators: List = None,
        task_info: dict = None,
        on_progress: Callable = None
    ) -> MonitoredResult:
        """
        基于进程健康状态的监控执行 - 无固定超时

        Args:
            executor: 执行器对象（ClaudeExecutor，支持异步 execute_async）
            prompt: 执行提示
            work_dir: 工作目录
            validators: 输出验证器列表
            task_info: 任务信息（用于通知）
            on_progress: 进度回调函数

        Returns:
            MonitoredResult: 包含验证结果的执行结果
        """
        start_time = time.time()
        task_id = task_info.get("task_id", "unknown") if task_info else "unknown"

        # 检测任务类型
        task_type = self._detect_task_type(prompt)
        threshold = self._get_activity_threshold(task_type)

        self._log("info", f"任务类型: {task_type.value}, 无响应阈值: {threshold}秒")

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
        await asyncio.sleep(0.3)
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

        # 创建异步任务执行
        exec_task = asyncio.create_task(
            executor.execute_async(prompt=prompt, work_dir=work_dir, timeout=None)
        )

        # 初始化监控状态
        last_activity_time = start_time
        last_output_len = 0
        check_count = 0
        inactive_periods = 0
        max_inactive_periods = 2  # 连续2个检查周期无活动则中断

        self._log("info", f"开始健康监控，任务ID: {task_id}")

        try:
            while not exec_task.done():
                # 等待心跳间隔或任务完成
                try:
                    await asyncio.wait_for(exec_task, timeout=self.config.heartbeat_interval)
                except asyncio.TimeoutError:
                    # 检查超时 - 这是预期的行为，继续监控
                    pass

                check_count += 1
                current_time = time.time()
                elapsed = current_time - start_time

                # 检查任务是否完成
                if exec_task.done():
                    break

                # 获取当前输出长度（通过检查执行器的状态）
                current_output_len = len(exec_task.result().stdout) if exec_task.done() else last_output_len

                # 检测是否有新输出
                if current_output_len > last_output_len:
                    # 有新输出，进程是健康的
                    last_activity_time = current_time
                    last_output_len = current_output_len
                    inactive_periods = 0
                    self._log("debug", f"检测到新输出 ({current_output_len - (last_output_len - (current_output_len - last_output_len))} bytes)")
                else:
                    # 无新输出，增加无响应周期计数
                    inactive_periods += 1

                inactive_seconds = int(current_time - last_activity_time)

                # 打印心跳日志
                self._log("info", f"心跳 #{check_count}: 已运行 {elapsed:.0f}秒, 无活动 {inactive_seconds}秒, "
                              f"无响应周期: {inactive_periods}/{max_inactive_periods}")

                # 如果连续2个周期无活动，中断任务
                if inactive_periods >= max_inactive_periods and inactive_seconds >= threshold:
                    self._log("warning", f"检测到进程无响应: {inactive_seconds}秒无活动，中断任务")

                    # 发送告警通知
                    await self._send_health_alert(
                        task_info=task_info or {},
                        last_activity_time=last_activity_time,
                        inactive_seconds=inactive_seconds
                    )

                    # 取消任务
                    exec_task.cancel()

                    # 发送中断通知
                    duration = time.time() - start_time
                    await self._send_task_interrupted_notification(
                        task_info=task_info or {},
                        reason=f"检测到 {inactive_seconds}秒无活动",
                        duration=duration
                    )

                    # 构建被中断的结果
                    try:
                        await exec_task
                    except asyncio.CancelledError:
                        pass

                    # 创建中断结果
                    monitored_result = await self._create_interrupted_result(
                        start_time=start_time,
                        task_type=task_type.value,
                        reason=f"进程无响应 ({inactive_seconds}秒)",
                        task_info=task_info
                    )
                    return monitored_result

        except asyncio.CancelledError:
            self._log("info", "任务被取消")
            duration = time.time() - start_time

            monitored_result = await self._create_interrupted_result(
                start_time=start_time,
                task_type=task_type.value,
                reason="任务被取消",
                task_info=task_info
            )
            return monitored_result

        except Exception as e:
            self._log("error", f"监控过程出错: {e}")
            duration = time.time() - start_time

            monitored_result = MonitoredResult(
                success=False,
                error=str(e),
                duration=duration,
                progress_history=self.reporter.get_progress_history()
            )
            return monitored_result

        # 获取执行结果
        try:
            exec_result = exec_task.result()
        except asyncio.CancelledError:
            exec_result = None

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
        if validators and exec_result:
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
            "✅ 执行完成" if (exec_result and exec_result.success) else "❌ 执行失败"
        )
        if on_progress:
            on_progress(self.reporter.get_progress_history()[-1])

        # 构建结果
        duration = time.time() - start_time

        if exec_result:
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
        else:
            monitored_result = MonitoredResult(
                success=False,
                error="任务被中断",
                duration=duration,
                validation_results=validation_results,
                progress_history=self.reporter.get_progress_history(),
                final_progress=final_progress
            )

        return monitored_result

    async def _create_interrupted_result(
        self,
        start_time: float,
        task_type: str,
        reason: str,
        task_info: dict = None
    ) -> MonitoredResult:
        """
        创建被中断的任务结果

        Args:
            start_time: 开始时间
            task_type: 任务类型
            reason: 中断原因
            task_info: 任务信息

        Returns:
            MonitoredResult: 中断的结果
        """
        duration = time.time() - start_time

        # 报告完成阶段
        final_progress = self.reporter.report_progress(
            ExecutionPhase.COMPLETING.value,
            100,
            f"❌ 任务中断: {reason}"
        )

        return MonitoredResult(
            success=False,
            error=reason,
            duration=duration,
            progress_history=self.reporter.get_progress_history(),
            final_progress=final_progress
        )

    def get_progress_reporter(self) -> ProgressReporter:
        """获取进度报告器"""
        return self.reporter
