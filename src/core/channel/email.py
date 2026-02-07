"""
Email 通道实现
"""
import re
import sys
from typing import List, Optional
from dataclasses import dataclass

from imap_tools import MailBox, AND

from .base import Message, IChannel
from ...utils.logger import get_logger


# 解决 Windows 编码问题
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


@dataclass
class EmailConfig:
    """邮箱配置"""
    imap_host: str = "imap.qq.com"
    imap_port: int = 993
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    use_ssl: bool = True
    use_tls: bool = True
    search_subject: str = "[Task]"
    folder: str = "INBOX"


class EmailChannel(IChannel):
    """
    Email 通信通道

    实现 IChannel 接口，支持 IMAP 接收和 SMTP 发送
    """

    def __init__(self, config: EmailConfig):
        """
        初始化 Email 通道

        Args:
            config: 邮箱配置
        """
        self.config = config
        self.mailbox: Optional[MailBox] = None
        self._processed_ids: set = set()
        self.log = get_logger("email_channel")

    @property
    def channel_type(self) -> str:
        return "email"

    def connect(self) -> bool:
        """建立 IMAP 连接"""
        try:
            # 根据 SSL 配置选择连接方式
            if self.config.use_ssl:
                self.mailbox = MailBox(self.config.imap_host, port=self.config.imap_port)
            else:
                self.mailbox = MailBox(self.config.imap_host, port=self.config.imap_port)

            self.mailbox.login(self.config.username, self.config.password)
            self.log.info(f"Connected to IMAP: {self.config.imap_host}:{self.config.imap_port}")
            return True
        except Exception as e:
            self.log.error(f"Failed to connect IMAP: {e}")
            return False

    def disconnect(self) -> None:
        """断开 IMAP 连接"""
        if self.mailbox:
            try:
                self.mailbox.logout()
            except:
                pass
            self.mailbox = None
            self.log.info("Disconnected from IMAP")

    def receive(self, limit: int = 10) -> List[Message]:
        """
        接收消息

        Args:
            limit: 最大接收数量

        Returns:
            Message 列表
        """
        if not self.mailbox:
            if not self.connect():
                return []

        try:
            # 搜索未读邮件，主题包含 [Task]
            search_query = AND(
                unseen=True,
                subject=self.config.search_subject
            )

            messages = []
            for msg in self.mailbox.fetch(search_query, limit=limit):
                # 跳过已处理的
                if msg.uid in self._processed_ids:
                    continue

                message = self._parse_message(msg)
                if message:
                    messages.append(message)
                    self._processed_ids.add(msg.uid)

            return messages

        except Exception as e:
            self.log.error(f"Error receiving messages: {e}")
            return []

    def _parse_message(self, msg) -> Optional[Message]:
        """解析邮件消息"""
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

            # 构建消息
            message = Message(
                id=str(msg.uid),
                channel_type="email",
                sender=str(msg.from_),
                recipient=self.config.username,
                subject=clean_subject or None,
                content=clean_content,
                raw_content=content,
                timestamp=msg.date,
                metadata={
                    "raw_subject": subject,
                    "message_id": msg.headers.get("message-id", [""])[0],
                    "uid": msg.uid
                }
            )

            return message

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

    def send(self, message: Message) -> bool:
        """
        发送消息

        Args:
            message: 要发送的消息

        Returns:
            是否发送成功
        """
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        try:
            # 构建邮件
            msg = MIMEMultipart()
            msg["From"] = self.config.username
            msg["To"] = message.recipient or message.sender
            msg["Subject"] = message.subject or f"[Hermes] {message.channel_type} message"

            # 添加正文
            msg.attach(MIMEText(message.content, "plain", "utf-8"))

            # 发送邮件
            server = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port)
            try:
                if self.config.use_tls:
                    server.starttls()
                server.login(self.config.username, self.config.password)
                server.send_message(msg)
            finally:
                server.quit()

            self.log.info(f"Sent email to {msg['To']}")
            return True

        except Exception as e:
            self.log.error(f"Failed to send email: {e}")
            return False

    def mark_processed(self, message_id: str) -> bool:
        """标记消息已处理"""
        try:
            self._processed_ids.add(message_id)

            # 标记为已读
            if self.mailbox:
                self.mailbox.flag(
                    [message_id],
                    ["\\Seen"],
                    silent=True
                )

            return True
        except Exception as e:
            self.log.error(f"Failed to mark processed: {e}")
            return False

    def mark_seen(self, message_id: str) -> bool:
        """标记消息为已读"""
        if self.mailbox:
            try:
                self.mailbox.flag([message_id], ["\\Seen"], silent=True)
                return True
            except Exception as e:
                self.log.error(f"Failed to mark seen: {e}")
        return False
