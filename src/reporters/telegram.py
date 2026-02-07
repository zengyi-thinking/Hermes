#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Telegram Reporter - Hermes 统一报告接口

支持通过 Telegram 发送任务结果
"""
import httpx
from typing import List, Optional
from datetime import datetime
from ...core.channel.base import Message


class TelegramReporter:
    """Telegram 报告器"""

    def __init__(self, token: str):
        self.token = token

    def send_result(self, chat_id: str, content: str) -> bool:
        """发送任务完成结果"""
        try:
            resp = httpx.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": content,
                    "parse_mode": "Markdown"
                },
                timeout=30
            )
            return resp.json().get("ok", False)
        except Exception as e:
            print(f"Telegram 发送失败: {e}")
            return False

    def send_error(self, chat_id: str, error: str) -> bool:
        """发送错误通知"""
        return self.send_result(chat_id, f"❌ 任务失败\n\n{error}")

    def request_clarification(self, chat_id: str, questions: List[str]) -> bool:
        """发送澄清请求"""
        content = "请澄清以下问题：\n\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
        return self.send_result(chat_id, content)


def create_telegram_reporter(token: str) -> Optional[TelegramReporter]:
    """创建 Telegram Reporter"""
    if not token:
        return None
    return TelegramReporter(token)
