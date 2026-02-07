"""
网络搜索技能
"""

import json
from typing import Any, Dict, Optional
from ..base import Skill, SkillResult


class WebSearchSkill(Skill):
    """网络搜索技能"""

    name = "web_search"
    description = "搜索网络获取信息，支持网页搜索"
    permission_level = "sensitive"  # 敏感权限

    async def execute(
        self,
        query: str,
        search_engine: str = "auto",
        max_results: int = 5,
        **kwargs
    ) -> SkillResult:
        """
        执行网络搜索

        Args:
            query: 搜索查询
            search_engine: 搜索引擎 (google, bing, duckduckgo, auto)
            max_results: 最大结果数
        """
        try:
            # 优先使用 MCP web-search 服务
            try:
                from mcp_web_search_prime import web_search

                result = await web_search(
                    search_query=query,
                    content_size="medium",
                    search_query_num=max_results
                )

                return SkillResult(
                    success=True,
                    data={
                        "query": query,
                        "results": result,
                        "source": "mcp_web_search"
                    }
                )
            except ImportError:
                pass

            # 备选：使用 httpx 直接调用搜索引擎
            import httpx
            import urllib.parse

            encoded_query = urllib.parse.quote(query)

            # 使用 DuckDuckGo HTML API（无需 API key）
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()

                # 简单解析 HTML 结果
                results = self._parse_html_results(response.text)

                return SkillResult(
                    success=True,
                    data={
                        "query": query,
                        "results": results[:max_results],
                        "source": "duckduckgo"
                    }
                )

        except ImportError as e:
            return SkillResult(
                success=False,
                error=f"缺少依赖: {str(e)}"
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"搜索错误: {str(e)}"
            )

    def _parse_html_results(self, html: str) -> list:
        """解析 DuckDuckGo HTML 结果"""
        import re

        results = []

        # DuckDuckGo HTML 格式解析
        pattern = r'<a class="result__a" href="([^"]*)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, html, re.DOTALL)

        for href, title in matches[:10]:
            # 清理 HTML 标签
            title_clean = re.sub(r'<[^>]+>', '', title).strip()
            href_clean = href if href.startswith('http') else ''

            if title_clean and href_clean:
                results.append({
                    "title": title_clean,
                    "url": href_clean
                })

        return results

    async def fetch_url(self, url: str, **kwargs) -> SkillResult:
        """
        获取 URL 内容

        Args:
            url: 目标 URL
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()

                # 返回文本内容
                content_length = len(response.text)
                excerpt = response.text[:500] + "..." if len(response.text) > 500 else response.text

                return SkillResult(
                    success=True,
                    data={
                        "url": url,
                        "status_code": response.status_code,
                        "content_length": content_length,
                        "excerpt": excerpt
                    }
                )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"获取 URL 失败: {str(e)}"
            )

    async def search_news(
        self,
        topic: str,
        max_results: int = 5,
        **kwargs
    ) -> SkillResult:
        """
        搜索新闻

        Args:
            topic: 新闻主题
            max_results: 最大结果数
        """
        return await self.execute(
            query=f"latest news {topic}",
            max_results=max_results,
            **kwargs
        )
