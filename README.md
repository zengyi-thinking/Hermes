# Hermes - Claude Code 远程异步指挥系统

基于 Python 的 Claude Code 远程指挥系统，支持通过**邮箱**和**Telegram**发送指令，系统自动优化并执行。

## 功能特性

- 📧 **邮箱监听**：自动轮询邮箱，识别 `[Task]` 主题的指令邮件
- 📱 **Telegram Bot**：支持 `@hermes_zeng_bot` 实时接收指令
- 🧠 **智能优化 (Refiner)**：将模糊的语音输入转化为精确的技术 Prompt
- ⚡ **Claude CLI 执行**：通过 git-bash 调用 Claude Code
- 📊 **状态管理**：维护 state.json，记录任务历史和文件变更
- 📬 **自动报告**：任务完成后自动发送执行结果

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境

编辑 `.env` 文件：

```env
# 邮箱配置 (以 QQ 邮箱为例)
EMAIL_IMAP_HOST=imap.qq.com
EMAIL_IMAP_PORT=993
EMAIL_SMTP_HOST=smtp.qq.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=your_email@qq.com
EMAIL_PASSWORD=your授权码

# Telegram 配置（可选）
TELEGRAM_TOKEN=your_bot_token

# Claude 配置
CLAUDE_WORK_DIR=D:\DevProject\Hermes
CLAUDE_TIMEOUT=600

# LLM 配置 (用于 Refiner 优化指令)
LLM_PROVIDER=minimax
LLM_API_KEY=your_api_key
```

### 3. 启动系统

```bash
python run_hermes.py
```

或直接在 PowerShell/CMD 中运行：

```powershell
python run_hermes.py
```

## 使用方法

### 方式一：邮箱指令

发送邮件到配置的邮箱，主题以 `[Task]` 开头：

```
主题: [Task] 帮我创建一个 Python 脚本来处理 CSV 文件
正文: 读取 data.csv，计算每列的平均值，输出到 result.txt
```

### 方式二：Telegram

在 Telegram 中搜索 `@hermes_zeng_bot`，直接发送指令：

```
帮我分析 D:\DevProject\AI_Travel_Planner_Pro 项目，生成说明文档
```

### 系统响应

1. 收到指令后，Refiner Agent 优化指令
2. 调用 Claude CLI 执行
3. 返回执行结果（通过原渠道）

## 项目结构

```
Hermes/
├── src/
│   ├── main.py              # 主入口（邮箱+Telegram）
│   ├── core/
│   │   ├── agent/
│   │   │   ├── executor.py  # Claude CLI 执行器（通过 git-bash）
│   │   │   └── refiner.py  # 指令优化器
│   │   ├── channel/
│   │   │   ├── email.py     # 邮箱通道
│   │   │   └── telegram.py  # Telegram 通道
│   │   └── state/
│   │       ├── manager.py   # 状态管理
│   │       └── schemas.py   # 数据模型
│   ├── listeners/
│   │   └── imap.py         # IMAP 邮箱监听
│   └── reporters/
│       └── email.py         # 邮件报告
├── config/
│   ├── settings.py         # 配置管理
│   └── prompts/            # Prompt 模板
├── logs/                    # 日志文件
├── state/                   # 状态文件
├── .env                     # 环境配置（敏感信息）
└── run_hermes.py          # 启动脚本
```

## 常见问题

### Q: Telegram 任务超时怎么办？

A: 系统已优化超时处理。如果 Claude 实际完成了任务（文件已创建），即使超时也会返回实际结果。

### Q: 如何查看日志？

A: 日志保存在 `logs/` 目录下，按日期分文件存储。

### Q: 支持其他通信渠道吗？

A: 系统采用适配器模式，可以轻松扩展飞书、Slack 等渠道。

## License

MIT
