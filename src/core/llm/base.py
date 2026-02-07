"""
LLM 抽象基类
"""
from abc import ABC, abstractmethod
from typing import Protocol, Optional
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    tokens_used: Optional[int] = None
    finish_reason: Optional[str] = None
    raw_response: dict = None


class LLMClientProtocol(Protocol):
    """LLM 客户端协议"""

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000
    ) -> LLMResponse:
        """
        发送补全请求

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大输出 tokens

        Returns:
            LLMResponse: 响应对象
        """
        ...


class BaseLLMClient(ABC):
    """LLM 客户端基类"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2000
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None
    ) -> LLMResponse:
        """发送补全请求"""
        pass

    def _merge_params(
        self,
        temperature: float = None,
        max_tokens: int = None
    ) -> tuple:
        """合并参数"""
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        return temp, tokens
