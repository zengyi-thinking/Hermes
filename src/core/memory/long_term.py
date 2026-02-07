"""
长期记忆模块
管理用户偏好、历史交互记录和持久化记忆存储
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pathlib import Path
import json
import os


class MemoryType(Enum):
    """记忆类型"""
    USER_PREFERENCE = "user_preference"
    INTERACTION_HISTORY = "interaction_history"
    PROJECT_CONTEXT = "project_context"
    KNOWLEDGE = "knowledge"


@dataclass
class UserPreference:
    """用户偏好"""
    user_id: str
    preferred_language: str = "zh-CN"
    code_style: str = "clean"
    communication_style: str = "concise"  # concise | detailed
    preferred_encoding: str = "utf-8"
    timezone: str = "Asia/Shanghai"
    custom_settings: Dict[str, Any] = field(default_factory=dict)

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "preferred_language": self.preferred_language,
            "code_style": self.code_style,
            "communication_style": self.communication_style,
            "preferred_encoding": self.preferred_encoding,
            "timezone": self.timezone,
            "custom_settings": self.custom_settings,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserPreference":
        return cls(
            user_id=data["user_id"],
            preferred_language=data.get("preferred_language", "zh-CN"),
            code_style=data.get("code_style", "clean"),
            communication_style=data.get("communication_style", "concise"),
            preferred_encoding=data.get("preferred_encoding", "utf-8"),
            timezone=data.get("timezone", "Asia/Shanghai"),
            custom_settings=data.get("custom_settings", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now()
        )


@dataclass
class InteractionHistory:
    """交互历史记录"""
    session_id: str
    user_id: str
    task_summary: str
    outcome: str  # "success" | "failed" | "cancelled"
    key_learning: str = ""  # 从这次交互中学到的要点
    file_changes: Dict[str, str] = field(default_factory=dict)  # 文件变更
    duration_seconds: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "task_summary": self.task_summary,
            "outcome": self.outcome,
            "key_learning": self.key_learning,
            "file_changes": self.file_changes,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InteractionHistory":
        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            task_summary=data["task_summary"],
            outcome=data.get("outcome", "success"),
            key_learning=data.get("key_learning", ""),
            file_changes=data.get("file_changes", {}),
            duration_seconds=data.get("duration_seconds", 0.0),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
            metadata=data.get("metadata", {})
        )


@dataclass
class MemoryEntry:
    """记忆条目"""
    entry_id: str
    memory_type: str
    user_id: str
    content: str
    embedding: List[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # TTL 配置
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = None
    last_accessed: datetime = field(default_factory=datetime.now)

    # 访问统计
    access_count: int = 0
    importance_score: float = 0.5  # 0.0 - 1.0

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "memory_type": self.memory_type,
            "user_id": self.user_id,
            "content": self.content,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
            "importance_score": self.importance_score
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        return cls(
            entry_id=data["entry_id"],
            memory_type=data["memory_type"],
            user_id=data["user_id"],
            content=data["content"],
            embedding=data.get("embedding"),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else datetime.now(),
            access_count=data.get("access_count", 0),
            importance_score=data.get("importance_score", 0.5)
        )

    def is_expired(self) -> bool:
        """检查是否已过期"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


class MemoryStore(ABC):
    """记忆存储抽象基类"""

    @abstractmethod
    def save(self, entry: MemoryEntry) -> bool:
        """保存记忆"""
        pass

    @abstractmethod
    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """获取记忆"""
        pass

    @abstractmethod
    def delete(self, entry_id: str) -> bool:
        """删除记忆"""
        pass

    @abstractmethod
    def list_by_user(self, user_id: str, memory_type: str = None) -> List[MemoryEntry]:
        """列出用户的记忆"""
        pass

    @abstractmethod
    def cleanup_expired(self) -> int:
        """清理过期的记忆"""
        pass


class FileMemoryStore(MemoryStore):
    """基于文件的记忆存储"""

    def __init__(self, storage_dir: str = "./memory"):
        """
        初始化文件存储

        Args:
            storage_dir: 存储目录
        """
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, MemoryEntry] = {}
        self._load_from_disk()

    def _get_file_path(self, entry_id: str) -> Path:
        """获取条目文件路径"""
        return self._storage_dir / f"{entry_id}.json"

    def _load_from_disk(self):
        """从磁盘加载所有条目"""
        if not self._storage_dir.exists():
            return

        for file_path in self._storage_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                entry = MemoryEntry.from_dict(data)
                self._entries[entry.entry_id] = entry
            except Exception:
                continue

    def _save_to_disk(self, entry: MemoryEntry):
        """保存条目到磁盘"""
        file_path = self._get_file_path(entry.entry_id)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)

    def save(self, entry: MemoryEntry) -> bool:
        """保存记忆"""
        self._entries[entry.entry_id] = entry
        self._save_to_disk(entry)
        return True

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """获取记忆"""
        entry = self._entries.get(entry_id)
        if entry:
            entry.last_accessed = datetime.now()
            entry.access_count += 1
        return entry

    def delete(self, entry_id: str) -> bool:
        """删除记忆"""
        if entry_id in self._entries:
            del self._entries[entry_id]
            file_path = self._get_file_path(entry_id)
            if file_path.exists():
                file_path.unlink()
            return True
        return False

    def list_by_user(self, user_id: str, memory_type: str = None) -> List[MemoryEntry]:
        """列出用户的记忆"""
        entries = [
            entry for entry in self._entries.values()
            if entry.user_id == user_id
        ]

        if memory_type:
            entries = [e for e in entries if e.memory_type == memory_type]

        return sorted(entries, key=lambda x: x.created_at, reverse=True)

    def cleanup_expired(self) -> int:
        """清理过期的记忆"""
        expired_ids = [
            entry_id for entry_id, entry in self._entries.items()
            if entry.is_expired()
        ]

        for entry_id in expired_ids:
            self.delete(entry_id)

        return len(expired_ids)


class LongTermMemory:
    """
    长期记忆管理器
    管理用户偏好、历史交互和持久化记忆
    """

    def __init__(
        self,
        storage_dir: str = "./memory",
        default_ttl_days: int = 90
    ):
        """
        初始化长期记忆管理器

        Args:
            storage_dir: 记忆存储目录
            default_ttl_days: 默认 TTL（天）
        """
        self._storage_dir = Path(storage_dir)
        self._default_ttl_days = default_ttl_days
        self._store = FileMemoryStore(storage_dir)

        # 用户偏好存储
        self._preferences_dir = self._storage_dir / "preferences"
        self._preferences_dir.mkdir(parents=True, exist_ok=True)
        self._preferences: Dict[str, UserPreference] = {}

        # 交互历史存储
        self._history_dir = self._storage_dir / "history"
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._history: Dict[str, InteractionHistory] = {}

        self._load_preferences()
        self._load_history()

    def _get_preference_file(self, user_id: str) -> Path:
        """获取用户偏好文件路径"""
        return self._preferences_dir / f"{user_id}.json"

    def _get_history_file(self, session_id: str) -> Path:
        """获取历史记录文件路径"""
        return self._history_dir / f"{session_id}.json"

    def _load_preferences(self):
        """加载所有用户偏好"""
        if not self._preferences_dir.exists():
            return

        for file_path in self._preferences_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                pref = UserPreference.from_dict(data)
                self._preferences[pref.user_id] = pref
            except Exception:
                continue

    def _load_history(self):
        """加载所有交互历史"""
        if not self._history_dir.exists():
            return

        for file_path in self._history_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                history = InteractionHistory.from_dict(data)
                self._history[history.session_id] = history
            except Exception:
                continue

    # ==================== 用户偏好管理 ====================

    def get_preference(self, user_id: str) -> Optional[UserPreference]:
        """
        获取用户偏好

        Args:
            user_id: 用户 ID

        Returns:
            UserPreference 或 None
        """
        return self._preferences.get(user_id)

    def set_preference(self, user_id: str, **preferences) -> UserPreference:
        """
        设置用户偏好

        Args:
            user_id: 用户 ID
            **preferences: 偏好设置

        Returns:
            UserPreference
        """
        if user_id in self._preferences:
            pref = self._preferences[user_id]
            for key, value in preferences.items():
                if hasattr(pref, key):
                    setattr(pref, key, value)
            pref.updated_at = datetime.now()
        else:
            pref = UserPreference(user_id=user_id, **preferences)

        self._preferences[user_id] = pref
        self._save_preference(pref)
        return pref

    def _save_preference(self, pref: UserPreference):
        """保存用户偏好到磁盘"""
        file_path = self._get_preference_file(pref.user_id)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(pref.to_dict(), f, ensure_ascii=False, indent=2)

    def delete_preference(self, user_id: str) -> bool:
        """
        删除用户偏好

        Args:
            user_id: 用户 ID

        Returns:
            是否成功
        """
        if user_id in self._preferences:
            del self._preferences[user_id]
            file_path = self._get_preference_file(user_id)
            if file_path.exists():
                file_path.unlink()
            return True
        return False

    def get_all_preferences(self) -> List[UserPreference]:
        """获取所有用户偏好"""
        return list(self._preferences.values())

    # ==================== 交互历史管理 ====================

    def add_history(self, history: InteractionHistory):
        """
        添加交互历史

        Args:
            history: 交互历史记录
        """
        self._history[history.session_id] = history
        self._save_history(history)

    def get_history(self, session_id: str) -> Optional[InteractionHistory]:
        """
        获取交互历史

        Args:
            session_id: 会话 ID

        Returns:
            InteractionHistory 或 None
        """
        history = self._history.get(session_id)
        if history:
            return history
        # 尝试从磁盘加载
        file_path = self._get_history_file(session_id)
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            history = InteractionHistory.from_dict(data)
            self._history[session_id] = history
            return history
        return None

    def get_user_history(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[InteractionHistory]:
        """
        获取用户的交互历史

        Args:
            user_id: 用户 ID
            limit: 返回数量限制

        Returns:
            InteractionHistory 列表
        """
        histories = [
            h for h in self._history.values()
            if h.user_id == user_id
        ]
        histories.sort(key=lambda x: x.timestamp, reverse=True)
        return histories[:limit]

    def get_recent_outcomes(
        self,
        user_id: str,
        outcome: str,
        limit: int = 10
    ) -> List[InteractionHistory]:
        """
        获取用户最近的特定结果历史

        Args:
            user_id: 用户 ID
            outcome: 结果类型 (success, failed, cancelled)
            limit: 返回数量限制

        Returns:
            InteractionHistory 列表
        """
        histories = [
            h for h in self._history.values()
            if h.user_id == user_id and h.outcome == outcome
        ]
        histories.sort(key=lambda x: x.timestamp, reverse=True)
        return histories[:limit]

    def _save_history(self, history: InteractionHistory):
        """保存历史到磁盘"""
        file_path = self._get_history_file(history.session_id)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(history.to_dict(), f, ensure_ascii=False, indent=2)

    def get_history_stats(self, user_id: str) -> dict:
        """
        获取用户历史统计

        Args:
            user_id: 用户 ID

        Returns:
            统计信息
        """
        histories = self.get_user_history(user_id, limit=1000)

        success_count = sum(1 for h in histories if h.outcome == "success")
        failed_count = sum(1 for h in histories if h.outcome == "failed")
        cancelled_count = sum(1 for h in histories if h.outcome == "cancelled")

        avg_duration = 0.0
        if histories:
            avg_duration = sum(h.duration_seconds for h in histories) / len(histories)

        return {
            "total_tasks": len(histories),
            "success_count": success_count,
            "failed_count": failed_count,
            "cancelled_count": cancelled_count,
            "success_rate": success_count / len(histories) if histories else 0,
            "average_duration_seconds": avg_duration
        }

    # ==================== 记忆条目管理 ====================

    def add_memory(
        self,
        memory_type: str,
        user_id: str,
        content: str,
        embedding: List[float] = None,
        metadata: Dict[str, Any] = None,
        ttl_days: int = None,
        importance: float = 0.5
    ) -> MemoryEntry:
        """
        添加记忆条目

        Args:
            memory_type: 记忆类型
            user_id: 用户 ID
            content: 记忆内容
            embedding: 向量嵌入
            metadata: 元数据
            ttl_days: TTL（天）
            importance: 重要性分数

        Returns:
            MemoryEntry
        """
        import uuid
        entry_id = str(uuid.uuid4())

        expires_at = None
        if ttl_days or self._default_ttl_days:
            from datetime import timedelta
            ttl = ttl_days or self._default_ttl_days
            expires_at = datetime.now() + timedelta(days=ttl)

        entry = MemoryEntry(
            entry_id=entry_id,
            memory_type=memory_type,
            user_id=user_id,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            expires_at=expires_at,
            importance_score=importance
        )

        self._store.save(entry)
        return entry

    def get_memory(self, entry_id: str) -> Optional[MemoryEntry]:
        """获取记忆条目"""
        return self._store.get(entry_id)

    def search_memories(
        self,
        user_id: str,
        query: str = None,
        memory_type: str = None,
        limit: int = 10
    ) -> List[MemoryEntry]:
        """
        搜索记忆

        Args:
            user_id: 用户 ID
            query: 查询文本
            memory_type: 记忆类型过滤
            limit: 返回数量限制

        Returns:
            MemoryEntry 列表
        """
        entries = self._store.list_by_user(user_id, memory_type)

        # 如果有查询，简单的关键词匹配
        if query:
            query_lower = query.lower()
            entries = [
                e for e in entries
                if query_lower in e.content.lower()
            ]

        # 按重要性和创建时间排序
        entries.sort(key=lambda x: (x.importance_score, x.created_at), reverse=True)

        return entries[:limit]

    def delete_memory(self, entry_id: str) -> bool:
        """删除记忆条目"""
        return self._store.delete(entry_id)

    def cleanup_expired_memories(self) -> int:
        """清理过期记忆"""
        return self._store.cleanup_expired()

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_memories": len(self._store.list_by_user("")),
            "total_preferences": len(self._preferences),
            "total_history": len(self._history)
        }
