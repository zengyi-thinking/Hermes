"""
Telegram 通信适配器 - 轮询模式

特点：
- 不需要公网服务器
- 直接在本地运行
- 实时接收消息
"""

import asyncio
import os
import json
import logging
from typing import List, Optional
from datetime import datetime

import httpx

from .base import Message, IChannel

logger = logging.getLogger(__name__)


class TelegramChannel(IChannel):
    """Telegram 机器人适配器（轮询模式）"""

    def __init__(
        self,
        token: str = None,
        poll_interval: int = 1,
        allowed_users: List[str] = None
    ):
        """
        初始化 Telegram 适配器

        Args:
            token: Bot Token
            poll_interval: 轮询间隔（秒）
            allowed_users: 允许使用机器人的用户 ID 列表（留空则允许所有人）
        """
        self.token = token or os.getenv("TELEGRAM_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_TOKEN 环境变量未设置")

        self.poll_interval = poll_interval
        self.allowed_users = set(allowed_users or [])
        self.offset = 0  # 消息偏移量
        self._running = False
        self.bot_info = None

    @property
    def channel_type(self) -> str:
        return "telegram"

    def connect(self) -> bool:
        """验证 Token 并获取机器人信息"""
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"https://api.telegram.org/bot{self.token}/getMe")
                data = resp.json()

                if data.get("ok"):
                    self.bot_info = data["result"]
                    logger.info(f"🤖 Telegram 已连接: @{self.bot_info['username']}")
                    return True
                else:
                    logger.error(f"❌ Token 验证失败: {data}")
                    return False
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            return False

    def disconnect(self) -> None:
        """断开连接"""
        self._running = False
        logger.info("👋 Telegram 已断开")

    def receive(self, limit: int = 10) -> List[Message]:
        """轮询获取新消息（同步版本）"""
        messages = []
        try:
            with httpx.Client(timeout=35) as client:
                resp = client.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params={
                        "offset": self.offset,
                        "timeout": 30,  # 长轮询
                        "limit": limit
                    }
                )
                data = resp.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        msg = self._parse_update(update)
                        if msg:
                            messages.append(msg)
                            # 更新 offset
                            self.offset = update["update_id"] + 1
        except Exception as e:
            logger.error(f"❌ 获取消息失败: {e}")
        return messages

    async def receive_async(self, limit: int = 10) -> List[Message]:
        """异步轮询获取新消息"""
        messages = []
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params={
                        "offset": self.offset,
                        "timeout": 30,
                        "limit": limit
                    }
                )
                data = resp.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        msg = self._parse_update(update)
                        if msg:
                            messages.append(msg)
                            self.offset = update["update_id"] + 1
        except Exception as e:
            logger.error(f"❌ 获取消息失败: {e}")
        return messages

    def _parse_update(self, update: dict) -> Optional[Message]:
        """解析 Telegram 更新"""
        if "message" not in update:
            return None

        msg = update["message"]
        chat = msg["chat"]
        text = msg.get("text", "")

        # 忽略命令（如 /start /help）
        if text.startswith("/"):
            return None

        # 检查用户白名单
        user_id = str(msg["from"]["id"])
        if self.allowed_users and user_id not in self.allowed_users:
            logger.info(f"🚫 忽略未授权用户: {user_id}")
            return None

        return Message(
            id=str(msg["message_id"]),
            channel_type="telegram",
            sender=user_id,
            recipient=self.bot_info["id"] if self.bot_info else "",
            content=text,
            raw_content=json.dumps(msg, ensure_ascii=False),
            timestamp=datetime.fromtimestamp(msg["date"]),
            metadata={
                "chat_id": chat["id"],
                "chat_type": chat.get("type", "private"),
                "username": msg["from"].get("username", ""),
                "first_name": msg["from"].get("first_name", "")
            }
        )

    def send(self, message: Message) -> bool:
        """发送消息"""
        try:
            chat_id = message.recipient or message.sender
            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": message.content,
                        "parse_mode": "Markdown"
                    }
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"❌ 发送失败: {e}")
            return False

    async def send_async(self, message: Message) -> bool:
        """异步发送消息"""
        try:
            chat_id = message.recipient or message.sender
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": message.content,
                        "parse_mode": "Markdown"
                    }
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"❌ 发送失败: {e}")
            return False

    def send_markdown(
        self,
        chat_id: str,
        text: str,
        buttons: List[dict] = None
    ) -> bool:
        """发送 Markdown 消息（自动转义 MarkdownV2 特殊字符）"""
        try:
            # MarkdownV2 需要转义的字符
            escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            escaped_text = text
            for char in escape_chars:
                escaped_text = escaped_text.replace(char, '\\' + char)

            payload = {
                "chat_id": chat_id,
                "text": escaped_text,
                "parse_mode": "MarkdownV2"
            }

            if buttons:
                keyboard = [[{
                    "text": btn["text"],
                    "callback_data": btn.get("data", "")
                }] for btn in buttons]
                payload["reply_markup"] = {"inline_keyboard": keyboard}

            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json=payload
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"❌ 发送失败: {e}")
            return False

    def mark_processed(self, message_id: str) -> bool:
        """标记消息已处理（通过更新 offset 实现）"""
        try:
            # 设置 offset 到该消息之后
            msg_id = int(message_id)
            if msg_id >= self.offset:
                self.offset = msg_id + 1
            return True
        except Exception:
            return False

    def get_chat(self, chat_id: str) -> dict:
        """获取聊天信息"""
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"https://api.telegram.org/bot{self.token}/getChat",
                    params={"chat_id": chat_id}
                )
                return resp.json().get("result", {})
        except Exception as e:
            logger.error(f"❌ 获取聊天信息失败: {e}")
            return {}


# ============ 便捷函数 ============

def create_channel(token: str = None) -> TelegramChannel:
    """创建 Telegram 通道"""
    return TelegramChannel(token=token)


async def run_polling(
    token: str,
    on_message,
    poll_interval: int = 1
):
    """
    便捷轮询函数

    Args:
        token: Bot Token
        on_message: 收到消息时的回调函数 (message: Message) -> None
        poll_interval: 轮询间隔
    """
    channel = TelegramChannel(token=token, poll_interval=poll_interval)

    if not channel.connect():
        raise Exception("连接 Telegram 失败")

    print(f"✅ 开始轮询... (按 Ctrl+C 退出)")
    print(f"📱 在 Telegram 中搜索 @{channel.bot_info['username']} 发送消息\n")

    try:
        while True:
            messages = await channel.receive_async()
            for msg in messages:
                await on_message(channel, msg)
            await asyncio.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\n👋 停止轮询")
    finally:
        channel.disconnect()
