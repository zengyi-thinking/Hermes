"""
会话管理模块
提供会话的创建、恢复、上下文传递功能
"""

from .session import Session, Message, MessageRole
from .manager import SessionManager
from .context import Context, ContextBuilder

__all__ = [
    'Session',
    'Message',
    'MessageRole',
    'SessionManager',
    'Context',
    'ContextBuilder',
]
