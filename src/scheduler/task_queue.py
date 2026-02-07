"""
任务队列管理器

支持多任务串行执行、优先级、状态持久化
"""
import uuid
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from ..core.state.schemas import TaskStatus, TaskInfo


@dataclass
class QueueConfig:
    """队列配置"""
    max_retries: int = 3
    task_timeout: int = 300
    poll_interval: int = 60


@dataclass
class QueueItem:
    """队列项"""
    task: TaskInfo
    priority: int = 0  # 越小优先级越高
    retries: int = 0
    added_at: datetime = field(default_factory=datetime.now)


class TaskQueue:
    """
    任务队列

    特性：
    - 串行执行：上一任务完成后才执行下一任务
    - 优先级支持：高优先级任务优先处理
    - 重试机制：失败任务自动重试
    - 状态持久化：重启后可恢复执行进度
    """

    def __init__(self, config: QueueConfig = None):
        self.config = config or QueueConfig()
        self._queue: List[QueueItem] = []
        self._lock = threading.Lock()
        self._processing: Optional[QueueItem] = None
        self._completed: List[QueueItem] = []
        self._failed: List[QueueItem] = []

    def add(self, task: TaskInfo, priority: int = 0) -> str:
        """
        添加任务到队列

        Args:
            task: 任务信息
            priority: 优先级（0-9，0 最高）

        Returns:
            任务 ID
        """
        with self._lock:
            # 检查是否已存在
            existing = self._find_task(task.task_id)
            if existing:
                return task.task_id

            item = QueueItem(task=task, priority=priority)

            # 按优先级插入
            inserted = False
            for i, q_item in enumerate(self._queue):
                if priority < q_item.priority:
                    self._queue.insert(i, item)
                    inserted = True
                    break

            if not inserted:
                self._queue.append(item)

            return task.task_id

    def add_batch(self, tasks: List[TaskInfo], default_priority: int = 0) -> List[str]:
        """批量添加任务"""
        return [self.add(task, default_priority) for task in tasks]

    def get_next(self) -> Optional[TaskInfo]:
        """
        获取下一个待处理任务

        Returns:
            下一个任务，或 None
        """
        with self._lock:
            if self._processing:
                return self._processing.task

            if not self._queue:
                return None

            # 获取队首任务
            item = self._queue.pop(0)
            self._processing = item
            item.task.status = TaskStatus.PROCESSING.value
            item.task.started_at = datetime.now()

            return item.task

    def complete(self, task_id: str, success: bool, output_files: List[str] = None) -> bool:
        """
        完成任务

        Args:
            task_id: 任务 ID
            success: 是否成功
            output_files: 输出的文件列表

        Returns:
            是否找到并完成任务
        """
        with self._lock:
            if not self._processing or self._processing.task.task_id != task_id:
                return False

            item = self._processing
            item.task.status = (
                TaskStatus.COMPLETED.value if success
                else TaskStatus.FAILED.value
            )
            item.task.completed_at = datetime.now()
            item.task.output_files = output_files or []

            if success:
                self._completed.append(item)
            else:
                # 检查是否需要重试
                if item.retries < self.config.max_retries:
                    item.retries += 1
                    item.task.status = TaskStatus.PENDING.value
                    item.task.started_at = None
                    # 放回队列队首
                    self._queue.insert(0, item)
                else:
                    self._failed.append(item)

            self._processing = None
            return True

    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        with self._lock:
            # 检查是否正在处理
            if self._processing and self._processing.task.task_id == task_id:
                self._processing = None
                return True

            # 从队列中移除
            for i, item in enumerate(self._queue):
                if item.task.task_id == task_id:
                    del self._queue[i]
                    return True

            return False

    def clear_completed(self) -> int:
        """清理已完成的任务"""
        with self._lock:
            count = len(self._completed)
            self._completed = []
            return count

    def clear_failed(self) -> int:
        """清理失败的任务"""
        with self._lock:
            count = len(self._failed)
            self._failed = []
            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取队列统计"""
        with self._lock:
            return {
                "pending": len(self._queue),
                "processing": 1 if self._processing else 0,
                "completed": len(self._completed),
                "failed": len(self._failed),
                "total": len(self._queue) + len(self._completed) + len(self._failed)
            }

    def get_processing(self) -> Optional[TaskInfo]:
        """获取正在处理的任务"""
        with self._lock:
            if self._processing:
                return self._processing.task
            return None

    def get_all(self) -> List[TaskInfo]:
        """获取所有任务"""
        with self._lock:
            tasks = [item.task for item in self._queue]
            if self._processing:
                tasks.insert(0, self._processing.task)
            tasks.extend([item.task for item in self._completed])
            tasks.extend([item.task for item in self._failed])
            return tasks

    def is_empty(self) -> bool:
        """检查队列是否为空"""
        with self._lock:
            return (
                len(self._queue) == 0 and
                self._processing is None
            )

    def _find_task(self, task_id: str) -> Optional[QueueItem]:
        """查找任务"""
        if self._processing and self._processing.task.task_id == task_id:
            return self._processing

        for item in self._queue:
            if item.task.task_id == task_id:
                return item

        return None

    def to_dict(self) -> dict:
        """转换为字典"""
        with self._lock:
            return {
                "queue": [
                    {
                        "task": item.task.to_dict(),
                        "priority": item.priority,
                        "retries": item.retries,
                        "added_at": item.added_at.isoformat()
                    }
                    for item in self._queue
                ],
                "processing": (
                    self._processing.task.to_dict()
                    if self._processing else None
                ),
                "stats": self.get_stats()
            }
