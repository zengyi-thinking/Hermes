"""
Skills 技能系统模块
提供可插拔的工具/技能机制
"""

from .base import Skill, SkillPermission, SkillResult
from .registry import SkillRegistry, register_skill, get_skill, execute_skill, list_skills
from .builtins import BuiltinSkills, register_builtin_skills

__all__ = [
    'Skill',
    'SkillPermission',
    'SkillResult',
    'SkillRegistry',
    'register_skill',
    'get_skill',
    'execute_skill',
    'list_skills',
    'BuiltinSkills',
    'register_builtin_skills',
]
