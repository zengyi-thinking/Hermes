"""
飞书通信通道实现

支持飞书开放平台 API：
- 接收消息：通过事件订阅或轮询
- 发送消息：通过发送消息 API
"""
import json
import time
import hmac
import hashlib
import base64
import asyncio
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import httpx

from .base import Message, IChannel
from ...utils.logger import get_logger


class FeishuMessageType(str, Enum):
    """飞书消息类型"""
    TEXT = "text"
    IMAGE = "image"
    CARD = "card"


@dataclass
class FeishuMessage:
    """飞书消息结构"""
    message_id: str = ""
    message_type: str = "text"
    content: str = ""
    sender_id: str = ""
    sender_id_type: str = "open_id"
    chat_id: str = ""
    root_id: str = ""
    parent_id: str = ""
    create_time: str = ""


class FeishuChannel(IChannel):
    """
    飞书通信通道

    实现 IChannel 接口，支持飞书即时消息功能

    使用方式：
    1. 创建飞书应用（开放平台）
    2. 配置事件订阅和权限
    3. 启用应用并发送消息
    """

    def __init__(self, config: "FeishuConfig"):
        """
        初始化飞书通道

        Args:
            config: 飞书配置
        """
        from config.settings import FeishuConfig

        self.config = config
        self.log = get_logger("feishu_channel")
        self._http_client: Optional[httpx.AsyncClient] = None
        self._tenant_access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._processed_message_ids: set = set()

        # API 地址
        self._base_url = "https://open.feishu.cn/open-apis"
        self._auth_url = f"{self._base_url}/auth/v3/tenant_access_token/internal"

    @property
    def channel_type(self) -> str:
        return "feishu"

    async def _get_tenant_access_token(self) -> Optional[str]:
        """获取 tenant_access_token"""
        # 检查 token 是否过期
        if self._tenant_access_token and time.time() < self._token_expires_at:
            return self._tenant_access_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._auth_url,
                    json={
                        "app_id": self.config.app_id,
                        "app_secret": self.config.app_secret.get_secret_value()
                    },
                    timeout=30.0
                )
                data = response.json()

                if data.get("code") == 0:
                    self._tenant_access_token = data["tenant_access_token"]
                    self._token_expires_at = time.time() + data.get("expire", 7200) - 60
                    return self._tenant_access_token
                else:
                    self.log.error(f"Failed to get token: {data}")
                    return None

        except Exception as e:
            self.log.error(f"Error getting tenant access token: {e}")
            return None

    async def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        token = await self._get_tenant_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

    def connect(self) -> bool:
        """建立连接（验证配置）"""
        if not self.config.app_id or not self.config.app_secret:
            self.log.error("Feishu app_id or app_secret not configured")
            return False

        # 验证 token
        try:
            loop = asyncio.new_event_loop()
            token = loop.run_until_complete(self._get_tenant_access_token())
            loop.close()

            if token:
                self.log.info("Feishu connection established")
                return True

        except Exception as e:
            self.log.error(f"Failed to connect to Feishu: {e}")

        return False

    def disconnect(self) -> None:
        """同步断开连接"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_disconnect())
        finally:
            loop.close()

    async def _async_disconnect(self) -> None:
        """异步断开连接"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._tenant_access_token = None
        self.log.info("Disconnected from Feishu")

    def receive(self, limit: int = 10) -> List[Message]:
        """
        接收消息（需要事件订阅或轮询）

        对于飞书，推荐使用事件订阅方式接收消息
        这里提供模拟轮询方式
        """
        try:
            loop = asyncio.new_event_loop()
            messages = loop.run_until_complete(self._receive_messages(limit))
            loop.close()
            return messages
        except Exception as e:
            self.log.error(f"Error receiving messages: {e}")
            return []

    async def _receive_messages(self, limit: int = 10) -> List[Message]:
        """异步接收消息"""
        # 获取所有群聊
        chats = await self._get_chats()

        messages = []
        for chat in chats[:5]:  # 限制群聊数量
            chat_messages = await self._get_chat_messages(chat["chat_id"], limit // len(chats) + 1)
            for msg in chat_messages:
                if msg.message_id in self._processed_message_ids:
                    continue

                message = self._parse_feishu_message(msg, chat)
                if message:
                    messages.append(message)
                    self._processed_message_ids.add(msg.message_id)

        return messages

    async def _get_chats(self) -> List[Dict]:
        """获取群聊列表"""
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._base_url}/im/v1/chats",
                    headers=headers,
                    timeout=30.0
                )
                data = response.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("items", [])
        except Exception as e:
            self.log.error(f"Error getting chats: {e}")
        return []

    async def _get_chat_messages(self, chat_id: str, limit: int = 10) -> List[FeishuMessage]:
        """获取群聊消息"""
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._base_url}/im/v1/messages",
                    headers=headers,
                    params={
                        "container_id_type": "chat",
                        "container_id": chat_id,
                        "page_size": limit
                    },
                    timeout=30.0
                )
                data = response.json()
                if data.get("code") == 0:
                    return [
                        FeishuMessage(**msg)
                        for msg in data.get("data", {}).get("items", [])
                    ]
        except Exception as e:
            self.log.error(f"Error getting messages: {e}")
        return []

    def _parse_feishu_message(self, feishu_msg: FeishuMessage, chat: Dict) -> Optional[Message]:
        """解析飞书消息为标准 Message"""
        try:
            # 解析内容
            content = json.loads(feishu_msg.content) if feishu_msg.content else {}
            text_content = content.get("text", "") if isinstance(content, dict) else str(content)

            return Message(
                id=feishu_msg.message_id,
                channel_type="feishu",
                sender=feishu_msg.sender_id,
                recipient=chat.get("chat_id", ""),
                subject=f"飞书消息",
                content=text_content,
                raw_content=feishu_msg.content,
                timestamp=datetime.fromisoformat(
                    feishu_msg.create_time.replace("+08:00", "")
                ) if feishu_msg.create_time else datetime.now(),
                metadata={
                    "chat_id": chat.get("chat_id"),
                    "chat_name": chat.get("name"),
                    "message_type": feishu_msg.message_type,
                    "root_id": feishu_msg.root_id,
                    "parent_id": feishu_msg.parent_id
                }
            )
        except Exception as e:
            self.log.error(f"Error parsing Feishu message: {e}")
            return None

    def send(self, message: Message) -> bool:
        """发送消息"""
        try:
            loop = asyncio.new_event_loop()
            success = loop.run_until_complete(self._send_message(message))
            loop.close()
            return success
        except Exception as e:
            self.log.error(f"Error sending message: {e}")
            return False

    async def _send_message(self, message: Message) -> bool:
        """异步发送消息"""
        try:
            headers = await self._get_headers()

            # 构建消息内容
            content = json.dumps({"text": message.content}, ensure_ascii=False)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}/im/v1/messages",
                    headers=headers,
                    params={
                        "receive_id_type": "open_id"
                    },
                    json={
                        "receive_id": message.recipient or self._get_open_id(message.sender),
                        "msg_type": "text",
                        "content": content
                    },
                    timeout=30.0
                )
                data = response.json()

                if data.get("code") == 0:
                    self.log.info(f"Sent message to {message.recipient}")
                    return True
                else:
                    self.log.error(f"Failed to send message: {data}")

        except Exception as e:
            self.log.error(f"Error sending message: {e}")

        return False

    def _get_open_id(self, user_id: str) -> str:
        """获取用户的 open_id（需要查询用户详情）"""
        return user_id

    def mark_processed(self, message_id: str) -> bool:
        """标记消息已处理"""
        self._processed_message_ids.add(message_id)
        return True

    # ============ Webhook 事件处理 ============

    def verify_webhook(self, verification_token: str, timestamp: str, signature: str) -> bool:
        """
        验证 Webhook 签名

        Args:
            verification_token: 应用的 verification_token
            timestamp: 时间戳
            signature: 签名

        Returns:
            验证是否成功
        """
        # 计算签名
        sign_string = f"{timestamp}{verification_token}"
        hmac_sha256 = hmac.new(
            sign_string.encode("utf-8"),
            b"",
            hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(hmac_sha256).decode("utf-8")

        return hmac.compare_digest(signature, expected_signature)

    def handle_webhook_event(self, event_data: dict) -> Optional[Message]:
        """
        处理 Webhook 事件

        Args:
            event_data: Webhook 事件数据

        Returns:
            解析后的 Message，或 None
        """
        try:
            # 验证事件类型
            event_type = event_data.get("type")
            if event_type != "im.message":
                return None

            event = event_data.get("event", {})
            message = event.get("message", {})

            return Message(
                id=message.get("message_id", ""),
                channel_type="feishu",
                sender=message.get("sender_id", {}).get("open_id", ""),
                recipient=message.get("receiver_id", ""),
                subject="飞书消息",
                content=message.get("content", ""),
                raw_content=event_data,
                timestamp=datetime.now(),
                metadata={
                    "event_type": event_type,
                    "chat_id": message.get("chat_id"),
                    "message_type": message.get("msg_type")
                }
            )

        except Exception as e:
            self.log.error(f"Error handling webhook event: {e}")
            return None


class FeishuConfig:
    """飞书配置类（兼容旧接口）"""

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        webhook_url: str = "",
        verification_token: str = "",
        enabled: bool = False
    ):
        from pydantic import SecretStr
        self.enabled = enabled
        self.app_id = app_id
        self.app_secret = SecretStr(app_secret) if app_secret else SecretStr("")
        self.webhook_url = webhook_url
        self.verification_token = SecretStr(verification_token) if verification_token else SecretStr("")
        self.event_type = "im.message"
        self.poll_interval = 60
