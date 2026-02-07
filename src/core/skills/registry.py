"""
技能注册表
提供技能的注册、查找、列表功能
"""

from typing import Any, Dict, List, Optional, Type
from .base import Skill, SkillResult, SkillPermission


class SkillRegistry:
    """
    全局技能注册表
    单例模式，确保全局只有一个注册表实例
    """

    _instance: Optional['SkillRegistry'] = None
    _skills: Dict[str, Type[Skill]] = {}
    _skill_instances: Dict[str, Skill] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._skills = {}
            cls._skill_instances = {}
        return cls._instance

    @classmethod
    def reset(cls):
        """重置注册表（主要用于测试）"""
        cls._instance = None
        cls._skills = {}
        cls._skill_instances = {}

    @classmethod
    def register(cls, skill_class: Type[Skill]) -> None:
        """
        注册技能类

        Args:
            skill_class: 继承自 Skill 的类
        """
        if not issubclass(skill_class, Skill):
            raise TypeError(f"{skill_class.__name__} 不是 Skill 的子类")

        skill_name = skill_class.name
        if skill_name in cls._skills:
            raise ValueError(f"技能 {skill_name} 已经注册")

        cls._skills[skill_name] = skill_class

    @classmethod
    def register_instance(cls, skill: Skill) -> None:
        """
        注册技能实例

        Args:
            skill: Skill 实例
        """
        skill_name = skill.name
        if skill_name in cls._skill_instances:
            raise ValueError(f"技能实例 {skill_name} 已经注册")

        cls._skill_instances[skill_name] = skill

    @classmethod
    def get(cls, name: str) -> Optional[Type[Skill]]:
        """
        获取技能类

        Args:
            name: 技能名称

        Returns:
            技能类，如果不存在返回 None
        """
        return cls._skills.get(name)

    @classmethod
    def get_instance(cls, name: str) -> Optional[Skill]:
        """
        获取技能实例

        Args:
            name: 技能名称

        Returns:
            Skill 实例，如果不存在返回 None
        """
        # 先检查实例缓存
        if name in cls._skill_instances:
            return cls._skill_instances[name]

        # 如果只有类没有实例，创建一个
        skill_class = cls._skills.get(name)
        if skill_class:
            instance = skill_class()
            cls._skill_instances[name] = instance
            return instance

        return None

    @classmethod
    def list_available(cls) -> List[Dict[str, Any]]:
        """
        列出所有可用技能

        Returns:
            技能信息列表
        """
        result = []
        for name, skill_class in cls._skills.items():
            instance = cls.get_instance(name)
            result.append({
                "name": name,
                "description": instance.description if instance else skill_class.description,
                "permission_level": instance.permission_level if instance else skill_class.permission_level,
                "examples": instance.examples if instance else []
            })
        return result

    @classmethod
    def list_by_permission(cls, level: SkillPermission) -> List[Dict[str, Any]]:
        """
        按权限级别列出技能

        Args:
            level: 权限级别

        Returns:
            技能信息列表
        """
        return [
            info for info in cls.list_available()
            if info["permission_level"] == level
        ]

    @classmethod
    def execute(cls, name: str, **kwargs) -> SkillResult:
        """
        执行技能

        Args:
            name: 技能名称
            **kwargs: 技能参数

        Returns:
            SkillResult: 执行结果
        """
        skill = cls.get_instance(name)
        if not skill:
            return SkillResult(
                success=False,
                error=f"技能 {name} 不存在"
            )

        return skill.execute(**kwargs)

    @classmethod
    def require_approval(cls, name: str) -> bool:
        """
        检查技能是否需要审批

        Args:
            name: 技能名称

        Returns:
            是否需要审批
        """
        skill = cls.get_instance(name)
        if not skill:
            return False
        return skill.require_approval()

    @classmethod
    def get_count(cls) -> int:
        """获取已注册技能数量"""
        return len(cls._skills)

    @classmethod
    def get_all_names(cls) -> List[str]:
        """获取所有技能名称"""
        return list(cls._skills.keys())


# 全局注册表实例
registry = SkillRegistry()


def register_skill(skill_class: Type[Skill]) -> Type[Skill]:
    """
    装饰器：注册技能

    Usage:
        @register_skill
        class MySkill(Skill):
            name = "my_skill"
            ...
    """
    SkillRegistry.register(skill_class)
    return skill_class


def get_skill(name: str) -> Optional[Skill]:
    """
    获取技能实例

    Args:
        name: 技能名称

    Returns:
        Skill 实例
    """
    return SkillRegistry.get_instance(name)


def list_skills() -> List[Dict[str, Any]]:
    """列出所有可用技能"""
    return SkillRegistry.list_available()


def execute_skill(name: str, **kwargs) -> SkillResult:
    """
    执行技能

    Args:
        name: 技能名称
        **kwargs: 技能参数

    Returns:
        SkillResult: 执行结果
    """
    return SkillRegistry.execute(name, **kwargs)
