"""
内置技能模块
"""

from .calculator import CalculatorSkill
from .file_search import FileSearchSkill
from .web_search import WebSearchSkill
from .system_info import SystemInfoSkill


class BuiltinSkills:
    """
    内置技能管理器
    提供内置技能的注册和访问
    """

    SKILLS = [
        CalculatorSkill,
        FileSearchSkill,
        WebSearchSkill,
        SystemInfoSkill,
    ]

    @classmethod
    def register_all(cls, registry) -> None:
        """注册所有内置技能"""
        for skill_class in cls.SKILLS:
            registry.register(skill_class)

    @classmethod
    def get_calculator(cls):
        """获取计算器技能"""
        return CalculatorSkill()

    @classmethod
    def get_file_search(cls):
        """获取文件搜索技能"""
        return FileSearchSkill()

    @classmethod
    def get_web_search(cls):
        """获取网络搜索技能"""
        return WebSearchSkill()

    @classmethod
    def get_system_info(cls):
        """获取系统信息技能"""
        return SystemInfoSkill()


# 便捷函数
def register_builtin_skills():
    """注册所有内置技能到全局注册表"""
    from ..registry import SkillRegistry
    BuiltinSkills.register_all(SkillRegistry)


__all__ = [
    'BuiltinSkills',
    'register_builtin_skills',
    'CalculatorSkill',
    'FileSearchSkill',
    'WebSearchSkill',
    'SystemInfoSkill',
]
