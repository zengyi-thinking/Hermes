"""
Refiner Agent - 指令优化器

将用户的模糊语音输入转化为精确的技术 Prompt
"""
import re
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass

from ..llm.base import LLMClientProtocol
from ..state.schemas import HermesState, RefinedResult


# 常见错别字和技术术语纠正映射
TERM_CORRECTIONS = {
    # 编程语言
    r'\bpythn?\b': 'Python',
    r'\bjavascirpt\b': 'JavaScript',
    r'\btypescirpt\b': 'TypeScript',
    r'\bruby\b': 'Ruby',
    r'\bgo\b': 'Go',
    r'\bgolang\b': 'Go',

    # 框架和库
    r'\breact\b': 'React',
    r'\bvant?\b': 'Vue',
    r'\banguar\b': 'Angular',
    r'\bnextjs\b': 'Next.js',
    r'\bnestjs\b': 'NestJS',
    r'\bdjangor\b': 'Django',
    r'\bflask\b': 'Flask',
    r'\bfastapi\b': 'FastAPI',

    # 数据库
    r'\bpsql\b': 'PostgreSQL',
    r'\bmysql\b': 'MySQL',
    r'\bmongodb\b': 'MongoDB',
    r'\bredis\b': 'Redis',

    # 开发工具
    r'\bgits\b': 'git',
    r'\bnpms\b': 'npm',
    r'\byarn\b': 'yarn',
    r'\bdocker\b': 'Docker',
    r'\bk8s\b': 'Kubernetes',
    r'\bkuberentes\b': 'Kubernetes',

    # 概念
    r'\bai\b': 'AI',
    r'\bllm\b': 'LLM',
    r'\bapi\b': 'API',
    r'\bsdk\b': 'SDK',
    r'\buuid\b': 'UUID',
    r'\buuid\b': 'UUID',
    r'\bid\b': 'ID',

    # 常见拼写错误
    r'\benviroment\b': 'environment',
    r'\bconfig\b': 'config',
    r'\bparam\b': 'parameter',
    r'\bargs\b': 'arguments',
    r'\breturn\b': 'return',
    r'\brequires\b': 'requires',
}

# 口语化表达转换
COLLOQUIAL_TO_FORMAL = {
    r'搞一下': '实现',
    r'弄一下': '修改',
    r'看一下': '查看',
    r'调一下': '调试',
    r'加一下': '添加',
    r'改一下': '修改',
    r'删一下': '删除',
    r'跑一下': '运行',
    r'测试一下': '测试',
    r'那个': '',
    r'这个': '',
}


@dataclass
class RefinerConfig:
    """Refiner 配置"""
    system_prompt_path: str = "config/prompts/refiner_system.txt"
    context_prompt_path: str = "config/prompts/refiner_context.txt"
    min_confidence: float = 0.6
    enable_correction: bool = True


class RefinerAgent:
    """
    Refiner Agent - 指令优化器

    职责：
    1. 纠正错别字和语法错误
    2. 推断用户意图
    3. 结合上下文生成精确的技术 Prompt
    4. 生成后续执行步骤建议
    """

    def __init__(
        self,
        llm_client: LLMClientProtocol,
        config: RefinerConfig = None
    ):
        """
        初始化 Refiner Agent

        Args:
            llm_client: LLM 客户端
            config: 配置
        """
        self.llm_client = llm_client
        self.config = config or RefinerConfig()

        # 加载 Prompt 模板
        self.system_prompt = self._load_prompt(self.config.system_prompt_path)
        self.context_prompt_template = self._load_prompt(self.config.context_prompt_path)

    def _load_prompt(self, path: str) -> str:
        """加载 Prompt 文件"""
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ""

    def refine(self, raw_prompt: str, state: HermesState) -> RefinedResult:
        """
        优化原始指令

        Args:
            raw_prompt: 用户原始指令
            state: 当前系统状态

        Returns:
            RefinedResult: 优化结果
        """
        # Step 1: 文本预处理
        normalized_prompt = self._normalize_text(raw_prompt)

        # Step 2: 构建上下文
        context = self._build_context(state)

        # Step 3: 构建完整 Prompt
        full_prompt = self._build_refiner_prompt(normalized_prompt, context)

        # Step 4: 调用 LLM 优化（同步调用）
        response = self.llm_client.complete(
            system_prompt=self.system_prompt,
            user_prompt=full_prompt,
            temperature=0.3
        )

        # Step 5: 解析结果
        result = self._parse_response(response.content if hasattr(response, 'content') else str(response), raw_prompt)

        return result

    def _normalize_text(self, text: str) -> str:
        """
        文本规范化

        处理：
        - 常见错别字自动纠正
        - 口语化表达转书面语
        - 移除多余空白
        - 统一术语
        """
        normalized = text

        # 应用术语纠正
        for pattern, correction in TERM_CORRECTIONS.items():
            normalized = re.sub(
                pattern, correction, normalized,
                flags=re.IGNORECASE
            )

        # 应用口语化转换
        for pattern, correction in COLLOQUIAL_TO_FORMAL.items():
            normalized = normalized.replace(pattern, correction)

        # 移除多余空白
        normalized = ' '.join(normalized.split())

        # 移除常见的前缀
        prefixes = [
            r'^claude\s*[,:]?\s*',
            r'^帮我\s*',
            r'^请\s*',
            r'^帮我把\s*',
        ]
        for prefix in prefixes:
            normalized = re.sub(prefix, '', normalized, flags=re.IGNORECASE)

        return normalized.strip()

    def _build_context(self, state: HermesState) -> str:
        """构建上下文信息"""
        context_parts = []

        # 系统状态
        context_parts.append(f"当前系统状态: {state.last_status}")

        # 错误历史
        if state.last_error:
            context_parts.append(f"最近错误: {state.last_error}")
            if state.last_error_timestamp:
                context_parts.append(f"错误时间: {state.last_error_timestamp.isoformat()}")

        # 文件变更历史（最近 5 个）
        if state.modified_files:
            recent_files = state.modified_files[-5:]
            file_list = ", ".join([
                f"[{f.change_type}] {f.file_path}"
                for f in recent_files
            ])
            context_parts.append(f"最近文件变更: {file_list}")

        # 项目上下文
        if state.project_context:
            context_parts.append(
                f"项目上下文: {json.dumps(state.project_context, ensure_ascii=False)}"
            )

        # 任务统计
        context_parts.append(
            f"任务统计: 完成 {state.completed_tasks_count}, "
            f"失败 {state.failed_tasks_count}, "
            f"待处理 {len(state.task_queue)}"
        )

        return "\n".join(context_parts)

    def _build_refiner_prompt(
        self,
        normalized_prompt: str,
        context: str
    ) -> str:
        """构建 Refiner 的完整 Prompt"""
        from datetime import datetime

        return self.context_prompt_template.format(
            user_prompt=normalized_prompt,
            context=context,
            timestamp=datetime.now().isoformat()
        )

    def _parse_response(
        self,
        response: str,
        original_prompt: str
    ) -> RefinedResult:
        """解析 LLM 返回的结果"""
        # 清理响应
        cleaned_response = self._clean_response(response)

        try:
            # 尝试解析 JSON
            data = json.loads(cleaned_response)

            result = RefinedResult(
                refined_prompt=data.get("refined_prompt", ""),
                clarifications=data.get("clarifications", []),
                suggested_steps=data.get("suggested_steps", []),
                confidence=float(data.get("confidence", 0.5)),
                intent_type=data.get("intent_type", "other"),
                reasoning=data.get("reasoning", ""),
                original_prompt=original_prompt
            )

        except (json.JSONDecodeError, ValueError, KeyError):
            # 如果不是 JSON，使用原始响应
            result = RefinedResult(
                refined_prompt=cleaned_response,
                clarifications=[],
                suggested_steps=[],
                confidence=0.5,
                intent_type="other",
                reasoning="非 JSON 格式响应，直接使用原始响应",
                original_prompt=original_prompt
            )

        return result

    def _clean_response(self, response: str) -> str:
        """清理 LLM 响应"""
        # 移除 markdown 代码块标记
        cleaned = re.sub(r'^```json\s*', '', response, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^```\s*', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE)

        return cleaned.strip()

    def quick_refine(self, raw_prompt: str) -> str:
        """
        快速优化（不调用 LLM，仅本地处理）

        适用于简单的错别字纠正
        """
        normalized = self._normalize_text(raw_prompt)

        # 如果 normalized 变化明显，返回规范化后的版本
        if normalized != raw_prompt:
            return normalized

        return raw_prompt
