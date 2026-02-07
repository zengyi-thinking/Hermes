"""
IMAP 监听器
"""
import re
from typing import List, Optional
from dataclasses import dataclass

from imap_tools import MailBox, AND

from .base import BaseListener, Task
from ..core.channel.base import Message
from ..core.state.schemas import TaskStatus
from ..utils.logger import get_logger


@dataclass
class IMAPConfig:
    """IMAP 配置"""
    host: str = "imap.gmail.com"
    port: int = 993
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    use_ssl: bool = True
    search_subject: str = "[Task]"
    poll_interval: int = 60


class IMAPListener:
    """
    IMAP 邮箱监听器

    功能：
    - 定期轮询邮箱
    - 查找 [Task] 主题的邮件
    - 解析为 Task 对象
    """

    def __init__(self, config: IMAPConfig):
        self.config = config
        self.mailbox: Optional[MailBox] = None
        self._running = False
        self._processed_uids: set = set()
        self.log = get_logger("imap_listener")

    def connect(self) -> bool:
        """建立 IMAP 连接"""
        try:
            # 先断开任何现有连接
            if self.mailbox:
                try:
                    self.mailbox.logout()
                except Exception:
                    pass
                self.mailbox = None

            self.mailbox = MailBox(self.config.host)
            self.mailbox.login(self.config.username, self.config.password)
            self.log.info(f"Connected to IMAP: {self.config.host}")
            return True
        except Exception as e:
            self.log.error(f"Failed to connect IMAP: {e}")
            self.mailbox = None
            return False

    def disconnect(self) -> None:
        """断开 IMAP 连接"""
        if self.mailbox:
            self.mailbox.logout()
            self.mailbox = None
            self.log.info("Disconnected from IMAP")

    def poll(self) -> List[Task]:
        """
        轮询邮箱，获取新任务

        Returns:
            Task 列表
        """
        if not self.mailbox:
            if not self.connect():
                return []

        try:
            # 搜索未读邮件，主题包含 [Task]
            # seen=False 表示未读邮件
            search_query = AND(
                seen=False,
                subject=self.config.search_subject
            )

            tasks = []
            for msg in self.mailbox.fetch(search_query):
                # 跳过已处理的 UID
                if msg.uid in self._processed_uids:
                    continue

                # 解析任务
                task = self._parse_message(msg)
                if task:
                    tasks.append(task)
                    self._processed_uids.add(msg.uid)

            return tasks

        except Exception as e:
            self.log.error(f"Error polling IMAP: {e}")
            # 如果是 socket EOF 错误，断开连接以便下次重试
            error_str = str(e).lower()
            if "eof" in error_str or "socket" in error_str or "ssl" in error_str:
                self.log.warning("Detected connection error, will reconnect on next poll")
                self.disconnect()
            return []

    def _parse_message(self, msg) -> Optional[Task]:
        """解析邮件消息为 Task"""
        from datetime import datetime
        import uuid

        try:
            # 提取主题
            subject = msg.subject or ""

            # 移除 [Task] 前缀
            clean_subject = re.sub(
                rf'^\s*{re.escape(self.config.search_subject)}\s*',
                '',
                subject,
                flags=re.IGNORECASE
            ).strip()

            # 获取正文
            content = msg.text or msg.html or ""

            # 清理内容
            clean_content = self._clean_content(content)

            # 构建任务：优先使用正文内容，主题作为补充
            # 如果正文有内容，优先用正文；否则用主题
            if clean_content and len(clean_content) > 20:
                # 正文有实质性内容，使用主题+正文组合
                original_prompt = f"{clean_subject}\n\n{clean_content}".strip() if clean_subject else clean_content
            else:
                # 正文太短，使用主题
                original_prompt = clean_subject or clean_content[:200]

            task = Task(
                id=str(uuid.uuid4()),
                original_prompt=original_prompt,
                refined_prompt="",
                status=TaskStatus.PENDING,
                channel_message_id=str(msg.uid),
                sender=str(msg.from_),
                timestamp=msg.date or datetime.now(),
                metadata={
                    "raw_subject": subject,
                    "message_id": msg.headers.get("message-id", [""])[0],
                    "full_content": clean_content,
                    "uid": msg.uid
                }
            )

            return task

        except Exception as e:
            self.log.error(f"Error parsing message: {e}")
            return None

    def _clean_content(self, content: str) -> str:
        """清理邮件内容"""
        lines = content.split('\n')
        clean_lines = []

        skip_patterns = [
            r'^On\s+\w+.*wrote:$',
            r'^--$',
            r'^Best regards,$',
            r'^Thanks,$',
            r'^Sent from my iPhone',
            r'^Sent from my Android',
            r'^==+$',
            r'^--\s*$',
        ]

        for line in lines:
            should_skip = any(
                re.match(pattern, line.strip(), re.IGNORECASE)
                for pattern in skip_patterns
            )
            if not should_skip:
                clean_lines.append(line)

        return '\n'.join(clean_lines).strip()

    def acknowledge(self, task_id: str) -> bool:
        """确认任务已处理"""
        self._processed_uids.discard(task_id)
        return True

    def mark_seen(self, uid: str) -> bool:
        """标记邮件为已读"""
        if self.mailbox:
            try:
                # imap_tools API: flag(uid_list, flag_set, value)
                # value=True 表示设置标志（标记已读）
                self.mailbox.flag(uid, "\\Seen", True)
                return True
            except Exception as e:
                self.log.error(f"Failed to mark seen: {e}")
        return False
