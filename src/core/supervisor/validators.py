"""
输出验证器模块
提供多种输出验证功能：正则验证、文件存在验证、JSON格式验证等
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Pattern
import re
import json
from pathlib import Path


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "message": self.message,
            "details": self.details
        }


class OutputValidator(ABC):
    """输出验证基类"""

    @abstractmethod
    def validate(self, output: str) -> ValidationResult:
        """
        验证输出

        Args:
            output: 要验证的输出文本

        Returns:
            ValidationResult: 验证结果
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """验证器名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """验证器描述"""
        pass


class RegexValidator(OutputValidator):
    """正则表达式验证器"""

    def __init__(
        self,
        pattern: str,
        required: bool = True,
        flags: int = 0,
        name: str = "regex_validator",
        description: str = "正则表达式验证"
    ):
        """
        初始化正则验证器

        Args:
            pattern: 正则表达式模式
            required: 输出是否必须匹配
            flags: 正则 flags (re.IGNORECASE, re.MULTILINE 等)
            name: 验证器名称
            description: 验证器描述
        """
        self._pattern = pattern
        self._required = required
        self._flags = flags
        self._compiled: Optional[Pattern] = re.compile(pattern, flags)
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def validate(self, output: str) -> ValidationResult:
        """验证输出是否匹配正则表达式"""
        if not output:
            if self._required:
                return ValidationResult(
                    is_valid=False,
                    message="输出为空",
                    details={"pattern": self._pattern, "required": True}
                )
            return ValidationResult(
                is_valid=True,
                message="输出为空但非必需",
                details={"pattern": self._pattern, "required": False}
            )

        match = self._compiled.search(output)
        is_valid = match is not None

        message = "验证通过" if is_valid else f"输出不匹配模式: {self._pattern}"

        return ValidationResult(
            is_valid=is_valid,
            message=message,
            details={
                "pattern": self._pattern,
                "required": self._required,
                "matched": is_valid,
                "match_position": (match.start(), match.end()) if match else None
            }
        )


class FileExistsValidator(OutputValidator):
    """文件存在验证器"""

    def __init__(
        self,
        required_patterns: List[str] = None,
        work_dir: str = ".",
        name: str = "file_exists_validator",
        description: str = "文件存在验证"
    ):
        """
        初始化文件存在验证器

        Args:
            required_patterns: 必须存在的文件/目录模式列表
            work_dir: 工作目录
            name: 验证器名称
            description: 验证器描述
        """
        self._required_patterns = required_patterns or []
        self._work_dir = Path(work_dir)
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def validate(self, output: str) -> ValidationResult:
        """验证输出中提到的文件是否实际存在"""
        if not output:
            return ValidationResult(
                is_valid=len(self._required_patterns) == 0,
                message="无文件需要验证" if not self._required_patterns else "输出为空",
                details={"checked": 0, "found": 0, "missing": len(self._required_patterns)}
            )

        # 从输出中提取文件路径
        file_patterns = self._extract_file_paths(output)

        # 添加必需的文件模式
        all_patterns = set(self._required_patterns) | set(file_patterns)

        existing = []
        missing = []

        for pattern in all_patterns:
            path = self._work_dir / pattern
            if path.exists():
                existing.append(str(path))
            else:
                missing.append(str(path))

        is_valid = len(missing) == 0

        return ValidationResult(
            is_valid=is_valid,
            message="所有文件存在" if is_valid else f"缺少 {len(missing)} 个文件",
            details={
                "checked": len(all_patterns),
                "found": len(existing),
                "missing": missing,
                "existing": existing
            }
        )

    def _extract_file_paths(self, output: str) -> List[str]:
        """从输出中提取文件路径"""
        # 匹配常见的文件路径模式
        patterns = [
            r'[Cc]reated\s+[\'"]?([^\s\'"\'")]+\.[a-zA-Z0-9_]+[\'"]?',
            r'[Ww]rote\s+to\s+([^\s]+)',
            r'[Mm]odified\s+([^\s]+)',
            r'[Nn]ew\s+file[:\s]+([^\s]+)',
        ]

        files = []
        for pattern in patterns:
            matches = re.findall(pattern, output)
            for match in matches:
                file_path = match.strip().strip("'\"")
                if file_path and not file_path.startswith('http'):
                    files.append(file_path)

        return list(dict.fromkeys(files))


class JSONValidator(OutputValidator):
    """JSON 格式验证器"""

    def __init__(
        self,
        required_fields: List[str] = None,
        strict: bool = False,
        name: str = "json_validator",
        description: str = "JSON 格式验证"
    ):
        """
        初始化 JSON 验证器

        Args:
            required_fields: 必须存在的字段列表
            strict: 是否严格模式（输出必须全部是 JSON）
            name: 验证器名称
            description: 验证器描述
        """
        self._required_fields = required_fields or []
        self._strict = strict
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def validate(self, output: str) -> ValidationResult:
        """验证输出是否为有效的 JSON 格式"""
        if not output:
            return ValidationResult(
                is_valid=False,
                message="输出为空",
                details={"error": "empty_output"}
            )

        # 尝试解析 JSON
        try:
            # 尝试提取 JSON 代码块
            json_text = self._extract_json(output)
            if not json_text:
                if self._strict:
                    return ValidationResult(
                        is_valid=False,
                        message="输出中未找到 JSON",
                        details={"error": "no_json_found"}
                    )
                # 尝试直接解析整个输出
                json_text = output.strip()

            data = json.loads(json_text)

            # 验证必需字段
            if self._required_fields:
                missing = []
                for field in self._required_fields:
                    if field not in data:
                        missing.append(field)

                is_valid = len(missing) == 0
                message = "JSON 验证通过" if is_valid else f"缺少必需字段: {', '.join(missing)}"

                return ValidationResult(
                    is_valid=is_valid,
                    message=message,
                    details={
                        "valid_json": True,
                        "required_fields": self._required_fields,
                        "missing_fields": missing,
                        "found_fields": list(data.keys()) if isinstance(data, dict) else []
                    }
                )

            return ValidationResult(
                is_valid=True,
                message="有效的 JSON 格式",
                details={
                    "valid_json": True,
                    "data_type": type(data).__name__
                }
            )

        except json.JSONDecodeError as e:
            return ValidationResult(
                is_valid=False,
                message=f"JSON 解析错误: {str(e)}",
                details={
                    "valid_json": False,
                    "error": str(e)
                }
            )

    def _extract_json(self, output: str) -> str:
        """从输出中提取 JSON 代码块"""
        # 匹配 ```json ... ``` 或 ``` ... ```
        json_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
        matches = re.findall(json_block_pattern, output, re.DOTALL)

        if matches:
            return matches[0].strip()

        # 匹配首尾的 { ... }
        output = output.strip()
        if output.startswith('{') and output.endswith('}'):
            return output

        # 匹配首尾的 [ ... ]
        if output.startswith('[') and output.endswith(']'):
            return output

        return ""


class CompositeValidator(OutputValidator):
    """组合验证器"""

    def __init__(
        self,
        validators: List[OutputValidator],
        require_all: bool = True,
        name: str = "composite_validator",
        description: str = "组合验证"
    ):
        """
        初始化组合验证器

        Args:
            validators: 验证器列表
            require_all: 是否所有验证都通过才算成功
            name: 验证器名称
            description: 验证器描述
        """
        self._validators = validators
        self._require_all = require_all
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._description} ({len(self._validators)} 个验证器)"

    def validate(self, output: str) -> ValidationResult:
        """执行所有验证器验证"""
        results = []
        for validator in self._validators:
            result = validator.validate(output)
            results.append({
                "validator": validator.name,
                "is_valid": result.is_valid,
                "message": result.message,
                "details": result.details
            })

        if self._require_all:
            is_valid = all(r["is_valid"] for r in results)
            failed = [r["validator"] for r in results if not r["is_valid"]]
            message = "所有验证通过" if is_valid else f"验证失败: {', '.join(failed)}"
        else:
            is_valid = any(r["is_valid"] for r in results)
            passed = [r["validator"] for r in results if r["is_valid"]]
            message = f"至少一个验证通过: {', '.join(passed)}" if is_valid else "无验证通过"

        return ValidationResult(
            is_valid=is_valid,
            message=message,
            details={
                "validators_count": len(self._validators),
                "results": results,
                "require_all": self._require_all
            }
        )


class KeywordValidator(OutputValidator):
    """关键词存在验证器"""

    def __init__(
        self,
        required_keywords: List[str],
        forbidden_keywords: List[str] = None,
        case_sensitive: bool = False,
        name: str = "keyword_validator",
        description: str = "关键词验证"
    ):
        """
        初始化关键词验证器

        Args:
            required_keywords: 必须包含的关键词列表
            forbidden_keywords: 禁止包含的关键词列表
            case_sensitive: 是否大小写敏感
            name: 验证器名称
            description: 验证器描述
        """
        self._required_keywords = required_keywords
        self._forbidden_keywords = forbidden_keywords or []
        self._case_sensitive = case_sensitive
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def validate(self, output: str) -> ValidationResult:
        """验证输出是否包含必需关键词且不包含禁止关键词"""
        if not output:
            return ValidationResult(
                is_valid=False,
                message="输出为空",
                details={"error": "empty_output"}
            )

        search_output = output if self._case_sensitive else output.lower()

        # 检查必需关键词
        missing_keywords = []
        for keyword in self._required_keywords:
            search_keyword = keyword if self._case_sensitive else keyword.lower()
            if search_keyword not in search_output:
                missing_keywords.append(keyword)

        # 检查禁止关键词
        found_forbidden = []
        for keyword in self._forbidden_keywords:
            search_keyword = keyword if self._case_sensitive else keyword.lower()
            if search_keyword in search_output:
                found_forbidden.append(keyword)

        is_valid = len(missing_keywords) == 0 and len(found_forbidden) == 0

        if is_valid:
            message = "关键词验证通过"
        elif found_forbidden:
            message = f"包含禁止关键词: {', '.join(found_forbidden)}"
        else:
            message = f"缺少必需关键词: {', '.join(missing_keywords)}"

        return ValidationResult(
            is_valid=is_valid,
            message=message,
            details={
                "required_keywords": self._required_keywords,
                "missing_keywords": missing_keywords,
                "forbidden_keywords": self._forbidden_keywords,
                "found_forbidden": found_forbidden
            }
        )
