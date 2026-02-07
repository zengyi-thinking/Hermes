#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Hermes 启动脚本

支持：
- 邮箱任务
- Telegram 任务 (@hermes_zeng_bot)

使用方式：
  python run_hermes.py

环境变量：
  TELEGRAM_TOKEN - Telegram Bot Token
"""

import os
import sys

# 确保 src 目录在路径中
src_dir = os.path.dirname(os.path.abspath(__file__))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# 确保 Telegram Token 已加载
from dotenv import load_dotenv
load_dotenv(os.path.join(src_dir, '.env'))

# 导入并运行主程序
from src.main import main

if __name__ == "__main__":
    main()
