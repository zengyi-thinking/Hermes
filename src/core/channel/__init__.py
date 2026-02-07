"""
通信通道模块导出
"""
from .base import IChannel, Message
from .email import EmailChannel, EmailConfig
from .feishu import FeishuChannel, FeishuConfig, FeishuMessage, FeishuMessageType

__all__ = [
    "IChannel",
    "Message",
    "EmailChannel",
    "EmailConfig",
    "FeishuChannel",
    "FeishuConfig",
    "FeishuMessage",
    "FeishuMessageType"
]
