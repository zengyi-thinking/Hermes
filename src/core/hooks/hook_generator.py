"""
Claude Code 钩子系统
生成和管理 Claude CLI 钩子配置
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import json


@dataclass
class HookConfig:
    """钩子配置"""
    hook_type: str  # "command" | "http"
    command: str = ""  # 命令类型使用
    http_url: str = ""  # HTTP 类型使用
    timeout: int = 60
    matchers: Dict[str, List[str]] = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "type": self.hook_type,
            "command": self.command,
            "httpUrl": self.http_url,
            "timeout": self.timeout,
            "matchers": self.matchers,
            "enabled": self.enabled
        }


@dataclass
class HookEntry:
    """钩子条目"""
    name: str
    description: str
    hook: HookConfig
    priority: int = 0
    category: str = "general"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "hook": self.hook.to_dict(),
            "priority": self.priority,
            "category": self.category
        }


class HookGenerator:
    """Claude Code 钩子配置生成器"""

    def __init__(self, project_root: str = "."):
        """
        初始化钩子生成器

        Args:
            project_root: 项目根目录
        """
        self._project_root = Path(project_root)
        self._hooks_dir = self._project_root / ".claude" / "hooks"
        self._hooks_dir.mkdir(parents=True, exist_ok=True)
        self._hooks: List[HookEntry] = []

    def add_hook(self, entry: HookEntry):
        """添加钩子"""
        self._hooks.append(entry)

    def remove_hook(self, name: str) -> bool:
        """移除钩子"""
        for i, hook in enumerate(self._hooks):
            if hook.name == name:
                self._hooks.pop(i)
                return True
        return False

    def get_hooks(self) -> List[HookEntry]:
        """获取所有钩子"""
        return sorted(self._hooks, key=lambda x: x.priority, reverse=True)

    def generate_hooks_json(self) -> dict:
        """
        生成 .claude/hooks.json 配置

        Returns:
            钩子配置字典
        """
        hooks_by_type: Dict[str, List[Dict]] = {
            "PreTaskValidation": [],
            "PostToolUse": [],
            "TaskComplete": [],
            "PostExecutorComplete": []
        }

        for entry in self.get_hooks():
            hook_data = {
                "name": entry.name,
                "description": entry.description,
                **entry.hook.to_dict()
            }

            # 根据类别添加到对应类型
            if "pre" in entry.category.lower() and "validation" in entry.category.lower():
                hooks_by_type["PreTaskValidation"].append(hook_data)
            elif "post" in entry.category.lower() and "task" in entry.category.lower():
                hooks_by_type["TaskComplete"].append(hook_data)
            elif "tool" in entry.category.lower():
                hooks_by_type["PostToolUse"].append(hook_data)
            else:
                hooks_by_type["TaskComplete"].append(hook_data)

        # 构建完整的 hooks.json 结构
        config: Dict[str, Any] = {
            "version": 1,
            "hooks": {}
        }

        for hook_type, hooks_list in hooks_by_type.items():
            if hooks_list:
                config["hooks"][hook_type] = hooks_list

        return config

    def save_hooks_json(self, output_path: Path = None) -> Path:
        """
        保存钩子配置到文件

        Args:
            output_path: 输出路径

        Returns:
            文件路径
        """
        if output_path is None:
            output_path = self._hooks_dir / "hooks.json"

        config = self.generate_hooks_json()

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return output_path

    def generate_hook_script(
        self,
        hook_name: str,
        script_content: str,
        language: str = "python"
    ) -> Path:
        """
        生成钩子脚本

        Args:
            hook_name: 钩子名称
            script_content: 脚本内容
            language: 脚本语言

        Returns:
            脚本文件路径
        """
        ext_map = {
            "python": ".py",
            "bash": ".sh",
            "javascript": ".js"
        }

        ext = ext_map.get(language, ".sh")
        script_path = self._hooks_dir / f"{hook_name}{ext}"

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)

        # 设置执行权限（Unix 系统）
        import os
        os.chmod(script_path, 0o755)

        return script_path

    def get_predefined_hooks(self) -> List[HookEntry]:
        """获取预定义的钩子列表"""
        return [
            # PostTaskValidation - 任务完成后验证
            HookEntry(
                name="generate_report",
                description="生成任务报告",
                hook=HookConfig(
                    hook_type="command",
                    command="python ${CLAUDE_PROJECT_ROOT}/.claude/hooks/generate_report.py",
                    timeout=120,
                    matchers={}
                ),
                priority=10,
                category="PostTaskValidation"
            ),

            # PostToolUse - 文件变更后记录
            HookEntry(
                name="file_change_logger",
                description="记录文件变更",
                hook=HookConfig(
                    hook_type="command",
                    command="python ${CLAUDE_PROJECT_ROOT}/.claude/hooks/file_change_logger.py",
                    timeout=30,
                    matchers={
                        "matcher": ["Write", "Edit"]
                    }
                ),
                priority=5,
                category="PostToolUse"
            ),

            # PostToolUse - 代码格式化检查
            HookEntry(
                name="format_check",
                description="检查代码格式",
                hook=HookConfig(
                    hook_type="command",
                    command="python ${CLAUDE_PROJECT_ROOT}/.claude/hooks/format_check.py",
                    timeout=60,
                    matchers={
                        "matcher": ["Write", "Edit"]
                    }
                ),
                priority=1,
                category="PostToolUse"
            ),
        ]

    def install_predefined_hooks(self) -> List[Path]:
        """
        安装预定义钩子

        Returns:
            安装的文件路径列表
        """
        installed_files = []

        # 添加预定义钩子
        for hook in self.get_predefined_hooks():
            self.add_hook(hook)

        # 保存钩子配置
        hooks_path = self.save_hooks_json()
        installed_files.append(hooks_path)

        # 生成必要的钩子脚本
        self._generate_hook_scripts()
        for script_path in self._hooks_dir.glob("*.py"):
            installed_files.append(script_path)

        return installed_files

    def _generate_hook_scripts(self):
        """生成默认的钩子脚本"""
        # generate_report.py
        report_script = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
任务完成后自动生成报告
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# 读取 Claude 提供的上下文
task_context = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

# 生成报告逻辑
report_path = Path(".claude/hooks/output") / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
report_path.parent.mkdir(parents=True, exist_ok=True)

report_data = {
    "timestamp": datetime.now().isoformat(),
    "task": task_context.get("task", {}),
    "output": task_context.get("output", "")
}

with open(report_path, 'w', encoding='utf-8') as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2)

print(f"报告已生成: {report_path}")
'''

        self.generate_hook_script("generate_report", report_script, "python")

        # file_change_logger.py
        logger_script = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
记录文件变更到项目日志
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# 读取变更信息
change_info = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

# 记录到变更日志
log_path = Path(".claude/hooks/file_changes.log")
with open(log_path, 'a', encoding='utf-8') as f:
    f.write(f"[{datetime.now().isoformat()}] {json.dumps(change_info, ensure_ascii=False)}\\n")

print("文件变更已记录")
'''

        self.generate_hook_script("file_change_logger", logger_script, "python")

        # format_check.py
        format_script = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
代码格式检查
"""

import sys
import subprocess

# 读取文件路径
files = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []

for file_path in files:
    if file_path.endswith('.py'):
        try:
            # 使用 Black 检查格式
            result = subprocess.run(
                ["black", "--check", file_path],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"格式问题: {file_path}")
                print(result.stdout)
        except FileNotFoundError:
            pass  # Black 未安装，跳过检查

print("格式检查完成")
'''

        self.generate_hook_script("format_check", format_script, "python")


class HookManager:
    """钩子管理器"""

    def __init__(self, project_root: str = "."):
        """
        初始化钩子管理器

        Args:
            project_root: 项目根目录
        """
        self._project_root = Path(project_root)
        self._generator = HookGenerator(project_root)

    def install_all(self) -> bool:
        """
        安装所有钩子

        Returns:
            是否成功
        """
        try:
            self._generator.install_predefined_hooks()
            return True
        except Exception:
            return False

    def list_hooks(self) -> List[Dict]:
        """列出所有已安装的钩子"""
        return [h.to_dict() for h in self._generator.get_hooks()]

    def disable_hook(self, name: str) -> bool:
        """禁用钩子"""
        for hook in self._generator.get_hooks():
            if hook.name == name:
                hook.hook.enabled = False
                self._generator.save_hooks_json()
                return True
        return False

    def enable_hook(self, name: str) -> bool:
        """启用钩子"""
        for hook in self._generator.get_hooks():
            if hook.name == name:
                hook.hook.enabled = True
                self._generator.save_hooks_json()
                return True
        return False

    def generate_hooks_json(self) -> dict:
        """生成钩子配置"""
        return self._generator.generate_hooks_json()

    def get_hook_script_path(self, hook_name: str) -> Optional[Path]:
        """获取钩子脚本路径"""
        script_path = self._generator._hooks_dir / f"{hook_name}.py"
        if script_path.exists():
            return script_path
        return None
