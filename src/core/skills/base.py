"""
技能基类定义
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class SkillPermission(str, Enum):
    """技能权限级别"""
    NORMAL = "normal"      # 普通权限，直接执行
    SENSITIVE = "sensitive"  # 敏感权限，需要警告
    DANGEROUS = "dangerous"  # 危险权限，需要用户审批


@dataclass
class SkillResult:
    """技能执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    requires_approval: bool = False
    approval_message: Optional[str] = None


class Skill(ABC):
    """技能基类"""

    # 子类必须定义这些属性
    name: str = ""
    description: str = ""
    permission_level: SkillPermission = SkillPermission.NORMAL
    examples: list = field(default_factory=list)

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """
        执行技能逻辑

        Args:
            **kwargs: 技能参数

        Returns:
            SkillResult: 执行结果
        """
        pass

    def get_full_description(self) -> str:
        """获取完整描述（包含参数信息）"""
        return f"{self.name}: {self.description}"

    def require_approval(self) -> bool:
        """是否需要用户审批"""
        return self.permission_level == SkillPermission.DANGEROUS

    def get_permission_level(self) -> SkillPermission:
        """获取权限级别"""
        return self.permission_level


class CalculatorSkill(Skill):
    """计算器技能 - 示例实现"""

    name = "calculator"
    description = "执行数学计算，支持加减乘除、百分比、幂运算等"
    permission_level = SkillPermission.NORMAL
    examples = [
        "计算 15% tip on $85",
        "计算 100 * 25 + 50",
        "计算 (10 + 5) * 2"
    ]

    async def execute(self, expression: str, **kwargs) -> SkillResult:
        """执行计算"""
        try:
            # 安全计算：只允许数字和基本运算符
            allowed_chars = set('0123456789+-*/.%() ')
            if not all(c in allowed_chars for c in expression):
                return SkillResult(
                    success=False,
                    error="表达式包含非法字符"
                )

            # 使用 eval 进行计算（已限制字符集）
            result = eval(expression)

            return SkillResult(
                success=True,
                data={
                    "expression": expression,
                    "result": result
                }
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"计算错误: {str(e)}"
            )


class FileSearchSkill(Skill):
    """文件搜索技能"""

    name = "file_search"
    description = "搜索文件和目录，支持按名称、路径模式匹配"
    permission_level = SkillPermission.NORMAL
    examples = [
        "搜索所有 *.py 文件",
        "查找包含 'test' 的文件"
    ]

    async def execute(self, pattern: str, search_path: str = ".", **kwargs) -> SkillResult:
        """执行文件搜索"""
        try:
            import glob
            import os

            # 构建搜索路径
            full_pattern = os.path.join(search_path, "**", pattern)

            # 递归搜索
            matches = glob.glob(full_pattern, recursive=True)

            return SkillResult(
                success=True,
                data={
                    "pattern": pattern,
                    "matches": matches[:100],  # 限制返回数量
                    "count": len(matches)
                }
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"搜索错误: {str(e)}"
            )


class WebSearchSkill(Skill):
    """网络搜索技能"""

    name = "web_search"
    description = "搜索网络获取信息，支持网页搜索"
    permission_level = SkillPermission.SENSITIVE
    examples = [
        "搜索 Python 异步编程教程",
        "查找最新 AI 新闻"
    ]

    async def execute(self, query: str, **kwargs) -> SkillResult:
        """执行网络搜索"""
        try:
            # 尝试使用 MCP web-search 服务
            from mcp_web_search_prime import web_search

            result = await web_search(
                search_query=query,
                content_size="medium"
            )

            return SkillResult(
                success=True,
                data={
                    "query": query,
                    "results": result
                }
            )
        except ImportError:
            # 如果 MCP 不可用，返回提示
            return SkillResult(
                success=False,
                error="Web search 需要配置 MCP 服务器"
            )


class SystemInfoSkill(Skill):
    """系统信息技能"""

    name = "system_info"
    description = "获取系统信息，如 CPU、内存、磁盘使用情况"
    permission_level = SkillPermission.NORMAL
    examples = [
        "查看系统信息",
        "检查内存使用"
    ]

    async def execute(self, info_type: str = "all", **kwargs) -> SkillResult:
        """获取系统信息"""
        try:
            import psutil
            import platform

            data = {}

            if info_type in ["all", "cpu"]:
                data["cpu_percent"] = psutil.cpu_percent(interval=1)
                data["cpu_count"] = psutil.cpu_count()

            if info_type in ["all", "memory"]:
                memory = psutil.virtual_memory()
                data["memory_percent"] = memory.percent
                data["memory_used_gb"] = round(memory.used / (1024**3), 2)
                data["memory_total_gb"] = round(memory.total / (1024**3), 2)

            if info_type in ["all", "disk"]:
                disk = psutil.disk_usage('/')
                data["disk_percent"] = disk.percent
                data["disk_used_gb"] = round(disk.used / (1024**3), 2)
                data["disk_total_gb"] = round(disk.total / (1024**3), 2)

            data["platform"] = platform.system()
            data["hostname"] = platform.node()

            return SkillResult(
                success=True,
                data=data
            )
        except ImportError:
            return SkillResult(
                success=False,
                error="需要安装 psutil: pip install psutil"
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"获取系统信息错误: {str(e)}"
            )
