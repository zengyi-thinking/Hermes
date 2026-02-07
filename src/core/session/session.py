"""
会话数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """消息模型"""
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "message_id": self.message_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """从字典创建"""
        return cls(
            role=MessageRole(data["role"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            metadata=data.get("metadata", {}),
            message_id=data.get("message_id", str(uuid.uuid4()))
        )


class SessionStatus(str, Enum):
    """会话状态"""
    ACTIVE = "active"
    IDLE = "idle"
    ARCHIVED = "archived"


@dataclass
class Session:
    """
    会话模型
    包含会话的基本信息和消息历史
    """

    session_id: str
    user_id: str
    platform: str  # telegram, email, etc.
    title: Optional[str] = None
    status: SessionStatus = SessionStatus.ACTIVE

    # 消息历史
    messages: List[Message] = field(default_factory=list)

    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 上下文变量（用于跨消息的状态保持）
    context_vars: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: MessageRole, content: str, **metadata) -> Message:
        """
        添加消息到历史

        Args:
            role: 消息角色
            content: 消息内容
            **metadata: 附加元数据

        Returns:
            创建的消息对象
        """
        message = Message(
            role=role,
            content=content,
            metadata=metadata
        )
        self.messages.append(message)
        self.updated_at = datetime.now()
        return message

    def add_user_message(self, content: str, **metadata) -> Message:
        """添加用户消息"""
        return self.add_message(MessageRole.USER, content, **metadata)

    def add_assistant_message(self, content: str, **metadata) -> Message:
        """添加助手消息"""
        return self.add_message(MessageRole.ASSISTANT, content, **metadata)

    def add_system_message(self, content: str, **metadata) -> Message:
        """添加系统消息"""
        return self.add_message(MessageRole.SYSTEM, content, **metadata)

    def get_message_history(self, limit: Optional[int] = None) -> List[Message]:
        """
        获取消息历史

        Args:
            limit: 返回最近 N 条消息，None 表示全部

        Returns:
            消息列表
        """
        if limit is None:
            return self.messages.copy()
        return self.messages[-limit:]

    def get_conversation_text(self, limit: Optional[int] = None) -> str:
        """
        获取会话文本（用于 LLM 上下文）

        Args:
            limit: 消息数量限制

        Returns:
            格式化的对话文本
        """
        messages = self.get_message_history(limit)
        lines = []
        for msg in messages:
            role_name = msg.role.value.upper()
            lines.append(f"[{role_name}]: {msg.content}")
        return "\n".join(lines)

    def set_context(self, key: str, value: Any) -> None:
        """
        设置上下文变量

        Args:
            key: 变量名
            value: 变量值
        """
        self.context_vars[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """
        获取上下文变量

        Args:
            key: 变量名
            default: 默认值

        Returns:
            变量值或默认值
        """
        return self.context_vars.get(key, default)

    def clear_context(self, key: Optional[str] = None) -> None:
        """
        清除上下文

        Args:
            key: 指定变量名，None 表示清除全部
        """
        if key is None:
            self.context_vars.clear()
        elif key in self.context_vars:
            del self.context_vars[key]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "platform": self.platform,
            "title": self.title,
            "status": self.status.value,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "context_vars": self.context_vars
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        """从字典创建会话"""
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            platform=data["platform"],
            title=data.get("title"),
            status=SessionStatus(data.get("status", "active")),
            messages=messages,
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            metadata=data.get("metadata", {}),
            context_vars=data.get("context_vars", {})
        )

    @property
    def message_count(self) -> int:
        """消息数量"""
        return len(self.messages)

    @property
    def last_message(self) -> Optional[Message]:
        """最后一条消息"""
        return self.messages[-1] if self.messages else None

    def archive(self) -> None:
        """归档会话"""
        self.status = SessionStatus.ARCHIVED

    def activate(self) -> None:
        """激活会话"""
        self.status = SessionStatus.ACTIVE
