"""
任务文档生成器
生成 Markdown 格式的任务记录文档
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
import os


@dataclass
class TaskDocInfo:
    """任务文档信息"""
    task_id: str
    original_prompt: str
    refined_prompt: str = ""
    intent_type: str = "new_task"
    confidence: float = 0.0

    # 时间信息
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime = None
    completed_at: datetime = None
    duration_seconds: float = 0.0

    # 状态
    status: str = "pending"  # pending, processing, completed, failed
    outcome: str = ""  # success, failed, cancelled

    # 执行信息
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0

    # 文件变更
    created_files: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)

    # 元数据
    sender: str = ""
    session_id: str = ""
    error: str = ""
    clarifications: List[str] = field(default_factory=list)
    suggested_steps: List[str] = field(default_factory=list)

    # 相关记忆
    related_memories: List[Dict] = field(default_factory=list)
    key_learning: str = ""


class TaskDocGenerator:
    """任务文档生成器"""

    def __init__(
        self,
        tasks_dir: str = "./tasks",
        project_root: str = "."
    ):
        """
        初始化任务文档生成器

        Args:
            tasks_dir: 任务文档目录
            project_root: 项目根目录
        """
        self._tasks_dir = Path(tasks_dir)
        self._project_root = Path(project_root)
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        task_info: TaskDocInfo,
        output_path: Path = None
    ) -> Path:
        """
        生成任务 Markdown 文档

        Args:
            task_info: 任务信息
            output_path: 输出路径（可选）

        Returns:
            文档路径
        """
        if output_path is None:
            output_path = self._generate_path(task_info.task_id)

        content = self._render_markdown(task_info)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return output_path

    def _generate_path(self, task_id: str) -> Path:
        """生成文档路径"""
        # 格式: tasks/task_YYYYMMDD_XXX.md
        date_prefix = datetime.now().strftime("%Y%m%d")
        task_num = task_id.split('_')[-1] if '_' in task_id else "001"

        # 如果任务 ID 包含日期，使用它
        if 'tg_' in task_id or 'email_' in task_id:
            # 从任务 ID 提取日期
            parts = task_id.split('_')
            if len(parts) >= 3:
                date_prefix = parts[1]

        filename = f"task_{date_prefix}_{task_num}.md"
        return self._tasks_dir / filename

    def _render_markdown(self, task_info: TaskDocInfo) -> str:
        """渲染 Markdown 内容"""
        # 格式化时间
        created_time = task_info.created_at.strftime("%Y-%m-%d %H:%M:%S")
        completed_time = task_info.completed_at.strftime("%Y-%m-%d %H:%M:%S") if task_info.completed_at else "N/A"
        duration = self._format_duration(task_info.duration_seconds)

        # 状态emoji
        status_emoji = {
            "completed": "✅",
            "failed": "❌",
            "cancelled": "⏸️",
            "pending": "⏳",
            "processing": "🔄"
        }
        status_icon = status_emoji.get(task_info.status, "📋")

        # 意图类型中文
        intent_map = {
            "new_task": "新任务",
            "continue": "继续/补充",
            "modify": "修改任务",
            "cancel": "取消任务",
            "clarification": "澄清问题",
            "confirm": "确认执行"
        }
        intent_cn = intent_map.get(task_info.intent_type, task_info.intent_type)

        # 结果emoji
        outcome_emoji = {
            "success": "✅ 完成",
            "failed": "❌ 失败",
            "cancelled": "⏸️ 已取消"
        }
        outcome_text = outcome_emoji.get(task_info.outcome, "⏳ 进行中")

        # 构建 Markdown
        lines = [
            f"# 任务: {task_info.task_id}",
            "",
            "## 基本信息",
            f"- **任务ID**: `{task_info.task_id}`",
            f"- **创建时间**: {created_time}",
            f"- **开始时间**: {task_info.started_at.strftime('%Y-%m-%d %H:%M:%S') if task_info.started_at else 'N/A'}",
            f"- **完成时间**: {completed_time}",
            f"- **执行时间**: {duration}",
            f"- **状态**: {status_icon} {task_info.status.upper()}",
            f"- **结果**: {outcome_text}",
            f"- **意图类型**: {intent_cn}",
            f"- **置信度**: {task_info.confidence:.0%}",
            f"- **发送者**: {task_info.sender or 'Unknown'}",
            f"- **会话ID**: `{task_info.session_id or 'N/A'}`",
            "",
            "## 原始需求",
            f"> {task_info.original_prompt}",
            "",
        ]

        # 优化后的任务（如果有）
        if task_info.refined_prompt:
            lines.extend([
                "## 优化后的任务",
                f"> {task_info.refined_prompt}",
                "",
            ])

        # 建议步骤（如果有）
        if task_info.suggested_steps:
            lines.extend([
                "## 执行步骤",
            ])
            for i, step in enumerate(task_info.suggested_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        # 澄清问题（如果有）
        if task_info.clarifications:
            lines.extend([
                "## 澄清问题",
            ])
            for i, q in enumerate(task_info.clarifications, 1):
                lines.append(f"{i}. {q}")
            lines.append("")

        # 文件变更
        total_files = len(task_info.created_files) + len(task_info.modified_files) + len(task_info.deleted_files)
        if total_files > 0:
            lines.extend([
                "## 文件变更",
                f"| 文件 | 操作 | 说明 |",
                f"|------|------|------|",
            ])
            for f in task_info.created_files:
                lines.append(f"| `{f}` | 🆕 创建 | |")
            for f in task_info.modified_files:
                lines.append(f"| `{f}` | ✏️ 修改 | |")
            for f in task_info.deleted_files:
                lines.append(f"| `{f}` | 🗑️ 删除 | |")
            lines.append("")

        # 执行结果
        lines.append("## 执行结果")
        lines.append(f"- **退出码**: `{task_info.exit_code}`")
        lines.append(f"- **执行时间**: {duration}")
        lines.append("")

        # 标准输出
        if task_info.stdout:
            lines.append("### 标准输出")
            lines.append("```")
            lines.append(task_info.stdout[:5000])  # 限制长度
            if len(task_info.stdout) > 5000:
                lines.append("... (输出过长，已截断)")
            lines.append("```")
            lines.append("")

        # 标准错误
        if task_info.stderr:
            lines.append("### 标准错误")
            lines.append("```")
            lines.append(task_info.stderr[:2000])  # 限制长度
            if len(task_info.stderr) > 2000:
                lines.append("... (输出过长，已截断)")
            lines.append("```")
            lines.append("")

        # 错误信息（如果有）
        if task_info.error:
            lines.extend([
                "### 错误信息",
                f"```",
                f"{task_info.error}",
                f"```",
                ""
            ])

        # 相关历史（如果有）
        if task_info.related_memories:
            lines.extend([
                "## 相关历史",
            ])
            for memory in task_info.related_memories[:5]:
                summary = memory.get("content", "")[:100]
                lines.append(f"- {summary}")
            lines.append("")

        # 经验总结
        if task_info.key_learning:
            lines.extend([
                "## 经验总结",
                f"> {task_info.key_learning}",
                ""
            ])

        # 元数据
        lines.extend([
            "---",
            "## 元数据",
            f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **文档版本**: 1.0",
        ])

        return "\n".join(lines)

    def _format_duration(self, seconds: float) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            mins = seconds // 60
            secs = seconds % 60
            return f"{int(mins)}分{int(secs)}秒"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{int(hours)}小时{int(mins)}分"


class ProjectDocUpdater:
    """项目文档更新器"""

    def __init__(self, project_root: str = "."):
        """
        初始化项目文档更新器

        Args:
            project_root: 项目根目录
        """
        self._project_root = Path(project_root)
        self._task_index_path = self._project_root / "TASK_LOG.md"

    def update_task_index(
        self,
        doc_path: Path,
        task_info: TaskDocInfo
    ) -> bool:
        """
        更新项目任务索引

        Args:
            doc_path: 任务文档路径
            task_info: 任务信息

        Returns:
            是否成功
        """
        try:
            # 读取现有索引
            if self._task_index_path.exists():
                with open(self._task_index_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = ""

            # 检查是否已存在
            rel_path = doc_path.relative_to(self._project_root)
            if str(rel_path) in content:
                return True  # 已存在

            # 构建新条目
            date = task_info.created_at.strftime("%Y-%m-%d")
            status_icon = "✅" if task_info.outcome == "success" else "❌"
            summary = task_info.original_prompt[:60] + "..." if len(task_info.original_prompt) > 60 else task_info.original_prompt

            entry = f"- {date} | {status_icon} [{task_info.task_id}]({rel_path}) | {summary}\n"

            # 如果文件为空，创建表头
            if not content:
                content = "# 任务日志\n\n| 日期 | 状态 | 任务 | 描述 |\n|------|------|------|-------|\n"

            # 找到表格末尾，插入新行
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('|') and '---' in line:
                    # 在表头后插入
                    lines.insert(i + 1, entry)
                    break
            else:
                # 没有表头，直接追加
                lines.append(entry)

            content = '\n'.join(lines)

            with open(self._task_index_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return True

        except Exception:
            return False


def create_task_doc_from_result(
    task_id: str,
    original_prompt: str,
    refined_prompt: str,
    exec_result,
    task_info = None,
    tasks_dir: str = "./tasks",
    project_root: str = "."
) -> Path:
    """
    从执行结果创建任务文档（便捷函数）

    Args:
        task_id: 任务 ID
        original_prompt: 原始提示
        refined_prompt: 优化后的提示
        exec_result: 执行结果
        task_info: 原始任务信息
        tasks_dir: 任务文档目录
        project_root: 项目根目录

    Returns:
        文档路径
    """
    from datetime import datetime

    # 创建任务文档信息
    doc_info = TaskDocInfo(
        task_id=task_id,
        original_prompt=original_prompt,
        refined_prompt=refined_prompt,
        completed_at=datetime.now()
    )

    if hasattr(exec_result, 'success'):
        doc_info.status = "completed"
        doc_info.outcome = "success" if exec_result.success else "failed"

    if hasattr(exec_result, 'stdout'):
        doc_info.stdout = exec_result.stdout
    if hasattr(exec_result, 'stderr'):
        doc_info.stderr = exec_result.stderr
    if hasattr(exec_result, 'exit_code'):
        doc_info.exit_code = exec_result.exit_code
    if hasattr(exec_result, 'duration'):
        doc_info.duration_seconds = exec_result.duration
    if hasattr(exec_result, 'created_files'):
        doc_info.created_files = exec_result.created_files
    if hasattr(exec_result, 'modified_files'):
        doc_info.modified_files = exec_result.modified_files

    if task_info:
        doc_info.created_at = getattr(task_info, 'created_at', datetime.now())
        doc_info.started_at = getattr(task_info, 'started_at', None)
        doc_info.sender = getattr(task_info, 'sender', '')
        doc_info.session_id = getattr(task_info, 'session_id', '')
        doc_info.confidence = getattr(task_info, 'confidence', 0.0)
        doc_info.error = getattr(task_info, 'error', '')

    # 生成文档
    generator = TaskDocGenerator(tasks_dir=tasks_dir, project_root=project_root)
    doc_path = generator.generate(doc_info)

    # 更新项目索引
    updater = ProjectDocUpdater(project_root=project_root)
    updater.update_task_index(doc_path, doc_info)

    return doc_path
