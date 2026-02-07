"""
会话管理器
提供会话的创建、恢复、持久化功能
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid
import asyncio

from .session import Session, SessionStatus
from .context import Context, ContextBuilder


class SessionManager:
    """
    会话管理器
    单例模式，管理所有会话
    """

    _instance: Optional['SessionManager'] = None
    _sessions: Dict[str, Session] = {}
    _pending_approvals: Dict[str, Dict[str, Any]] = {}  # 待审批操作

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._sessions = {}
            cls._pending_approvals = {}
        return cls._instance

    @classmethod
    def reset(cls):
        """重置管理器（主要用于测试）"""
        cls._instance = None
        cls._sessions = {}
        cls._pending_approvals = {}

    # ==================== 会话管理 ====================

    def create_session(
        self,
        user_id: str,
        platform: str,
        title: Optional[str] = None,
        **metadata
    ) -> Session:
        """
        创建新会话

        Args:
            user_id: 用户 ID
            platform: 平台 (telegram, email, etc.)
            title: 会话标题
            **metadata: 附加元数据

        Returns:
            新创建的会话
        """
        session_id = str(uuid.uuid4())

        session = Session(
            session_id=session_id,
            user_id=user_id,
            platform=platform,
            title=title,
            metadata=metadata
        )

        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        获取会话

        Args:
            session_id: 会话 ID

        Returns:
            Session 或 None
        """
        return self._sessions.get(session_id)

    def get_or_create_session(
        self,
        user_id: str,
        platform: str,
        session_id: Optional[str] = None,
        **metadata
    ) -> Session:
        """
        获取或创建会话

        Args:
            user_id: 用户 ID
            platform: 平台
            session_id: 可选的会话 ID
            **metadata: 附加元数据

        Returns:
            Session
        """
        if session_id:
            existing = self.get_session(session_id)
            if existing and existing.user_id == user_id:
                return existing

        return self.create_session(user_id, platform, **metadata)

    def get_user_sessions(
        self,
        user_id: str,
        status: Optional[SessionStatus] = None,
        limit: int = 50
    ) -> List[Session]:
        """
        获取用户的所有会话

        Args:
            user_id: 用户 ID
            status: 可选的状态过滤
            limit: 返回数量限制

        Returns:
            会话列表
        """
        sessions = [
            s for s in self._sessions.values()
            if s.user_id == user_id and (status is None or s.status == status)
        ]

        # 按更新时间降序
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    def end_session(self, session_id: str) -> bool:
        """
        结束会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        session = self.get_session(session_id)
        if session:
            session.status = SessionStatus.ARCHIVED
            return True
        return False

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    # ==================== 消息管理 ====================

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        **metadata
    ) -> Optional['Session.Message']:
        """
        添加消息

        Args:
            session_id: 会话 ID
            role: 角色 (user, assistant, system)
            content: 消息内容
            **metadata: 附加元数据

        Returns:
            消息对象或 None
        """
        from .session import MessageRole

        session = self.get_session(session_id)
        if not session:
            return None

        role_enum = MessageRole(role) if isinstance(role, str) else role
        return session.add_message(role_enum, content, **metadata)

    def get_conversation(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List['Session.Message']:
        """
        获取对话历史

        Args:
            session_id: 会话 ID
            limit: 消息数量限制

        Returns:
            消息列表
        """
        session = self.get_session(session_id)
        if not session:
            return []
        return session.get_message_history(limit)

    def clear_history(self, session_id: str) -> bool:
        """
        清空对话历史

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        session = self.get_session(session_id)
        if session:
            session.messages.clear()
            session.clear_context()
            return True
        return False

    # ==================== 上下文管理 ====================

    def create_context(self, session_id: str) -> Context:
        """
        创建会话上下文

        Args:
            session_id: 会话 ID

        Returns:
            Context 对象
        """
        session = self.get_session(session_id)
        return ContextBuilder().with_conversation_context().build(session)

    def update_context(
        self,
        session_id: str,
        key: str,
        value: Any
    ) -> bool:
        """
        更新会话上下文

        Args:
            session_id: 会话 ID
            key: 键
            value: 值

        Returns:
            是否成功
        """
        session = self.get_session(session_id)
        if session:
            session.set_context(key, value)
            return True
        return False

    # ==================== 持久化 ====================

    async def save_session(self, session_id: str, filepath: str) -> bool:
        """
        保存会话到文件

        Args:
            session_id: 会话 ID
            filepath: 文件路径

        Returns:
            是否成功
        """
        session = self.get_session(session_id)
        if not session:
            return False

        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

            return True
        except Exception:
            return False

    async def load_session(self, filepath: str) -> Optional[Session]:
        """
        从文件加载会话

        Args:
            filepath: 文件路径

        Returns:
            Session 或 None
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            session = Session.from_dict(data)
            self._sessions[session.session_id] = session
            return session
        except Exception:
            return None

    # ==================== 统计信息 ====================

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = len(self._sessions)
        active = len([s for s in self._sessions.values() if s.status == SessionStatus.ACTIVE])
        archived = len([s for s in self._sessions.values() if s.status == SessionStatus.ARCHIVED])

        total_messages = sum(s.message_count for s in self._sessions.values())

        return {
            "total_sessions": total,
            "active_sessions": active,
            "archived_sessions": archived,
            "total_messages": total_messages
        }

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """
        清理旧会话

        Args:
            days: 超过多少天的归档会话将被删除

        Returns:
            删除的会话数量
        """
        cutoff = datetime.now() - timedelta(days=days)
        to_delete = []

        for session in self._sessions.values():
            if session.status == SessionStatus.ARCHIVED and session.updated_at < cutoff:
                to_delete.append(session.session_id)

        for session_id in to_delete:
            self.delete_session(session_id)

        return len(to_delete)

    # ==================== 审批管理 ====================

    def request_approval(
        self,
        session_id: str,
        action: str,
        details: Dict[str, Any]
    ) -> str:
        """
        请求用户审批

        Args:
            session_id: 会话 ID
            action: 操作描述
            details: 操作详情

        Returns:
            审批 ID
        """
        approval_id = str(uuid.uuid4())

        self._pending_approvals[approval_id] = {
            "session_id": session_id,
            "action": action,
            "details": details,
            "created_at": datetime.now().isoformat()
        }

        return approval_id

    def get_pending_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """获取待审批操作"""
        return self._pending_approvals.get(approval_id)

    def complete_approval(self, approval_id: str, approved: bool) -> bool:
        """
        完成审批

        Args:
            approval_id: 审批 ID
            approved: 是否批准

        Returns:
            是否找到该审批
        """
        if approval_id in self._pending_approvals:
            del self._pending_approvals[approval_id]
            return True
        return False

    # ==================== 会话引用解析 ====================

    def resolve_reference(
        self,
        session_id: str,
        reference: str
    ) -> Any:
        """
        解析会话中的引用

        Args:
            session_id: 会话 ID
            reference: 引用字符串（如 "last_message", "context:folder_name"）

        Returns:
            解析后的值
        """
        session = self.get_session(session_id)
        if not session:
            return None

        # 解析格式: type:key
        if ':' in reference:
            ref_type, key = reference.split(':', 1)
        else:
            ref_type = reference
            key = None

        if ref_type == "last_message":
            return session.last_message.content if session.last_message else None

        elif ref_type == "context" and key:
            return session.get_context(key)

        elif ref_type == "file":
            # 文件路径引用
            return session.get_context(f"file_{key}")

        elif ref_type == "folder":
            # 文件夹引用
            return session.get_context(f"folder_{key}")

        return None


# 全局管理器实例
session_manager = SessionManager()


# 便捷函数
def get_session_manager() -> SessionManager:
    """获取会话管理器实例"""
    return session_manager


def get_or_create_session(
    user_id: str,
    platform: str,
    session_id: Optional[str] = None,
    **metadata
) -> Session:
    """获取或创建会话"""
    return session_manager.get_or_create_session(
        user_id, platform, session_id, **metadata
    )


def get_user_sessions(
    user_id: str,
    status: Optional[SessionStatus] = None
) -> List[Session]:
    """获取用户会话列表"""
    return session_manager.get_user_sessions(user_id, status)
