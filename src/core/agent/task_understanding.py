"""
任务理解器 (Task Understanding Agent)

职责：
1. 分析用户原始提示词，结合最近任务历史进行上下文理解
2. 推断用户意图（NEW_TASK | CONTINUE | MODIFY | CANCEL | CLARIFICATION）
3. 判断是否需要中断当前任务
4. 返回结构化的任务理解结果
"""
import json
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from ..llm.base import LLMClientProtocol
from ..state.schemas import TaskInfo, TaskUnderstandingResult, IntentType


@dataclass
class UnderstandingConfig:
    """任务理解器配置"""
    system_prompt_path: str = "config/prompts/understanding_system.txt"
    max_context_tasks: int = 5  # 最多使用最近 N 个任务作为上下文
    min_confidence: float = 0.7  # 最小置信度阈值
    enable_interrupt_check: bool = True  # 是否启用中断检查


class TaskUnderstandingAgent:
    """
    任务理解器 - 意图推断

    在 Refiner 之前先分析用户意图，理解上下文
    """

    # 默认的系统提示词
    DEFAULT_SYSTEM_PROMPT = """你是 Hermes 任务理解器。你的职责是分析用户输入，结合上下文推断用户的真实意图。

## 任务类型判断
1. **NEW_TASK**: 用户提出了一个全新的任务，与之前的任务无直接关联
2. **CONTINUE**: 用户在继续/补充之前的任务（如"继续"、"还有"、"另外"）
3. **MODIFY**: 用户要修改当前正在执行的任务（如"改成"、"改为"、"换一种方式"）
4. **CANCEL**: 用户要取消当前任务（如"取消"、"停止"、"不用了"）
5. **CLARIFICATION**: 用户在澄清或询问问题
6. **CONFIRM**: 用户确认执行当前任务（如"好的"、"可以"、"开始吧"、"是"）

## 输出格式
请返回 JSON 格式的分析结果：
```json
{
    "intent_type": "new_task|continue|modify|cancel|clarification|confirm",
    "understanding": "对用户需求的简洁理解（1-2句话）",
    "should_interrupt": true/false,
    "context_summary": "相关上下文摘要",
    "confidence": 0.0-1.0,
    "suggested_questions": ["如果需要澄清的问题"]
}
```

## 判断规则
- 如果用户回复"好的"、"可以"、"开始吧"、"是"等确认词 → CONFIRM
- 如果当前有任务正在执行，且新任务是补充性质 → CONTINUE
- 如果当前有任务正在执行，且新任务完全不同 → 询问用户是否要中断
- 如果用户明确要求修改/取消 → MODIFY/CANCEL
- 如果用户请求模糊或不完整 → 返回 CLARIFICATION
"""

    def __init__(
        self,
        llm_client: LLMClientProtocol,
        config: UnderstandingConfig = None
    ):
        """
        初始化任务理解器

        Args:
            llm_client: LLM 客户端
            config: 配置
        """
        self.llm_client = llm_client
        self.config = config or UnderstandingConfig()
        self.system_prompt = self._load_prompt() or self.DEFAULT_SYSTEM_PROMPT

    def _load_prompt(self) -> Optional[str]:
        """加载自定义系统提示词"""
        try:
            from pathlib import Path
            p = Path(self.config.system_prompt_path)
            if p.exists():
                return p.read_text(encoding="utf-8")
        except Exception:
            pass
        return None

    def understand(
        self,
        raw_prompt: str,
        context_tasks: List[TaskInfo] = None,
        current_task: Optional[TaskInfo] = None
    ) -> TaskUnderstandingResult:
        """
        分析用户意图和任务需求

        Args:
            raw_prompt: 用户原始提示词
            context_tasks: 最近 N 个任务历史
            current_task: 当前正在执行的任务

        Returns:
            TaskUnderstandingResult: 包含意图类型、理解结果、是否中断等
        """
        # 1. 构建上下文提示词
        context_prompt = self._build_context_prompt(
            raw_prompt, context_tasks or [], current_task
        )

        # 2. 调用 LLM 进行分析
        response = self.llm_client.complete(
            system_prompt=self.system_prompt,
            user_prompt=context_prompt,
            temperature=0.3
        )

        # 3. 解析结果
        return self._parse_response(
            response.content if hasattr(response, 'content') else str(response),
            raw_prompt
        )

    def _build_context_prompt(
        self,
        raw_prompt: str,
        context_tasks: List[TaskInfo],
        current_task: Optional[TaskInfo]
    ) -> str:
        """构建包含上下文的用户提示词"""
        parts = ["## 用户输入", raw_prompt, ""]

        # 当前任务信息
        if current_task:
            parts.extend([
                "## 当前正在执行的任务",
                f"- 任务ID: {current_task.task_id}",
                f"- 任务内容: {current_task.original_prompt}",
                f"- 状态: {current_task.status}",
                ""
            ])

        # 最近任务历史
        if context_tasks:
            max_tasks = self.config.max_context_tasks
            recent_tasks = context_tasks[-max_tasks:]

            parts.append("## 最近任务历史")
            for i, task in enumerate(recent_tasks, 1):
                time_str = task.created_at.strftime("%Y-%m-%d %H:%M:%S") if task.created_at else "未知"
                parts.extend([
                    f"{i}. [{time_str}] {task.original_prompt[:100]}",
                    f"   状态: {task.status}, 置信度: {task.confidence:.0%}" if task.confidence else ""
                ])
            parts.append("")

        # 添加分析要求
        parts.extend([
            "## 分析要求",
            "请根据以上信息，分析用户的真实意图：",
            "1. 这是新任务还是对之前任务的补充/修改？",
            "2. 如果有当前任务，是否需要中断？",
            "3. 用户的核心需求是什么？"
        ])

        return "\n".join(parts)

    def _parse_response(
        self,
        response: str,
        original_prompt: str
    ) -> TaskUnderstandingResult:
        """解析 LLM 返回的结果"""
        cleaned = self._clean_response(response)

        try:
            data = json.loads(cleaned)

            # 验证 intent_type 有效性
            intent_type = data.get("intent_type", "new_task")
            valid_types = [t.value for t in IntentType]
            if intent_type not in valid_types:
                # 尝试映射
                intent_type_map = {
                    "continue": "continue",
                    "补充": "continue",
                    "继续": "continue",
                    "modify": "modify",
                    "修改": "modify",
                    "cancel": "cancel",
                    "取消": "cancel",
                    "clarification": "clarification",
                    "澄清": "clarification",
                    "confirm": "confirm",
                    "确认": "confirm",
                    "好的": "confirm",
                    "可以": "confirm",
                }
                intent_type = intent_type_map.get(intent_type.lower(), "new_task")

            return TaskUnderstandingResult(
                intent_type=intent_type,
                understanding=data.get("understanding", ""),
                should_interrupt=bool(data.get("should_interrupt", False)),
                context_summary=data.get("context_summary", ""),
                related_task_id=data.get("related_task_id"),
                confidence=float(data.get("confidence", 0.7)),
                suggested_questions=data.get("suggested_questions", [])
            )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # 解析失败时的默认结果
            return self._fallback_result(original_prompt, str(e))

    def _clean_response(self, response: str) -> str:
        """清理 LLM 响应"""
        import re
        # 移除 markdown 代码块标记
        cleaned = re.sub(r'^```json\s*', '', response, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^```\s*', '', cleaned, flags=re.MULTILINE)
        return cleaned.strip()

    def _fallback_result(
        self,
        original_prompt: str,
        error: str
    ) -> TaskUnderstandingResult:
        """解析失败时的默认结果"""
        # 基于关键词简单判断意图
        prompt_lower = original_prompt.lower()

        # CLARIFICATION 优先检查（问句特征最强）
        if any(kw in prompt_lower for kw in ['?', '？', '什么', '如何', '怎么', 'why', 'how', '是不是', '是否']):
            intent = "clarification"
        # 确认意图
        elif any(kw in prompt_lower for kw in ['好的', '可以', '开始吧', '执行吧', '是', 'yes', 'ok', 'okay', '确认']):
            intent = "confirm"
        elif any(kw in prompt_lower for kw in ['取消', '停止', '不用', 'cancel', 'stop']):
            intent = "cancel"
        elif any(kw in prompt_lower for kw in ['继续', '还有', '另外', '并且']):
            intent = "continue"
        elif any(kw in prompt_lower for kw in ['改成', '改为', '改一下', '修改', '换一种']):
            intent = "modify"
        else:
            intent = "new_task"

        return TaskUnderstandingResult(
            intent_type=intent,
            understanding=f"用户发送了: {original_prompt[:100]}",
            should_interrupt=False,
            context_summary="解析失败，使用关键词推断",
            confidence=0.5,
            suggested_questions=[]
        )

    def quick_understand(self, raw_prompt: str) -> str:
        """
        快速意图识别（不调用 LLM）

        基于关键词的简单判断，适用于简单场景
        """
        prompt_lower = raw_prompt.lower()

        # CLARIFICATION 优先检查（问句特征最强）
        if '?' in raw_prompt or '？' in raw_prompt:
            return "clarification"

        # 确认意图
        if any(kw in prompt_lower for kw in ['好的', '可以', '开始吧', '执行吧', '是', 'yes', 'ok', 'okay', '确认']):
            return "confirm"
        elif any(kw in prompt_lower for kw in ['取消', '停止', '不用', 'cancel', 'stop']):
            return "cancel"
        elif any(kw in prompt_lower for kw in ['继续', '还有', '另外', '并且']):
            return "continue"
        elif any(kw in prompt_lower for kw in ['改成', '改为', '改一下', '修改']):
            return "modify"
        else:
            return "new_task"
