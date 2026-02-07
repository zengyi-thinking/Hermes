"""
计算器技能
"""

from ..base import Skill, SkillResult


class CalculatorSkill(Skill):
    """计算器技能"""

    name = "calculator"
    description = "执行数学计算，支持加减乘除、百分比、幂运算等"
    permission_level = "normal"

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
