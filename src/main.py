#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Hermes 主应用入口
支持邮箱和Telegram，通过原渠道返回结果
"""
import signal
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_settings, EmailConfig
from src.utils.logger import get_logger
from src.core.state.manager import StateManager
from src.core.state.schemas import TaskStatus, TaskInfo
from src.core.channel.email import EmailChannel
from src.core.channel.telegram import TelegramChannel, Message
from src.core.agent.refiner import RefinerAgent
from src.core.agent.executor import ClaudeExecutor, ExecutorConfig
from src.core.llm.third_party import create_llm_client
from src.listeners.imap import IMAPListener, IMAPConfig


class HermesApplication:
    def __init__(self):
        self.settings = get_settings()
        self.log = get_logger("hermes")
        self.state_manager = StateManager(self.settings.state_file)
        self.llm_client = create_llm_client(
            provider=self.settings.llm.provider,
            api_key=self.settings.llm.api_key.get_secret_value(),
            base_url=self.settings.llm.base_url,
            model=self.settings.llm.model,
            temperature=self.settings.llm.temperature,
            max_tokens=self.settings.llm.max_tokens
        )
        self._init_components()
        self._running = False
        self._shutdown_requested = False

    def _init_components(self):
        email_config = EmailConfig(
            imap_host=self.settings.email.imap_host,
            imap_port=self.settings.email.imap_port,
            smtp_host=self.settings.email.smtp_host,
            smtp_port=self.settings.email.smtp_port,
            username=self.settings.email.username,
            password=self.settings.email.password,
            search_subject=self.settings.email.search_subject
        )

        imap_config = IMAPConfig(
            host=self.settings.email.imap_host,
            port=self.settings.email.imap_port,
            username=self.settings.email.username,
            password=self.settings.email.password.get_secret_value(),
            search_subject=self.settings.email.search_subject,
            poll_interval=self.settings.task.poll_interval
        )
        self.email_listener = IMAPListener(imap_config)
        self.email_channel = EmailChannel(email_config)

        # Telegram
        self.telegram_channel = None
        telegram_token = os.getenv("TELEGRAM_TOKEN")
        if telegram_token:
            try:
                self.telegram_channel = TelegramChannel(
                    token=telegram_token,
                    poll_interval=self.settings.task.poll_interval
                )
                if self.telegram_channel.connect():
                    self.log.info("Telegram: @{}".format(self.telegram_channel.bot_info['username']))
                else:
                    self.telegram_channel = None
            except Exception as e:
                self.log.warning("Telegram 失败: {}".format(e))
                self.telegram_channel = None

        self.refiner = RefinerAgent(self.llm_client)
        self.executor = ClaudeExecutor(ExecutorConfig(
            cli_path=self.settings.claude.cli_path,
            work_dir=self.settings.claude.work_dir,
            timeout=self.settings.claude.timeout,
            git_bash_path=os.getenv("CLAUDE_CODE_GIT_BASH_PATH", "")
        ))

    def run(self):
        self._running = True
        self.log.info("=" * 50)
        self.log.info("Hermes 启动")
        self.log.info("=" * 50)

        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        self.state_manager.update_status("running")

        self.log.info("邮箱: {}".format(self.settings.email.username))
        if self.telegram_channel:
            self.log.info("Telegram: @{}".format(self.telegram_channel.bot_info['username']))
        else:
            self.log.info("Telegram: 未配置")
        self.log.info("超时: {}秒".format(self.settings.claude.timeout))
        self.log.info("=" * 50)

        try:
            while not self._shutdown_requested:
                try:
                    self._poll_all_channels()
                    self._sleep()
                except Exception as e:
                    self.log.error("错误: {}".format(e))
                    self._sleep(5)
        finally:
            self._cleanup()

    def _poll_all_channels(self):
        # 邮箱
        try:
            for task in self.email_listener.poll():
                self._handle_email_task(task)
        except Exception as e:
            self.log.error("邮箱错误: {}".format(e))

        # Telegram
        if self.telegram_channel:
            try:
                for msg in self.telegram_channel.receive():
                    self._handle_telegram_message(msg)
            except Exception as e:
                self.log.error("Telegram 错误: {}".format(e))

    def _handle_telegram_message(self, message: Message):
        """处理 Telegram 消息"""
        self.log.info("收到 TG: {}...".format(message.content[:50]))

        # 记录任务来源是 Telegram
        task_info = TaskInfo(
            task_id="tg_{}".format(datetime.now().strftime('%Y%m%d_%H%M%S')),
            original_prompt=message.content,
            sender=message.metadata.get("username", message.sender),  # Telegram username
            created_at=message.timestamp
        )
        # 重要：保存原始 message 用于回复
        task_info.metadata = {"tg_message": message, "channel": "telegram"}
        self.state_manager.add_task(task_info)
        self._process_task(task_info)

    def _handle_email_task(self, task):
        """处理邮箱任务"""
        self.log.info("收到邮件: {}...".format(task.id[:20]))

        task_info = TaskInfo(
            task_id=task.id,
            original_prompt=task.original_prompt,
            sender=task.sender,  # 邮箱地址
            created_at=task.timestamp
        )
        # 保存邮件任务信息
        task_info.metadata = {"email_task": task, "channel": "email"}
        self.state_manager.add_task(task_info)

        try:
            self.email_listener.mark_seen(task.metadata.get("uid", task.id))
        except:
            pass
        self._process_task(task_info)

    def _reply_to_user(self, task_info: TaskInfo, content: str):
        """通过原渠道回复用户"""
        channel = task_info.metadata.get("channel", "email")

        if channel == "telegram" and self.telegram_channel:
            # Telegram 渠道 - 使用 chat_id 发送
            try:
                tg_msg = task_info.metadata.get("tg_message")
                if tg_msg:
                    # 使用 metadata 中的 chat_id（数字）
                    chat_id = tg_msg.metadata.get("chat_id", tg_msg.sender)
                    self.telegram_channel.send_markdown(chat_id, content)
                    self.log.info("TG 回复已发送到 chat_id: {}".format(chat_id))
                else:
                    self.log.error("没有保存 tg_message")
            except Exception as e:
                self.log.error("TG 回复失败: {}".format(e))
        else:
            # 邮箱渠道 - 暂不处理
            self.log.info("邮件回复: {}...".format(content[:50]))

    def _process_task(self, task_info: TaskInfo):
        self.log.info("处理: {}".format(task_info.task_id))

        try:
            # Refiner
            state = self.state_manager.get_state()
            refined = self.refiner.refine(task_info.original_prompt, state)
            self.log.info("优化: {}...".format(refined.refined_prompt[:50]))
            self.log.info("置信度: {:.0%}".format(refined.confidence))

            self.state_manager.update_task_status(
                task_info.task_id,
                TaskStatus.PROCESSING.value,
                refined_prompt=refined.refined_prompt
            )

            # 需要澄清
            if refined.clarifications and refined.confidence < 0.6:
                self.log.info("需要澄清: {}".format(refined.clarifications))
                # 通过原渠道请求澄清
                self._reply_to_user(task_info, "请澄清以下问题：\n\n" +
                                  "\n".join("{}. {}".format(i+1, q)
                                          for i, q in enumerate(refined.clarifications)))
                self.state_manager.update_task_status(task_info.task_id, TaskStatus.COMPLETED.value)
                return

            # 执行
            exec_result = self.executor.execute(
                refined.refined_prompt,
                self.settings.claude.work_dir,
                self.settings.claude.timeout
            )

            # 记录详细执行结果
            stdout_len = len(exec_result.stdout) if exec_result.stdout else 0
            stderr_len = len(exec_result.stderr) if exec_result.stderr else 0
            self.log.info("执行结果: success={}, exit_code={}, stdout_len={}, stderr_len={}".format(
                exec_result.success, getattr(exec_result, 'exit_code', 'N/A'), stdout_len, stderr_len))

            # 直接打印内容摘要
            if exec_result.stdout:
                preview = exec_result.stdout[:100].replace('\n', ' ')
                self.log.info("stdout预览: {}...".format(preview))
            if exec_result.stderr:
                preview = exec_result.stderr[:100].replace('\n', ' ')
                self.log.info("stderr预览: {}...".format(preview))

            # 超时智能处理
            if not exec_result.success and exec_result.error:
                if "timed out" in exec_result.error.lower():
                    self.log.info("检测到超时，检查是否有输出...")
                    if exec_result.stdout and len(exec_result.stdout.strip()) > 0:
                        exec_result.success = True
                        exec_result.error = ""
                        self.log.info("实际已完成，忽略超时")

            elapsed = exec_result.duration if hasattr(exec_result, 'duration') else 0
            self.log.info("完成: {}, {}秒".format(exec_result.success, elapsed))

            # 回复用户（通过原渠道）
            if exec_result.success:
                output = exec_result.stdout.strip() if exec_result.stdout else "任务完成"

                # 检查文件是否创建
                output_files = exec_result.output_files or []
                if output_files:
                    file_info = "\n已创建文件：\n" + "\n".join("- " + f for f in output_files)
                else:
                    file_info = ""

                # Telegram 消息长度限制
                if len(output) + len(file_info) > 3000:
                    output = output[:2500] + "\n\n...（详细内容见附件）"
                self._reply_to_user(task_info, "任务完成\n\n{}{}".format(output, file_info))
            else:
                error_msg = exec_result.stderr or exec_result.error or "执行失败"
                is_timeout = "timed out" in error_msg.lower() and exec_result.stdout
                if is_timeout:
                    output = exec_result.stdout.strip() if exec_result.stdout else ""
                    if output:
                        self._reply_to_user(task_info, "部分完成（超时）\n\n{}".format(output[:3000]))
                    else:
                        self._reply_to_user(task_info, "任务超时")
                else:
                    self._reply_to_user(task_info, "任务失败\n\n{}".format(error_msg[:500]))

            # 更新状态
            self.state_manager.update_task_status(
                task_info.task_id,
                TaskStatus.COMPLETED.value if exec_result.success else TaskStatus.FAILED.value
            )
            for f in (exec_result.output_files or []):
                self.state_manager.add_file_change(f, "modified", "Claude")

        except Exception as e:
            self.log.error("处理失败: {}".format(e))
            self._reply_to_user(task_info, "处理任务失败: {}".format(str(e)[:500]))
            self.state_manager.record_error(str(e))
            self.state_manager.update_task_status(task_info.task_id, TaskStatus.FAILED.value)

    def _sleep(self, seconds=None):
        seconds = seconds or self.settings.task.poll_interval
        for _ in range(seconds * 10):
            if self._shutdown_requested:
                break
            import time
            time.sleep(0.1)

    def _handle_shutdown(self, signum, frame):
        self.log.info("停止信号")
        self._shutdown_requested = True

    def _cleanup(self):
        self.log.info("清理...")
        try:
            self.email_listener.disconnect()
            self.email_channel.disconnect()
            if self.telegram_channel:
                self.telegram_channel.disconnect()
        except:
            pass
        self.state_manager.update_status("idle")
        self._running = False
        self.log.info("已停止")

    def shutdown(self):
        self._shutdown_requested = True


def main():
    app = HermesApplication()
    app.run()


if __name__ == "__main__":
    main()
