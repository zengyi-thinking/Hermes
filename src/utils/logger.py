"""
日志配置模块
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import structlog


def get_log_level(level: str = "INFO") -> str:
    """获取日志级别"""
    return level.upper()


def setup_logger(
    name: str = "hermes",
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    format: str = "json"  # json | pretty
) -> structlog.BoundLogger:
    """
    配置日志系统
    """
    # 配置处理器
    processors = [
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(colors=True) if format == "pretty" else structlog.processors.JSONRenderer(),
    ]

    # 配置 structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(get_log_level(log_level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger(name)


class LoggerMixin:
    """日志混入类"""

    @property
    def log(self) -> structlog.BoundLogger:
        """获取 logger"""
        return structlog.get_logger(self.__class__.__name__)


def get_logger(name: str = "hermes") -> structlog.BoundLogger:
    """获取 logger 便捷函数"""
    return structlog.get_logger(name)
