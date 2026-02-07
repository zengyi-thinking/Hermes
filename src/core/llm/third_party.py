"""
第三方 LLM API 适配器
"""
import json
import re
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .base import BaseLLMClient, LLMResponse


class ThirdPartyLLMClient(BaseLLMClient):
    """
    第三方 LLM API 客户端

    支持：
    - Minimax API
    - 智谱 GLM API
    - OpenAI 兼容接口
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        timeout: int = 60
    ):
        super().__init__(api_key, base_url, model, temperature, max_tokens)
        self.timeout = timeout
        self.http_client = httpx.Client(timeout=timeout)

    def close(self):
        """关闭 HTTP 客户端"""
        self.http_client.close()

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None
    ) -> LLMResponse:
        """
        发送补全请求（同步方法）

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大输出 tokens

        Returns:
            LLMResponse: 响应对象
        """
        temp, tokens = self._merge_params(temperature, max_tokens)

        payload = self._build_payload(system_prompt, user_prompt, temp, tokens)

        response = self._send_request_sync(payload)

        return self._parse_response(response)

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int
    ) -> dict:
        """构建请求载荷（子类可重写）"""
        raise NotImplementedError

    def _send_request_sync(self, payload: dict) -> dict:
        """发送 HTTP 请求（同步方法）"""
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException))
        )
        def _do_request():
            headers = self._get_headers()
            response = self.http_client.post(
                self.base_url,
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            return response.json()

        return _do_request()

    def _get_headers(self) -> dict:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _parse_response(self, response: dict) -> LLMResponse:
        """解析响应（子类可重写）"""
        raise NotImplementedError


class MinimaxClient(ThirdPartyLLMClient):
    """Minimax API 客户端"""

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int
    ) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_output_tokens": max_tokens
        }

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _parse_response(self, response: dict) -> LLMResponse:
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        # 尝试清理 JSON 格式
        content = self._clean_json_content(content)

        return LLMResponse(
            content=content,
            model=self.model,
            tokens_used=response.get("usage", {}).get("total_tokens"),
            finish_reason=choice.get("finish_reason"),
            raw_response=response
        )

    def _clean_json_content(self, content: str) -> str:
        """清理 JSON 内容，提取纯文本"""
        # 移除 markdown 代码块标记
        content = re.sub(r'^```json\s*', '', content, flags=re.MULTILINE)
        content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
        content = content.strip()

        # 如果是 JSON 格式，尝试提取 content 字段
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "content" in data:
                return data["content"]
            if isinstance(data, str):
                return data
        except json.JSONDecodeError:
            pass

        return content


class GLMClient(ThirdPartyLLMClient):
    """智谱 GLM API 客户端"""

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int
    ) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

    def _parse_response(self, response: dict) -> LLMResponse:
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        # 清理内容
        content = self._clean_content(content)

        return LLMResponse(
            content=content,
            model=self.model,
            tokens_used=response.get("usage", {}).get("total_tokens"),
            finish_reason=choice.get("finish_reason"),
            raw_response=response
        )

    def _clean_content(self, content: str) -> str:
        """清理内容"""
        # 移除 markdown 代码块
        content = re.sub(r'^```\w*\s*', '', content, flags=re.MULTILINE)
        content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
        return content.strip()


class OpenAIClient(ThirdPartyLLMClient):
    """OpenAI 兼容 API 客户端"""

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int
    ) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

    def _parse_response(self, response: dict) -> LLMResponse:
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        return LLMResponse(
            content=content,
            model=self.model,
            tokens_used=response.get("usage", {}).get("total_tokens"),
            finish_reason=choice.get("finish_reason"),
            raw_response=response
        )


def create_llm_client(
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    timeout: int = 60
) -> BaseLLMClient:
    """
    创建 LLM 客户端工厂函数

    Args:
        provider: 提供商名称 (minimax | glm | openai)
        api_key: API 密钥
        base_url: API 基础 URL
        model: 模型名称
        temperature: 温度
        max_tokens: 最大 tokens
        timeout: 超时时间

    Returns:
        BaseLLMClient: LLM 客户端实例
    """
    providers = {
        "minimax": MinimaxClient,
        "glm": GLMClient,
        "openai": OpenAIClient
    }

    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(providers.keys())}")

    return providers[provider](
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )
