"""
上下文管理
提供跨消息的上下文传递和引用解析
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
import re


@dataclass
class ContextReference:
    """上下文引用"""
    ref_type: str  # "last_message", "context", "session", "file", etc.
    ref_key: str   # 引用键
    default: Any = None


class Context:
    """
    上下文对象
    存储和解析对话上下文中的引用
    """

    def __init__(self, session=None):
        self.session = session
        self._refs: Dict[str, ContextReference] = {}
        self._storage: Dict[str, Any] = {}

    def add_reference(self, name: str, ref_type: str, key: str, default: Any = None) -> None:
        """
        添加引用

        Args:
            name: 引用名称
            ref_type: 引用类型
            key: 引用键
            default: 默认值
        """
        self._refs[name] = ContextReference(
            ref_type=ref_type,
            ref_key=key,
            default=default
        )

    def set(self, key: str, value: Any) -> None:
        """
        设置上下文值

        Args:
            key: 键
            value: 值
        """
        self._storage[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取上下文值

        Args:
            key: 键
            default: 默认值

        Returns:
            值或默认值
        """
        # 检查是否是引用
        if key in self._refs:
            ref = self._refs[key]
            return self._resolve_reference(ref)

        # 直接返回值
        return self._storage.get(key, default)

    def _resolve_reference(self, ref: ContextReference) -> Any:
        """解析引用"""
        if ref.ref_type == "context":
            return self._storage.get(ref.ref_key, ref.default)

        elif ref.ref_type == "session":
            if self.session:
                if ref.ref_key == "last_message":
                    return self.session.last_message.content if self.session.last_message else ref.default
                elif ref.ref_key == "last_user_message":
                    for msg in reversed(self.session.messages):
                        if msg.role.value == "user":
                            return msg.content
                    return ref.default
                else:
                    return self.session.get_context(ref.ref_key, ref.default)
            return ref.default

        elif ref.ref_type == "message":
            if self.session:
                try:
                    idx = int(ref.ref_key)
                    return self.session.messages[-idx].content if abs(idx) <= len(self.session.messages) else ref.default
                except ValueError:
                    pass
            return ref.default

        return ref.default

    def update_from_session(self) -> None:
        """从会话更新上下文"""
        if not self.session:
            return

        # 导入必要的模块
        from .session import MessageRole

        # 添加常用引用
        self.add_reference("last_message", "session", "last_message")
        self.add_reference("last_user_message", "session", "last_user_message")

    def format_with_context(self, text: str) -> str:
        """
        格式化文本，解析上下文引用

        Args:
            text: 包含 {ref:name} 格式引用的文本

        Returns:
            解析后的文本
        """
        # 匹配 {ref:xxx} 格式
        pattern = r'\{ref:([a-zA-Z0-9_]+)\}'

        def replacer(match):
            ref_name = match.group(1)
            value = self.get(ref_name)
            if value is None:
                return match.group(0)  # 返回原样
            return str(value)

        return re.sub(pattern, replacer, text)

    def extract_references(self, text: str) -> List[str]:
        """
        从文本中提取引用

        Args:
            text: 文本

        Returns:
            引用的名称列表
        """
        pattern = r'\{ref:([a-zA-Z0-9_]+)\}'
        matches = re.findall(pattern, text)
        return list(set(matches))


class ContextBuilder:
    """
    上下文构建器
    方便构建和组合上下文
    """

    def __init__(self):
        self._session_refs: List[Dict[str, Any]] = []
        self._custom_refs: Dict[str, Dict[str, Any]] = {}
        self._storage: Dict[str, Any] = {}

    def with_session_reference(
        self,
        name: str,
        ref_type: str,
        key: str,
        default: Any = None
    ) -> 'ContextBuilder':
        """
        添加会话引用

        Returns:
            self
        """
        self._session_refs.append({
            "name": name,
            "ref_type": ref_type,
            "key": key,
            "default": default
        })
        return self

    def with_reference(
        self,
        name: str,
        ref_type: str,
        key: str,
        default: Any = None
    ) -> 'ContextBuilder':
        """
        添加自定义引用

        Returns:
            self
        """
        self._custom_refs[name] = {
            "ref_type": ref_type,
            "key": key,
            "default": default
        }
        return self

    def with_storage(self, key: str, value: Any) -> 'ContextBuilder':
        """
        添加存储值

        Returns:
            self
        """
        self._storage[key] = value
        return self

    def with_conversation_context(self) -> 'ContextBuilder':
        """添加对话常用上下文引用"""
        return (
            self
            .with_session_reference("last_message", "session", "last_message")
            .with_session_reference("prev_message", "message", "-2")
            .with_reference("current_time", "context", "current_time")
        )

    def build(self, session=None) -> Context:
        """
        构建上下文对象

        Args:
            session: 可选的会话对象

        Returns:
            Context 实例
        """
        ctx = Context(session=session)

        # 添加会话引用
        for ref in self._session_refs:
            ctx.add_reference(
                name=ref["name"],
                ref_type=ref["ref_type"],
                key=ref["key"],
                default=ref["default"]
            )

        # 添加自定义引用
        for name, ref in self._custom_refs.items():
            ctx.add_reference(
                name=name,
                ref_type=ref["ref_type"],
                key=ref["key"],
                default=ref["default"]
            )

        # 添加存储值
        for key, value in self._storage.items():
            ctx.set(key, value)

        return ctx


# 便捷函数
def create_context(session=None) -> Context:
    """创建上下文"""
    return ContextBuilder().with_conversation_context().build(session)
