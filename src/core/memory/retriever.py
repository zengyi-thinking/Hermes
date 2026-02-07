"""
记忆检索模块
提供 RAG 风格的语义检索功能
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
import numpy as np


@dataclass
class RetrievedMemory:
    """检索到的记忆"""
    entry_id: str
    memory_type: str
    user_id: str
    content: str
    relevance_score: float
    metadata: Dict[str, Any]
    created_at: datetime

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "memory_type": self.memory_type,
            "user_id": self.user_id,
            "content": self.content,
            "relevance_score": self.relevance_score,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }


class MemoryRetriever:
    """记忆检索器"""

    def __init__(
        self,
        embedding_service = None,
        enable_semantic_search: bool = True
    ):
        """
        初始化记忆检索器

        Args:
            embedding_service: 向量化服务
            enable_semantic_search: 是否启用语义搜索
        """
        self._embedding_service = embedding_service
        self._enable_semantic_search = enable_semantic_search
        self._cache: Dict[str, np.ndarray] = {}  # entry_id -> embedding

    def set_embedding_service(self, service):
        """设置向量化服务"""
        self._embedding_service = service

    async def retrieve_relevant(
        self,
        query: str,
        user_id: str,
        memory_system = None,
        top_k: int = 5,
        memory_types: List[str] = None,
        min_relevance: float = 0.0
    ) -> List[RetrievedMemory]:
        """
        检索相关记忆

        Args:
            query: 查询文本
            user_id: 用户 ID
            memory_system: 记忆系统实例
            top_k: 返回结果数量
            memory_types: 记忆类型过滤
            min_relevance: 最小相关性分数

        Returns:
            RetrievedMemory 列表
        """
        results = []

        if memory_system is None:
            return results

        # 获取用户的所有记忆
        entries = memory_system.search_memories(
            user_id=user_id,
            query=query if not self._enable_semantic_search else None,
            memory_type=memory_types[0] if memory_types else None,
            limit=100
        )

        # 计算相关性分数
        if self._enable_semantic_search and self._embedding_service:
            query_embedding = self._get_embedding(query)

            for entry in entries:
                score = self._calculate_similarity(query_embedding, entry.embedding)
                if score >= min_relevance:
                    results.append(RetrievedMemory(
                        entry_id=entry.entry_id,
                        memory_type=entry.memory_type,
                        user_id=entry.user_id,
                        content=entry.content,
                        relevance_score=score,
                        metadata=entry.metadata,
                        created_at=entry.created_at
                    ))
        else:
            # 简单的关键词匹配
            query_words = query.lower().split()

            for entry in entries:
                content_lower = entry.content.lower()
                word_matches = sum(1 for word in query_words if word in content_lower)
                score = word_matches / max(len(query_words), 1)

                if score >= min_relevance:
                    results.append(RetrievedMemory(
                        entry_id=entry.entry_id,
                        memory_type=entry.memory_type,
                        user_id=entry.user_id,
                        content=entry.content,
                        relevance_score=score,
                        metadata=entry.metadata,
                        created_at=entry.created_at
                    ))

        # 排序并返回 top_k
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        return results[:top_k]

    async def retrieve_user_preferences(
        self,
        query: str,
        user_id: str,
        memory_system = None
    ) -> Dict[str, Any]:
        """
        检索用户偏好

        Args:
            query: 查询文本
            user_id: 用户 ID
            memory_system: 记忆系统实例

        Returns:
            用户偏好字典
        """
        pref = memory_system.get_preference(user_id) if memory_system else None

        if pref:
            return {
                "preferred_language": pref.preferred_language,
                "code_style": pref.code_style,
                "communication_style": pref.communication_style,
                "preferred_encoding": pref.preferred_encoding,
                "timezone": pref.timezone,
                "custom_settings": pref.custom_settings
            }

        # 返回默认偏好
        return {
            "preferred_language": "zh-CN",
            "code_style": "clean",
            "communication_style": "concise",
            "preferred_encoding": "utf-8",
            "timezone": "Asia/Shanghai",
            "custom_settings": {}
        }

    async def retrieve_interaction_history(
        self,
        query: str,
        user_id: str,
        memory_system = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        检索交互历史

        Args:
            query: 查询文本
            user_id: 用户 ID
            memory_system: 记忆系统实例
            limit: 返回数量限制

        Returns:
            交互历史列表
        """
        if memory_system is None:
            return []

        # 获取用户的历史
        histories = memory_system.get_user_history(user_id, limit=limit * 2)

        # 简单的任务相关性匹配
        query_words = set(query.lower().split())

        scored_histories = []
        for history in histories:
            history_words = set(history.task_summary.lower().split())
            overlap = query_words & history_words
            if overlap:
                score = len(overlap) / max(len(query_words), len(history_words))
                scored_histories.append({
                    "session_id": history.session_id,
                    "task_summary": history.task_summary,
                    "outcome": history.outcome,
                    "key_learning": history.key_learning,
                    "duration_seconds": history.duration_seconds,
                    "timestamp": history.timestamp.isoformat(),
                    "relevance_score": score
                })

        # 按相关性排序
        scored_histories.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored_histories[:limit]

    def _get_embedding(self, text: str) -> np.ndarray:
        """获取文本的向量表示"""
        if self._embedding_service:
            result = self._embedding_service.embed(text)
            return result.numpy
        # 返回零向量
        return np.zeros(384)

    def _calculate_similarity(
        self,
        embedding1: np.ndarray,
        embedding2: List[float]
    ) -> float:
        """
        计算两个向量的余弦相似度

        Args:
            embedding1: 第一个向量
            embedding2: 第二个向量

        Returns:
            余弦相似度
        """
        if embedding2 is None:
            return 0.0

        vec2 = np.array(embedding2)

        # 防止除零
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        cosine = np.dot(embedding1, vec2) / (norm1 * norm2)
        # 确保在 [0, 1] 范围内
        return max(0.0, min(1.0, cosine))


async def retrieve_relevant_memories(
    query: str,
    user_id: str,
    memory_system = None,
    embedding_service = None,
    top_k: int = 5,
    memory_types: List[str] = None
) -> List[RetrievedMemory]:
    """
    便捷函数：检索相关记忆

    Args:
        query: 查询文本
        user_id: 用户 ID
        memory_system: 记忆系统实例
        embedding_service: 向量化服务
        top_k: 返回结果数量
        memory_types: 记忆类型过滤

    Returns:
        RetrievedMemory 列表
    """
    retriever = MemoryRetriever(embedding_service=embedding_service)
    return await retriever.retrieve_relevant(
        query=query,
        user_id=user_id,
        memory_system=memory_system,
        top_k=top_k,
        memory_types=memory_types
    )


class ContextBuilder:
    """上下文构建器"""

    def __init__(self, memory_retriever: MemoryRetriever = None):
        """
        初始化上下文构建器

        Args:
            memory_retriever: 记忆检索器
        """
        self._retriever = memory_retriever or MemoryRetriever()

    async def build_context(
        self,
        query: str,
        user_id: str,
        memory_system = None,
        include_preferences: bool = True,
        include_history: bool = True,
        include_knowledge: bool = True
    ) -> Dict[str, Any]:
        """
        构建检索增强的上下文

        Args:
            query: 查询文本
            user_id: 用户 ID
            memory_system: 记忆系统实例
            include_preferences: 是否包含用户偏好
            include_history: 是否包含交互历史
            include_knowledge: 是否包含知识记忆

        Returns:
            上下文字典
        """
        context = {
            "retrieved_memories": [],
            "user_preferences": {},
            "interaction_history": []
        }

        if memory_system is None:
            return context

        # 检索相关记忆
        memory_types = []
        if include_knowledge:
            memory_types.append("knowledge")

        if memory_types or not include_preferences and not include_history:
            memories = await self._retriever.retrieve_relevant(
                query=query,
                user_id=user_id,
                memory_system=memory_system,
                top_k=5,
                memory_types=memory_types if memory_types else None
            )
            context["retrieved_memories"] = [m.to_dict() for m in memories]

        # 获取用户偏好
        if include_preferences:
            preferences = await self._retriever.retrieve_user_preferences(
                query=query,
                user_id=user_id,
                memory_system=memory_system
            )
            context["user_preferences"] = preferences

        # 获取交互历史
        if include_history:
            history = await self._retriever.retrieve_interaction_history(
                query=query,
                user_id=user_id,
                memory_system=memory_system,
                limit=5
            )
            context["interaction_history"] = history

        return context

    def format_context_for_prompt(
        self,
        context: Dict[str, Any],
        max_length: int = 2000
    ) -> str:
        """
        将上下文格式化为提示词

        Args:
            context: 上下文字典
            max_length: 最大长度

        Returns:
            格式化的上下文文本
        """
        parts = []

        # 用户偏好
        preferences = context.get("user_preferences", {})
        if preferences:
            pref_parts = ["用户偏好:"]
            for key, value in preferences.items():
                if value and key != "custom_settings":
                    pref_parts.append(f"  - {key}: {value}")
            if pref_parts:
                parts.append("\n".join(pref_parts))

        # 交互历史
        history = context.get("interaction_history", [])
        if history:
            history_parts = ["相关历史:"]
            for h in history[:3]:  # 最多 3 条
                outcome_emoji = "✅" if h.get("outcome") == "success" else "❌"
                summary = h.get("task_summary", "")[:100]
                learning = h.get("key_learning", "")
                history_parts.append(f"  {outcome_emoji} {summary}")
                if learning:
                    history_parts.append(f"      学到的: {learning[:50]}")
            parts.append("\n".join(history_parts))

        # 相关记忆
        memories = context.get("retrieved_memories", [])
        if memories:
            memory_parts = ["相关记忆:"]
            for m in memories[:3]:  # 最多 3 条
                score = m.get("relevance_score", 0)
                content = m.get("content", "")[:100]
                memory_parts.append(f"  [{score:.2f}] {content}")
            parts.append("\n".join(memory_parts))

        result = "\n\n".join(parts)

        if len(result) > max_length:
            result = result[:max_length] + "\n...(更多上下文)"

        return result
