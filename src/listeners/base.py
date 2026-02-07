"""
监听器基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from enum import Enum


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """任务模型"""
    id: str = field(default_factory=str)
    original_prompt: str = ""
    refined_prompt: str = ""
    status: TaskStatus = TaskStatus.PENDING
    channel_message_id: str = ""
    sender: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    result: str = ""
    error: str = ""
    metadata: dict = field(default_factory=dict)


class BaseListener(ABC):
    """监听器抽象基类"""

    @abstractmethod
    def start(self) -> None:
        """开始监听"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """停止监听"""
        pass

    @abstractmethod
    def poll(self) -> List[Task]:
        """轮询获取任务"""
        pass

    @abstractmethod
    def acknowledge(self, task_id: str) -> bool:
        """确认任务已处理"""
        pass
