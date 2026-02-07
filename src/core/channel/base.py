"""
通信通道抽象基类（适配器模式）
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid


@dataclass
class Message:
    """消息模型"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    channel_type: str = "unknown"
    sender: str = ""
    recipient: str = ""
    subject: Optional[str] = None
    content: str = ""
    raw_content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_type": self.channel_type,
            "sender": self.sender,
            "recipient": self.recipient,
            "subject": self.subject,
            "content": self.content,
            "raw_content": self.raw_content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


class IChannel(ABC):
    """通信渠道抽象基类（适配器模式）"""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """获取渠道类型"""
        pass

    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    def receive(self, limit: int = 10) -> List[Message]:
        """接收消息"""
        pass

    @abstractmethod
    def send(self, message: Message) -> bool:
        """发送消息"""
        pass

    @abstractmethod
    def mark_processed(self, message_id: str) -> bool:
        """标记消息已处理"""
        pass
