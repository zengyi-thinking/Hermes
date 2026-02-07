"""
短期记忆模块
管理对话上下文和会话内的临时记忆
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json


@dataclass
class ConversationMessage:
    """对话消息"""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationMessage":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {})
        )


@dataclass
class ConversationContext:
    """
    对话上下文
    管理单次会话内的对话历史和上下文信息
    """

    session_id: str
    user_id: str
    messages: List[ConversationMessage] = field(default_factory=list)
    system_prompt: str = ""
    context_vars: Dict[str, Any] = field(default_factory=dict)

    # 会话元数据
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    message_count: int = 0

    # TTL 配置
    ttl_minutes: int = 60  # 默认 60 分钟过期
    max_messages: int = 100  # 最大消息数

    def add_message(self, role: str, content: str, **metadata):
        """
        添加消息到对话历史

        Args:
            role: 消息角色
            content: 消息内容
            **metadata: 附加元数据
        """
        message = ConversationMessage(
            role=role,
            content=content,
            metadata=metadata
        )
        self.messages.append(message)
        self.message_count += 1
        self.last_accessed = datetime.now()

        # 超过最大消息数时，移除最旧的消息（保留系统提示）
        if len(self.messages) > self.max_messages + 1:  # +1 预留系统提示
            self.messages = [self.messages[0]] + self.messages[-(self.max_messages):]

    def get_messages(self, limit: int = None, include_system: bool = True) -> List[Dict[str, str]]:
        """
        获取消息历史

        Args:
            limit: 最大消息数
            include_system: 是否包含系统提示

        Returns:
            消息列表
        """
        messages = []

        # 添加系统提示（如果有）
        if include_system and self.system_prompt:
            messages.append({
                "role": "system",
                "content": self.system_prompt
            })

        # 添加对话消息
        msg_list = self.messages
        if limit:
            msg_list = msg_list[-limit:]

        for msg in msg_list:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })

        return messages

    def set_context(self, key: str, value: Any):
        """
        设置上下文变量

        Args:
            key: 变量名
            value: 变量值
        """
        self.context_vars[key] = value
        self.last_accessed = datetime.now()

    def get_context(self, key: str, default: Any = None) -> Any:
        """
        获取上下文变量

        Args:
            key: 变量名
            default: 默认值

        Returns:
            变量值
        """
        self.last_accessed = datetime.now()
        return self.context_vars.get(key, default)

    def clear_context(self):
        """清空上下文变量"""
        self.context_vars.clear()

    def clear_messages(self, keep_system: bool = True):
        """
        清空消息历史

        Args:
            keep_system: 是否保留系统提示
        """
        if keep_system and self.system_prompt:
            # 保留系统提示
            self.messages = [self.messages[0]] if self.messages and self.messages[0].role == "system" else []
        else:
            self.messages = []
        self.message_count = 0

    def is_expired(self) -> bool:
        """检查是否已过期"""
        expiry = self.created_at + timedelta(minutes=self.ttl_minutes)
        return datetime.now() > expiry

    def get_summary(self, max_length: int = 200) -> str:
        """
        获取对话摘要

        Args:
            max_length: 最大摘要长度

        Returns:
            对话摘要
        """
        if not self.messages:
            return ""

        # 汇总最后几条消息
        recent = self.messages[-5:]
        summary_parts = []

        for msg in recent:
            preview = msg.content[:50] + "..." if len(msg.content) > 50 else msg.content
            summary_parts.append(f"[{msg.role}]: {preview}")

        summary = " | ".join(summary_parts)
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."

        return summary

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "messages": [m.to_dict() for m in self.messages],
            "system_prompt": self.system_prompt,
            "context_vars": self.context_vars,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "message_count": self.message_count,
            "ttl_minutes": self.ttl_minutes,
            "max_messages": self.max_messages
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationContext":
        ctx = cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            system_prompt=data.get("system_prompt", ""),
            context_vars=data.get("context_vars", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            message_count=data.get("message_count", 0),
            ttl_minutes=data.get("ttl_minutes", 60),
            max_messages=data.get("max_messages", 100)
        )
        ctx.messages = [ConversationMessage.from_dict(m) for m in data.get("messages", [])]
        return ctx


class ShortTermMemory:
    """
    短期记忆管理器
    管理所有活跃会话的对话上下文
    """

    def __init__(self, maxContexts: int = 100):
        """
        初始化短期记忆管理器

        Args:
            maxContexts: 最大活跃上下文数
        """
        self._contexts: Dict[str, ConversationContext] = {}
        self._max_contexts = maxContexts
        self._cleanup_counter = 0

    def get_context(self, session_id: str) -> Optional[ConversationContext]:
        """
        获取会话上下文

        Args:
            session_id: 会话 ID

        Returns:
            ConversationContext 或 None
        """
        ctx = self._contexts.get(session_id)
        if ctx:
            ctx.last_accessed = datetime.now()
        return ctx

    def create_context(
        self,
        session_id: str,
        user_id: str,
        system_prompt: str = "",
        **kwargs
    ) -> ConversationContext:
        """
        创建新会话上下文

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            system_prompt: 系统提示
            **kwargs: 附加参数

        Returns:
            ConversationContext
        """
        ctx = ConversationContext(
            session_id=session_id,
            user_id=user_id,
            system_prompt=system_prompt,
            **kwargs
        )
        self._contexts[session_id] = ctx
        self._cleanup_if_needed()
        return ctx

    def delete_context(self, session_id: str) -> bool:
        """
        删除会话上下文

        Args:
            session_id: 会话 ID

        Returns:
            是否成功删除
        """
        if session_id in self._contexts:
            del self._contexts[session_id]
            return True
        return False

    def get_user_contexts(self, user_id: str) -> List[ConversationContext]:
        """
        获取用户的所有会话上下文

        Args:
            user_id: 用户 ID

        Returns:
            ConversationContext 列表
        """
        return [
            ctx for ctx in self._contexts.values()
            if ctx.user_id == user_id
        ]

    def cleanup_expired(self) -> int:
        """
        清理过期的会话上下文

        Returns:
            清理的上下文数量
        """
        expired_ids = []
        for session_id, ctx in self._contexts.items():
            if ctx.is_expired():
                expired_ids.append(session_id)

        for session_id in expired_ids:
            del self._contexts[session_id]

        return len(expired_ids)

    def _cleanup_if_needed(self):
        """必要时进行清理"""
        self._cleanup_counter += 1
        if self._cleanup_counter >= 100:
            self.cleanup_expired()
            # 如果还是太多，清理最久未访问的
            if len(self._contexts) > self._max_contexts:
                sorted_contexts = sorted(
                    self._contexts.items(),
                    key=lambda x: x[1].last_accessed
                )
                to_remove = len(self._contexts) - self._max_contexts
                for session_id, _ in sorted_contexts[:to_remove]:
                    del self._contexts[session_id]
            self._cleanup_counter = 0

    def get_stats(self) -> dict:
        """获取统计信息"""
        expired_count = sum(1 for ctx in self._contexts.values() if ctx.is_expired())
        return {
            "total_contexts": len(self._contexts),
            "expired_contexts": expired_count,
            "total_messages": sum(ctx.message_count for ctx in self._contexts.values())
        }

    def clear_all(self):
        """清空所有上下文"""
        self._contexts.clear()
