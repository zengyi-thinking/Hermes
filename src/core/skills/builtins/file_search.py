"""
文件搜索技能
"""

import glob
import os
from typing import Dict, List, Optional
from ..base import Skill, SkillResult


class FileSearchSkill(Skill):
    """文件搜索技能"""

    name = "file_search"
    description = "搜索文件和目录，支持按名称、路径模式匹配"
    permission_level = "normal"

    async def execute(
        self,
        pattern: str,
        search_path: str = ".",
        recursive: bool = True,
        max_results: int = 100,
        **kwargs
    ) -> SkillResult:
        """
        执行文件搜索

        Args:
            pattern: 文件名匹配模式（如 *.py, *.txt）
            search_path: 搜索起始路径
            recursive: 是否递归搜索子目录
            max_results: 最大返回结果数
        """
        try:
            # 构建搜索模式
            if recursive:
                full_pattern = os.path.join(search_path, "**", pattern)
            else:
                full_pattern = os.path.join(search_path, pattern)

            # 执行搜索
            matches = glob.glob(full_pattern, recursive=recursive)

            # 过滤只保留文件和目录（排除其他）
            matches = [m for m in matches if os.path.exists(m)]

            # 限制结果数量
            matches = matches[:max_results]

            # 获取文件详情
            file_details = []
            for match in matches:
                try:
                    stat = os.stat(match)
                    file_details.append({
                        "path": match,
                        "name": os.path.basename(match),
                        "is_dir": os.path.isdir(match),
                        "size": stat.st_size if os.path.isfile(match) else 0,
                        "modified": stat.st_mtime
                    })
                except Exception:
                    file_details.append({
                        "path": match,
                        "name": os.path.basename(match),
                        "is_dir": os.path.isdir(match),
                        "size": 0,
                        "modified": 0
                    })

            return SkillResult(
                success=True,
                data={
                    "pattern": pattern,
                    "search_path": search_path,
                    "matches": file_details,
                    "count": len(file_details)
                }
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"搜索错误: {str(e)}"
            )

    async def search_content(
        self,
        keyword: str,
        search_path: str = ".",
        file_types: Optional[List[str]] = None,
        **kwargs
    ) -> SkillResult:
        """
        搜索文件内容

        Args:
            keyword: 搜索关键词
            search_path: 搜索路径
            file_types: 限定文件类型（如 ['.py', '.txt']）
        """
        try:
            import re

            results = []

            # 确定要搜索的文件类型
            if file_types is None:
                file_types = ['.*']  # 搜索所有文件

            # 遍历目录
            for root, dirs, files in os.walk(search_path):
                for file in files:
                    # 检查文件类型
                    if file_types != ['.*']:
                        if not any(file.endswith(ext) for ext in file_types):
                            continue

                    file_path = os.path.join(root, file)

                    # 读取文件内容并搜索
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()

                        for line_num, line in enumerate(lines, 1):
                            if keyword.lower() in line.lower():
                                results.append({
                                    "file": file_path,
                                    "line": line_num,
                                    "content": line.strip()
                                })
                    except Exception:
                        continue

            return SkillResult(
                success=True,
                data={
                    "keyword": keyword,
                    "results": results[:100],  # 限制结果数
                    "count": len(results)
                }
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"内容搜索错误: {str(e)}"
            )
