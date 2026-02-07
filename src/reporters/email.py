"""
邮件报告器
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from ..core.channel.email import EmailConfig
from ..core.state.schemas import TaskInfo, ExecutionResult, RefinedResult
from ..utils.logger import get_logger


@dataclass
class ReportConfig:
    """报告配置"""
    sender_name: str = "Hermes"
    include_logs: bool = True
    max_log_length: int = 2000
    include_files: bool = True


class EmailReporter:
    """
    邮件报告器

    功能：
    - 发送任务完成报告
    - 发送澄清请求
    - 发送错误通知
    """

    def __init__(self, config: EmailConfig, report_config: ReportConfig = None):
        self.email_config = config
        self.report_config = report_config or ReportConfig()
        self.log = get_logger("email_reporter")

    def send_result(
        self,
        task: TaskInfo,
        refined_result: RefinedResult,
        exec_result: ExecutionResult,
        recipient: str = None
    ) -> bool:
        """
        发送任务完成结果

        Args:
            task: 任务信息
            refined_result: 优化结果
            exec_result: 执行结果
            recipient: 收件人

        Returns:
            是否发送成功
        """
        subject = self._build_subject(task, exec_result.success)
        body = self._build_result_body(task, refined_result, exec_result)

        message = self._create_message(
            subject=subject,
            body=body,
            to=recipient or task.sender
        )

        return self._send(message)

    def send_error(
        self,
        task: TaskInfo,
        error: str,
        recipient: str = None
    ) -> bool:
        """
        发送错误通知

        Args:
            task: 任务信息
            error: 错误信息
            recipient: 收件人

        Returns:
            是否发送成功
        """
        subject = f"[Hermes] 任务执行失败: {task.task_id[:8]}"
        body = self._build_error_body(task, error)

        message = self._create_message(
            subject=subject,
            body=body,
            to=recipient or task.sender
        )

        return self._send(message)

    def request_clarification(
        self,
        task: TaskInfo,
        questions: List[str],
        recipient: str = None
    ) -> bool:
        """
        发送澄清请求

        Args:
            task: 任务信息
            questions: 需要澄清的问题列表
            recipient: 收件人

        Returns:
            是否发送成功
        """
        subject = f"[Hermes] 需要澄清: {task.task_id[:8]}"
        body = self._build_clarification_body(task, questions)

        message = self._create_message(
            subject=subject,
            body=body,
            to=recipient or task.sender
        )

        return self._send(message)

    def _build_subject(self, task: TaskInfo, success: bool) -> str:
        """构建邮件主题"""
        status = "完成" if success else "失败"
        intent_type = task.refined_prompt[:30] if task.refined_prompt else "未知任务"
        return f"[Hermes] 任务{status}: {intent_type}..."

    def _build_result_body(
        self,
        task: TaskInfo,
        refined: RefinedResult,
        result: ExecutionResult
    ) -> str:
        """构建结果报告正文"""
        lines = [
            "=" * 50,
            "Hermes 任务执行报告",
            "=" * 50,
            "",
            f"任务 ID: {task.task_id}",
            f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"状态: {'成功 ✓' if result.success else '失败 ✗'}",
            "",
            "-" * 50,
            "原始指令:",
            "-" * 50,
            task.original_prompt,
            "",
            "-" * 50,
            "优化后指令:",
            "-" * 50,
            refined.refined_prompt,
            "",
            f"置信度: {refined.confidence:.0%}",
            f"意图类型: {refined.intent_type}",
            "",
        ]

        if result.success:
            lines.extend([
                "-" * 50,
                "执行结果:",
                "-" * 50,
                self._truncate_log(result.stdout),
            ])
        else:
            lines.extend([
                "-" * 50,
                "错误信息:",
                "-" * 50,
                result.stderr or result.error or "未知错误",
            ])

        if result.output_files:
            lines.extend([
                "",
                "-" * 50,
                "生成/修改的文件:",
                "-" * 50,
            ])
            for f in result.output_files:
                lines.append(f"  - {f}")

        lines.extend([
            "",
            "-" * 50,
            "建议执行步骤:",
            "-" * 50,
        ])
        for i, step in enumerate(refined.suggested_steps, 1):
            lines.append(f"{i}. {step}")

        lines.extend([
            "",
            "=" * 50,
            "由 Hermes 自动生成",
            "=" * 50,
        ])

        return "\n".join(lines)

    def _build_error_body(self, task: TaskInfo, error: str) -> str:
        """构建错误报告正文"""
        return f"""Hermes 任务执行错误报告

任务 ID: {task.task_id}
原始指令: {task.original_prompt}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

错误信息:
{error}

请检查系统状态或重新发送指令。
"""

    def _build_clarification_body(self, task: TaskInfo, questions: List[str]) -> str:
        """构建澄清请求正文"""
        lines = [
            "Hermes 任务澄清请求",
            "",
            f"任务 ID: {task.task_id}",
            f"原始指令: {task.original_prompt}",
            "",
            "为了更好地执行您的任务，请回复回答以下问题：",
            "",
        ]

        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q}")

        lines.extend([
            "",
            "请在回复中标记 [Task] 前缀，以便 Hermes 识别。",
        ])

        return "\n".join(lines)

    def _create_message(
        self,
        subject: str,
        body: str,
        to: str
    ) -> MIMEMultipart:
        """创建邮件消息"""
        msg = MIMEMultipart()
        msg["From"] = f"{self.report_config.sender_name} <{self.email_config.username}>"
        msg["To"] = to
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        return msg

    def _send(self, message: MIMEMultipart) -> bool:
        """发送邮件"""
        try:
            with smtplib.SMTP(
                self.email_config.smtp_host,
                self.email_config.smtp_port
            ) as server:
                server.starttls()
                server.login(
                    self.email_config.username,
                    self.email_config.password.get_secret_value()
                )
                server.send_message(message)

            self.log.info(f"Sent report to {message['To']}")
            return True

        except Exception as e:
            self.log.error(f"Failed to send report: {e}")
            return False

    def _truncate_log(self, log: str, max_length: int = None) -> str:
        """截断日志"""
        max_length = max_length or self.report_config.max_log_length
        if len(log) <= max_length:
            return log
        return log[:max_length] + f"\n... (已截断，完整日志 {len(log)} 字符)"
