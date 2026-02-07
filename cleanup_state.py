#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理状态文件，终止所有卡住的任务"""

import json
import os
from datetime import datetime

STATE_FILE = "state/state.json"
BACKUP_FILE = f"state/state_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def cleanup_state():
    # 备份原文件
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            old_data = json.load(f)
        with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(old_data, f, indent=2, ensure_ascii=False)
        print(f"已备份状态文件到: {BACKUP_FILE}")

    # 创建新的干净状态
    new_state = {
        "version": "1.0.0",
        "last_status": "idle",
        "last_error": None,
        "last_error_timestamp": None,
        "modified_files": [],
        "completed_tasks_count": 0,
        "failed_tasks_count": 0,
        "last_task_timestamp": None,
        "project_context": {},
        "task_queue": []
    }

    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_state, f, indent=2, ensure_ascii=False)

    print("已清理状态文件")
    print(f"之前有 {len(old_data.get('task_queue', []))} 个任务")

if __name__ == "__main__":
    cleanup_state()
