"""
向量化服务模块
提供文本向量化功能，支持多种嵌入模型
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
import numpy as np


@dataclass
class EmbeddingResult:
    """向量化结果"""
    vector: List[float]
    model: str
    dimensions: int
    token_count: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "vector": self.vector,
            "model": self.model,
            "dimensions": self.dimensions,
            "token_count": self.token_count
        }

    @property
    def numpy(self) -> np.ndarray:
        """获取 numpy 数组"""
        return np.array(self.vector)


class EmbeddingService(ABC):
    """向量化服务抽象基类"""

    @abstractmethod
    def embed(self, text: str) -> EmbeddingResult:
        """
        将单个文本向量化

        Args:
            text: 输入文本

        Returns:
            EmbeddingResult: 向量化结果
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        批量向量化

        Args:
            texts: 文本列表

        Returns:
            EmbeddingResult 列表
        """
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """获取向量维度"""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """获取模型名称"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查服务是否可用"""
        pass


class DefaultEmbeddingService(EmbeddingService):
    """
    默认向量化服务
    使用简单的词嵌入或 TF-IDF 风格向量
    对于没有 API 的场景提供降级方案
    """

    def __init__(self, dimensions: int = 384):
        """
        初始化默认向量化服务

        Args:
            dimensions: 向量维度
        """
        self._dimensions = dimensions
        self._model_name = "simple-hash-embedding"
        self._vocab: dict = {}
        self._is_available = True

    def embed(self, text: str) -> EmbeddingResult:
        """
        将文本转换为固定维度的向量
        使用基于字符 n-gram 的哈希方法

        Args:
            text: 输入文本

        Returns:
            EmbeddingResult
        """
        # 简单哈希嵌入：将文本转换为固定维度的向量
        vector = self._text_to_vector(text)
        return EmbeddingResult(
            vector=vector,
            model=self._model_name,
            dimensions=self._dimensions,
            token_count=len(text)
        )

    def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        批量向量化

        Args:
            texts: 文本列表

        Returns:
            EmbeddingResult 列表
        """
        return [self.embed(text) for text in texts]

    def _text_to_vector(self, text: str) -> List[float]:
        """
        将文本转换为向量

        Args:
            text: 输入文本

        Returns:
            向量列表
        """
        # 使用字符 n-gram 哈希生成固定维度向量
        vector = [0.0] * self._dimensions
        text_lower = text.lower()

        # 使用多个 n-gram 级别
        ngrams = []
        for n in [1, 2, 3]:
            for i in range(len(text_lower) - n + 1):
                ngram = text_lower[i:i+n]
                ngrams.append(ngram)

        # 使用哈希映射到向量位置
        for ngram in ngrams:
            hash_val = hash(ngram)
            idx = abs(hash_val) % self._dimensions
            vector[idx] += 1.0

        # L2 归一化
        norm = sum(v*v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector

    def get_dimension(self) -> int:
        """获取向量维度"""
        return self._dimensions

    def get_model_name(self) -> str:
        """获取模型名称"""
        return self._model_name

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._is_available


class OpenAIEmbeddingService(EmbeddingService):
    """
    OpenAI 嵌入服务
    使用 OpenAI 的 text-embedding 模型
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int = None,
        base_url: str = None
    ):
        """
        初始化 OpenAI 嵌入服务

        Args:
            api_key: OpenAI API 密钥
            model: 模型名称
            dimensions: 向量维度（可选，会被模型实际维度覆盖）
            base_url: 自定义 API 地址
        """
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._dimensions = dimensions
        self._model_name = f"openai/{model}"
        self._is_available = False
        self._client = None

        self._init_client()

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        try:
            from openai import OpenAI
            client_kwargs = {
                "api_key": self._api_key,
            }
            if self._base_url:
                client_kwargs["base_url"] = self._base_url

            self._client = OpenAI(**client_kwargs)
            self._is_available = True
        except ImportError:
            self._is_available = False
        except Exception:
            self._is_available = False

    def embed(self, text: str) -> EmbeddingResult:
        """
        使用 OpenAI API 向量化文本

        Args:
            text: 输入文本

        Returns:
            EmbeddingResult
        """
        if not self._is_available:
            # 降级到默认服务
            return DefaultEmbeddingService().embed(text)

        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=text,
                dimensions=self._dimensions
            )

            embedding = response.data[0].embedding

            return EmbeddingResult(
                vector=embedding,
                model=self._model_name,
                dimensions=len(embedding),
                token_count=response.usage.total_tokens if hasattr(response, 'usage') else None
            )
        except Exception as e:
            # 降级到默认服务
            return DefaultEmbeddingService().embed(text)

    def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        批量向量化

        Args:
            texts: 文本列表

        Returns:
            EmbeddingResult 列表
        """
        if not self._is_available:
            return [self.embed(text) for text in texts]

        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=texts,
                dimensions=self._dimensions
            )

            results = []
            for i, data in enumerate(response.data):
                results.append(EmbeddingResult(
                    vector=data.embedding,
                    model=self._model_name,
                    dimensions=len(data.embedding),
                    token_count=response.usage.total_tokens if hasattr(response, 'usage') else None
                ))

            return results
        except Exception:
            # 降级到默认服务
            return [self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        """获取向量维度"""
        if self._dimensions:
            return self._dimensions
        # 返回模型默认维度
        if "small" in self._model:
            return 1536
        elif "large" in self._model:
            return 3072
        return 1536

    def get_model_name(self) -> str:
        """获取模型名称"""
        return self._model_name

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._is_available


class SentenceTransformerEmbeddingService(EmbeddingService):
    """
    Sentence Transformers 嵌入服务
    使用 sentence-transformers 库
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = None,
        normalize: bool = True
    ):
        """
        初始化 Sentence Transformers 嵌入服务

        Args:
            model_name: 模型名称
            device: 计算设备 ('cpu', 'cuda', 'auto')
            normalize: 是否归一化向量
        """
        self._model_name = model_name
        self._normalize = normalize
        self._model = None
        self._is_available = False
        self._dimensions = 384  # 默认维度

        self._init_model(device)

    def _init_model(self, device: str = None):
        """初始化模型"""
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name, device=device)
            self._dimensions = self._model.get_sentence_embedding_dimension()
            self._is_available = True
        except ImportError:
            self._is_available = False
        except Exception:
            self._is_available = False

    def embed(self, text: str) -> EmbeddingResult:
        """
        向量化单个文本

        Args:
            text: 输入文本

        Returns:
            EmbeddingResult
        """
        if not self._is_available:
            return DefaultEmbeddingService(self._dimensions).embed(text)

        embedding = self._model.encode(text, normalize_embeddings=self._normalize)

        return EmbeddingResult(
            vector=embedding.tolist(),
            model=self._model_name,
            dimensions=len(embedding),
            token_count=None
        )

    def embed_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        批量向量化

        Args:
            texts: 文本列表

        Returns:
            EmbeddingResult 列表
        """
        if not self._is_available:
            default = DefaultEmbeddingService(self._dimensions)
            return [default.embed(text) for text in texts]

        embeddings = self._model.encode(texts, normalize_embeddings=self._normalize)

        results = []
        for embedding in embeddings:
            results.append(EmbeddingResult(
                vector=embedding.tolist(),
                model=self._model_name,
                dimensions=len(embedding)
            ))

        return results

    def get_dimension(self) -> int:
        """获取向量维度"""
        return self._dimensions

    def get_model_name(self) -> str:
        """获取模型名称"""
        return self._model_name

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._is_available


def create_embedding_service(
    provider: str = "default",
    api_key: str = None,
    model: str = None,
    **kwargs
) -> EmbeddingService:
    """
    创建向量化服务

    Args:
        provider: 服务提供商 ('default', 'openai', 'sentence-transformers')
        api_key: API 密钥
        model: 模型名称
        **kwargs: 附加参数

    Returns:
        EmbeddingService 实例
    """
    if provider == "openai":
        return OpenAIEmbeddingService(
            api_key=api_key,
            model=model or "text-embedding-3-small",
            base_url=kwargs.get("base_url")
        )
    elif provider == "sentence-transformers":
        return SentenceTransformerEmbeddingService(
            model_name=model or "all-MiniLM-L6-v2",
            device=kwargs.get("device")
        )
    else:
        return DefaultEmbeddingService(
            dimensions=kwargs.get("dimensions", 384)
        )
