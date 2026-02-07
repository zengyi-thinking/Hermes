#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Hermes 主应用入口
支持邮箱和Telegram，通过原渠道返回结果
集成 Skills 技能系统、Session 会话管理
"""
import signal
import sys
import os
import asyncio
from datetime import datetime
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_settings, EmailConfig
from src.utils.logger import get_logger
from src.core.state.manager import StateManager
from src.core.state.schemas import TaskStatus, TaskInfo, RefinedResult, ExecutionResult, TaskUnderstandingResult
from src.core.channel.email import EmailChannel
from src.core.channel.telegram import TelegramChannel, Message
from src.core.agent.refiner import RefinerAgent
from src.core.agent.task_understanding import TaskUnderstandingAgent, UnderstandingConfig
from src.core.agent.executor import ClaudeExecutor, ExecutorConfig
from src.core.llm.third_party import create_llm_client
from src.listeners.imap import IMAPListener, IMAPConfig
from src.reporters.html import HTMLReportGenerator
from src.reporters.github import GitHubPusher
from config.reporter import ReportMode

# Skills 和 Session 模块
from src.core.skills import SkillRegistry, register_builtin_skills
from src.core.skills.base import SkillResult
from src.core.session import SessionManager, SessionStatus

# 监督器模块
from src.core.supervisor import ExecutionMonitor, ExecutionPhase, RegexValidator, FileExistsValidator
from src.core.supervisor.health_monitor import ProcessHealthMonitor, HealthMonitorConfig
from src.core.memory import ShortTermMemory, LongTermMemory, MemoryRetriever, UserPreference
from src.core.reporters.task_doc_generator import TaskDocGenerator, create_task_doc_from_result
from src.core.hooks import HookGenerator


class HermesApplication:
    def __init__(self):
        self.settings = get_settings()
        self.log = get_logger("hermes")
        self.state_manager = StateManager(self.settings.state_file)

        # 初始化会话管理器
        self.session_manager = SessionManager()
        self.log.info("Session 系统已初始化")
        self.llm_client = create_llm_client(
            provider=self.settings.llm.provider,
            api_key=self.settings.llm.api_key.get_secret_value(),
            base_url=self.settings.llm.base_url,
            model=self.settings.llm.model,
            temperature=self.settings.llm.temperature,
            max_tokens=self.settings.llm.max_tokens
        )
        self._init_components()
        self._running = False
        self._shutdown_requested = False

    def _init_components(self):
        email_config = EmailConfig(
            imap_host=self.settings.email.imap_host,
            imap_port=self.settings.email.imap_port,
            smtp_host=self.settings.email.smtp_host,
            smtp_port=self.settings.email.smtp_port,
            username=self.settings.email.username,
            password=self.settings.email.password,
            search_subject=self.settings.email.search_subject
        )

        imap_config = IMAPConfig(
            host=self.settings.email.imap_host,
            port=self.settings.email.imap_port,
            username=self.settings.email.username,
            password=self.settings.email.password.get_secret_value(),
            search_subject=self.settings.email.search_subject,
            poll_interval=self.settings.task.poll_interval
        )
        self.email_listener = IMAPListener(imap_config)
        self.email_channel = EmailChannel(email_config)

        # Telegram
        self.telegram_channel = None
        telegram_token = os.getenv("TELEGRAM_TOKEN")
        if telegram_token:
            try:
                self.telegram_channel = TelegramChannel(
                    token=telegram_token,
                    poll_interval=self.settings.task.poll_interval
                )
                if self.telegram_channel.connect():
                    self.log.info("Telegram: @{}".format(self.telegram_channel.bot_info['username']))
                else:
                    self.telegram_channel = None
            except Exception as e:
                self.log.warning("Telegram 失败: {}".format(e))
                self.telegram_channel = None

        self.refiner = RefinerAgent(self.llm_client)

        # 初始化任务理解器
        understanding_config = UnderstandingConfig(
            system_prompt_path=self.settings.understanding.system_prompt_path,
            max_context_tasks=self.settings.understanding.max_context_tasks,
            min_confidence=self.settings.understanding.min_confidence,
            enable_interrupt_check=self.settings.understanding.enable_interrupt_check
        )
        self.task_understanding = TaskUnderstandingAgent(
            llm_client=self.llm_client,
            config=understanding_config
        )

        self.executor = ClaudeExecutor(ExecutorConfig(
            cli_path=self.settings.claude.cli_path,
            work_dir=self.settings.claude.work_dir,
            timeout=self.settings.claude.timeout,
            git_bash_path=os.getenv("CLAUDE_CODE_GIT_BASH_PATH", "")
        ))

        # 初始化报告生成器
        self.html_generator = HTMLReportGenerator(self.settings.report)
        self.github_pusher = None
        if self.settings.report.mode == ReportMode.GITHUB_PAGES:
            try:
                self.github_pusher = GitHubPusher(self.settings.report)
                self.log.info("GitHub Pages 模式已启用")
            except Exception as e:
                self.log.warning("GitHub Pages 初始化失败: {}".format(e))

        # ========== 初始化 Skills 技能系统 ==========
        self._init_skills_system()

        # ========== 初始化监督器系统 ==========
        self._init_supervisor_system()

        # ========== 初始化记忆系统 ==========
        self._init_memory_system()

        # ========== 初始化文档生成器 ==========
        self._init_doc_generator()

        # ========== 初始化钩子系统 ==========
        self._init_hooks_system()

    def _init_skills_system(self):
        """初始化 Skills 技能系统"""
        self.log.info("=" * 50)
        self.log.info("🛠️  INITIALIZING SKILLS SYSTEM")
        self.log.info("=" * 50)

        try:
            # 注册内置技能
            register_builtin_skills()
            skill_count = SkillRegistry.get_count()
            skills = SkillRegistry.list_available()

            self.log.info(f"   [COUNT] Registered Skills: {skill_count}")
            self.log.info("-" * 50)

            for skill in skills:
                self.log.info(f"   • {skill['name']:15} | {skill['permission_level']:8} | {skill['description'][:30]}")

            self.log.info("=" * 50)
            self.log.info("✅ Skills System Initialized Successfully")
            self.log.info("=" * 50)
        except Exception as e:
            self.log.error(f"❌ Skills System Init Failed: {e}")
            self.log.info("=" * 50)

    def _init_supervisor_system(self):
        """初始化监督器系统"""
        self.log.info("=" * 50)
        self.log.info("📊 INITIALIZING SUPERVISOR SYSTEM")
        self.log.info("=" * 50)

        try:
            # 初始化执行监督器
            self.execution_monitor = ExecutionMonitor(
                logger=self.log,
                channel_adapter=self.telegram_channel,
                channel="telegram"
            )
            self.log.info("   ✅ ExecutionMonitor 已初始化")

            # 初始化健康监控器
            self.health_monitor = ProcessHealthMonitor(
                channel_adapter=self.telegram_channel,
                config=HealthMonitorConfig(
                    enable_notification=self.telegram_channel is not None
                ),
                logger=self.log
            )
            self.log.info("   ✅ ProcessHealthMonitor 已初始化 (智能超时，无固定限制)")

            self.log.info("=" * 50)
            self.log.info("✅ Supervisor System Initialized Successfully")
            self.log.info("=" * 50)
        except Exception as e:
            self.log.error(f"❌ Supervisor System Init Failed: {e}")
            self.log.info("=" * 50)

    def _init_memory_system(self):
        """初始化记忆系统"""
        self.log.info("=" * 50)
        self.log.info("🧠 INITIALIZING MEMORY SYSTEM")
        self.log.info("=" * 50)

        try:
            # 初始化长期记忆
            self.long_term_memory = LongTermMemory(
                storage_dir="./memory",
                default_ttl_days=90
            )
            self.log.info("   ✅ LongTermMemory 已初始化")

            # 初始化记忆检索器
            self.memory_retriever = MemoryRetriever()
            self.log.info("   ✅ MemoryRetriever 已初始化")

            self.log.info("=" * 50)
            self.log.info("✅ Memory System Initialized Successfully")
            self.log.info("=" * 50)
        except Exception as e:
            self.log.error(f"❌ Memory System Init Failed: {e}")
            self.log.info("=" * 50)

    def _init_doc_generator(self):
        """初始化文档生成器"""
        self.log.info("=" * 50)
        self.log.info("📄 INITIALIZING DOCUMENT GENERATOR")
        self.log.info("=" * 50)

        try:
            # 初始化任务文档生成器
            self.task_doc_generator = TaskDocGenerator(
                tasks_dir="./tasks",
                project_root="."
            )
            self.log.info("   ✅ TaskDocGenerator 已初始化")

            self.log.info("=" * 50)
            self.log.info("✅ Document Generator Initialized Successfully")
            self.log.info("=" * 50)
        except Exception as e:
            self.log.error(f"❌ Document Generator Init Failed: {e}")
            self.log.info("=" * 50)

    def _init_hooks_system(self):
        """初始化钩子系统"""
        self.log.info("=" * 50)
        self.log.info("🪝 INITIALIZING HOOKS SYSTEM")
        self.log.info("=" * 50)

        try:
            # 初始化钩子生成器
            self.hook_generator = HookGenerator(project_root=".")
            self.log.info("   ✅ HookGenerator 已初始化")

            self.log.info("=" * 50)
            self.log.info("✅ Hooks System Initialized Successfully")
            self.log.info("=" * 50)
        except Exception as e:
            self.log.error(f"❌ Hooks System Init Failed: {e}")
            self.log.info("=" * 50)

    # ==================== Skills 技能系统 ====================

    def _detect_skill(self, message: str) -> tuple:
        """
        检测消息是否包含技能调用

        Returns:
            (skill_name, args) 或 (None, None)
        """
        message = message.strip()

        # 计算器模式: "计算 X" 或 "X 等于多少"
        calc_match = re.match(r'^(?:计算|算一下|算)\s*(.+)$', message)
        if calc_match:
            expression = calc_match.group(1).strip()
            return "calculator", {"expression": expression}

        # 文件搜索模式: "搜索 *.py" 或 "查找文件 *.py"
        search_match = re.match(r'^(?:搜索|查找|找)\s*(?:文件\s*)?(.+)$', message)
        if search_match:
            pattern = search_match.group(1).strip()
            return "file_search", {"pattern": pattern}

        # 网络搜索模式: "搜索 XXX" 或 "搜索网络 XXX"
        web_match = re.match(r'^(?:搜索|查一下|查找)\s*(?:网络\s*)?(.+)$', message)
        if web_match:
            query = web_match.group(1).strip()
            return "web_search", {"query": query}

        # 系统信息模式: "系统信息" 或 "查看系统"
        sys_match = re.match(r'^(?:系统信息|查看系统|系统状态)$', message, re.IGNORECASE)
        if sys_match:
            return "system_info", {"info_type": "all"}

        return None, None

    async def _execute_skill(self, skill_name: str, args: dict | None) -> str:
        """
        执行技能并返回结果

        Args:
            skill_name: 技能名称
            args: 技能参数

        Returns:
            结果文本
        """
        # ========== 技能执行日志 ==========
        self.log.info("=" * 50)
        self.log.info("🔧 SKILL EXECUTION STARTED")
        self.log.info("=" * 50)
        self.log.info(f"   [SKILL] Name: {skill_name}")
        normalized_args = args if isinstance(args, dict) else {}
        self.log.info(f"   [SKILL] Arguments: {normalized_args}")
        self.log.info("-" * 50)

        try:
            result = SkillRegistry.execute(skill_name, **normalized_args)

            # ========== 技能执行结果日志 ==========
            self.log.info("-" * 50)
            self.log.info(f"   [SKILL] Success: {result.success}")
            if result.success:
                self.log.info(f"   [SKILL] Result Data: {result.data}")
                self.log.info("   [SKILL] EXECUTION SUCCESS ✅")
            else:
                self.log.error(f"   [SKILL] Error: {result.error}")
                self.log.warning("   [SKILL] EXECUTION FAILED ❌")
            self.log.info("=" * 50)

            if result.success:
                data = result.data

                if skill_name == "calculator":
                    expr = data.get("expression", "")
                    res = data.get("result", "")
                    return f"计算结果: {expr} = {res}"

                elif skill_name == "file_search":
                    matches = data.get("matches", [])
                    count = data.get("count", 0)
                    if count == 0:
                        return "没有找到匹配的文件"
                    lines = ["找到 {} 个文件:".format(count)]
                    for m in matches[:10]:
                        name = m.get("name", "")
                        path = m.get("path", "")
                        lines.append(f"- {name}")
                    if count > 10:
                        lines.append(f"... 还有 {count - 10} 个文件")
                    return "\n".join(lines)

                elif skill_name == "web_search":
                    results = data.get("results", [])
                    if not results:
                        return "没有找到相关结果"
                    lines = ["搜索结果:"]
                    for r in results[:5]:
                        title = r.get("title", "")
                        url = r.get("url", "")
                        lines.append(f"• {title}")
                    return "\n".join(lines)

                elif skill_name == "system_info":
                    info = []
                    for k, v in data.items():
                        if isinstance(v, (int, float)):
                            info.append(f"{k}: {v}")
                    return "系统信息:\n" + "\n".join(info)

                else:
                    return str(data)
            else:
                return "执行失败: {}".format(result.error)

        except Exception as e:
            self.log.error("技能执行错误: {}".format(e))
            self.log.info("=" * 50)
            return "技能执行失败: {}".format(str(e))

    def _should_use_skill(self, message: str) -> bool:
        """
        判断是否应该使用技能处理
        """
        skill_name, _ = self._detect_skill(message)
        return skill_name is not None

    def run(self):
        self._running = True
        self.log.info("=" * 50)
        self.log.info("Hermes 启动")
        self.log.info("=" * 50)

        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        self.state_manager.update_status("running")

        self.log.info("邮箱: {}".format(self.settings.email.username))
        if self.telegram_channel:
            self.log.info("Telegram: @{}".format(self.telegram_channel.bot_info['username']))
        else:
            self.log.info("Telegram: 未配置")
        self.log.info("超时: {}秒".format(self.settings.claude.timeout))
        self.log.info("=" * 50)

        try:
            while not self._shutdown_requested:
                try:
                    self._poll_all_channels()
                    self._sleep()
                except Exception as e:
                    self.log.error("错误: {}".format(e))
                    self._sleep(5)
        finally:
            self._cleanup()

    def _poll_all_channels(self):
        # 邮箱
        try:
            for task in self.email_listener.poll():
                self._handle_email_task(task)
        except Exception as e:
            self.log.error("邮箱错误: {}".format(e))

        # Telegram
        if self.telegram_channel:
            try:
                for msg in self.telegram_channel.receive():
                    self._handle_telegram_message(msg)
            except Exception as e:
                self.log.error("Telegram 错误: {}".format(e))

    def _handle_telegram_message(self, message: Message):
        """处理 Telegram 消息"""
        self.log.info("收到 TG: {}...".format(message.content[:50]))

        # 获取或创建会话
        user_id = message.metadata.get("username", message.sender)
        session = SessionManager().get_or_create_session(
            user_id=user_id,
            platform="telegram",
            session_id=message.metadata.get("session_id")
        )

        # 添加用户消息到会话历史
        session.add_user_message(message.content)

        # ========== 技能检测 ==========
        skill_name, skill_args = self._detect_skill(message.content)

        # ========== 技能检测日志 ==========
        self.log.info("=" * 50)
        self.log.info("🔍 SKILL DETECTION")
        self.log.info("=" * 50)
        self.log.info(f"   [INPUT] Message: {message.content}")
        self.log.info(f"   [DETECTED] Skill: {skill_name}")
        self.log.info(f"   [DETECTED] Args: {skill_args}")
        self.log.info("-" * 50)

        if skill_name:
            self.log.info("   [STATUS] Skill detected ✅ - Will execute")
            self.log.info("=" * 50)

            # 检查是否需要审批
            if SkillRegistry.require_approval(skill_name):
                # 发送需要确认的消息
                self.telegram_channel.send_markdown(
                    message.metadata.get("chat_id", message.sender),
                    "⚠️ 此操作需要确认才能执行，请回复 '是' 确认。"
                )
                # 保存待审批操作
                approval_id = SessionManager().request_approval(
                    session.session_id,
                    f"执行技能 {skill_name}",
                    {"skill": skill_name, "args": skill_args}
                )
                session.metadata["pending_approval"] = approval_id
                return

            # 同步执行技能（简化处理）
            import asyncio
            try:
                safe_skill_args = skill_args if isinstance(skill_args, dict) else {}
                result_text = asyncio.run(self._execute_skill(skill_name, safe_skill_args))
                self.telegram_channel.send_markdown(
                    message.metadata.get("chat_id", message.sender),
                    result_text
                )
                session.add_assistant_message(result_text)
                return
            except Exception as e:
                self.log.error("技能执行失败: {}".format(e))
        else:
            self.log.info("   [STATUS] No skill detected - Normal task flow")
            self.log.info("=" * 50)

        # ========== 正常任务处理流程 ==========
        # 记录任务来源是 Telegram
        task_info = TaskInfo(
            task_id="tg_{}".format(datetime.now().strftime('%Y%m%d_%H%M%S')),
            original_prompt=message.content,
            sender=user_id,
            created_at=message.timestamp
        )
        # 重要：保存原始 message 用于回复
        task_info.metadata = {
            "tg_message": message,
            "channel": "telegram",
            "session_id": session.session_id
        }
        self.state_manager.add_task(task_info)
        self._process_task(task_info)

    def _handle_email_task(self, task):
        """处理邮箱任务"""
        self.log.info("收到邮件: {}...".format(task.id[:20]))

        task_info = TaskInfo(
            task_id=task.id,
            original_prompt=task.original_prompt,
            sender=task.sender,  # 邮箱地址
            created_at=task.timestamp
        )
        # 保存邮件任务信息
        task_info.metadata = {"email_task": task, "channel": "email"}
        self.state_manager.add_task(task_info)

        try:
            self.email_listener.mark_seen(task.metadata.get("uid", task.id))
        except:
            pass
        self._process_task(task_info)

    def _reply_to_user(self, task_info: TaskInfo, content: str):
        """通过原渠道回复用户"""
        channel = task_info.metadata.get("channel", "email")

        if channel == "telegram" and self.telegram_channel:
            # Telegram 渠道 - 使用 chat_id 发送
            try:
                tg_msg = task_info.metadata.get("tg_message")
                if tg_msg:
                    # 使用 metadata 中的 chat_id（数字）
                    chat_id = tg_msg.metadata.get("chat_id", tg_msg.sender)
                    self.telegram_channel.send_markdown(chat_id, content)
                    self.log.info("TG 回复已发送到 chat_id: {}".format(chat_id))
                else:
                    self.log.error("没有保存 tg_message")
            except Exception as e:
                self.log.error("TG 回复失败: {}".format(e))
        else:
            # 邮箱渠道 - 暂不处理
            self.log.info("邮件回复: {}...".format(content[:50]))

    def _build_understanding_feedback(
        self,
        task_info: TaskInfo,
        understanding: TaskUnderstandingResult
    ) -> str:
        """
        构建任务理解结果反馈消息
        """
        # 意图类型的中文映射
        intent_map = {
            "new_task": "新任务",
            "continue": "继续/补充",
            "modify": "修改任务",
            "cancel": "取消任务",
            "clarification": "澄清问题",
            "confirm": "确认执行"
        }

        intent_cn = intent_map.get(understanding.intent_type, understanding.intent_type)

        lines = [
            "🎯 任务理解分析",
            "",
            f"**意图识别**: {intent_cn}",
            f"**置信度**: {understanding.confidence:.0%}",
            "",
            f"📝 {understanding.understanding}",
        ]

        # 如果需要澄清
        if understanding.suggested_questions:
            lines.extend([
                "",
                "❓ 需要澄清的问题：",
            ])
            for i, q in enumerate(understanding.suggested_questions[:3], 1):
                lines.append(f"  {i}. {q}")

        # 如果需要中断当前任务
        if understanding.should_interrupt:
            lines.extend([
                "",
                "⚠️ 检测到当前有任务正在执行",
                "新任务可能与当前任务冲突，是否要：",
                "  1. 中断当前任务，开始新任务",
                "  2. 等待当前任务完成后执行",
                "  3. 取消新任务"
            ])

        lines.extend([
            "",
            "_如需修改任务，请重新发送指令_"
        ])

        return "\n".join(lines)

    def _build_interrupt_confirm_message(
        self,
        task_info: TaskInfo,
        understanding: TaskUnderstandingResult,
        current_task: TaskInfo
    ) -> str:
        """
        构建任务中断确认消息
        """
        return "\n".join([
            "⚠️ **任务冲突检测**",
            "",
            f"**当前任务**: {current_task.original_prompt[:100]}...",
            "",
            f"**新任务**: {task_info.original_prompt[:100]}...",
            "",
            f"**分析**: {understanding.understanding}",
            "",
            "请选择：",
            "  1. 中断当前任务，开始新任务",
            "  2. 继续执行当前任务",
            "  3. 取消新任务",
            "",
            "请回复数字选择，或回复任意内容取消。"
        ])

    def _build_refined_feedback(self, task_info: TaskInfo, refined) -> str:
        """
        构建对任务需求的理解反馈消息
        """
        lines = [
            "🎯 我理解您的任务是：",
            "",
            "```",
            refined.refined_prompt,
            "```",
            "",
            f"📊 置信度: {refined.confidence:.0%}",
            f"📋 类型: {refined.intent_type}",
        ]

        # 添加建议步骤
        if refined.suggested_steps:
            lines.extend([
                "",
                "📝 执行步骤：",
            ])
            for i, step in enumerate(refined.suggested_steps[:5], 1):  # 最多显示5步
                lines.append(f"  {i}. {step}")
            if len(refined.suggested_steps) > 5:
                lines.append(f"  ... 共 {len(refined.suggested_steps)} 步")

        lines.extend([
            "",
            "⏳ 即将开始执行...",
            "",
            "_如需修改任务，请重新发送指令_"
        ])

        return "\n".join(lines)

    def _process_task(self, task_info: TaskInfo):
        self.log.info("处理: {}".format(task_info.task_id))

        try:
            # ========== 任务理解器分析 ==========
            state = self.state_manager.get_state()

            # 获取最近任务历史和当前任务
            context_tasks = state.task_queue[-self.settings.understanding.max_context_tasks:]
            current_task = None
            for t in context_tasks:
                if t.status == "processing":
                    current_task = t
                    break

            # 调用任务理解器
            if self.settings.understanding.enabled:
                understanding = self.task_understanding.understand(
                    raw_prompt=task_info.original_prompt,
                    context_tasks=context_tasks,
                    current_task=current_task
                )
                self.log.info("意图识别: {}, 置信度: {:.0%}".format(
                    understanding.intent_type, understanding.confidence
                ))
            else:
                # 如果禁用任务理解器，创建默认结果
                understanding = TaskUnderstandingResult(
                    intent_type="new_task",
                    understanding=task_info.original_prompt,
                    should_interrupt=False,
                    context_summary="",
                    confidence=0.7
                )

            # 处理 CONFIRM 意图 - 用户确认执行当前任务
            if understanding.intent_type == "confirm":
                self.log.info("用户确认执行当前任务")
                if current_task:
                    self.log.info("继续执行当前任务: {}".format(current_task.task_id))
                    # 直接使用当前任务继续执行（不发送额外确认消息，避免重复）
                    exec_result = self.executor.execute(
                        current_task.refined_prompt or current_task.original_prompt,
                        self.settings.claude.work_dir,
                        self.settings.claude.timeout
                    )
                    # 处理执行结果（包含发送消息）
                    self._handle_execution_result(task_info, exec_result, current_task)
                    return
                else:
                    # 没有当前任务，按正常流程处理
                    self.log.info("没有当前任务，按新任务处理")
                    # 继续正常流程，不发送额外消息

            # 正常流程：发送任务理解结果给用户确认
            feedback = self._build_understanding_feedback(task_info, understanding)
            self._reply_to_user(task_info, feedback)

            # 如果需要中断且有当前任务，询问用户
            if understanding.should_interrupt and current_task:
                interrupt_msg = self._build_interrupt_confirm_message(
                    task_info, understanding, current_task
                )
                self._reply_to_user(task_info, interrupt_msg)
                # 暂不实现用户确认流程，先继续执行
                self.log.info("检测到需要中断，但暂不支持用户确认流程，继续执行")

            # ========== Refiner - 优化提示词 ==========
            refined = self.refiner.refine(
                task_info.original_prompt,
                state,
                task_understanding=understanding
            )
            self.log.info("优化: {}...".format(refined.refined_prompt[:50]))
            self.log.info("置信度: {:.0%}".format(refined.confidence))

            self.state_manager.update_task_status(
                task_info.task_id,
                TaskStatus.PROCESSING.value,
                refined_prompt=refined.refined_prompt
            )

            # ========== 立即返回对任务需求的理解 ==========
            feedback_msg = self._build_refined_feedback(task_info, refined)
            self._reply_to_user(task_info, feedback_msg)
            self.log.info("已发送优化后的任务理解给用户")

            # 需要澄清
            if refined.clarifications and refined.confidence < 0.6:
                self.log.info("需要澄清: {}".format(refined.clarifications))
                # 通过原渠道请求澄清
                self._reply_to_user(task_info, "请澄清以下问题：\n\n" +
                                  "\n".join("{}. {}".format(i+1, q)
                                          for i, q in enumerate(refined.clarifications)))
                self.state_manager.update_task_status(task_info.task_id, TaskStatus.COMPLETED.value)
                return

            # 短暂暂停，让用户有机会打断
            import time
            time.sleep(2)

            # ========== 使用监督器执行任务 ==========
            self.log.info("=" * 60)
            self.log.info("📊 使用健康监控执行（无固定超时）")
            self.log.info("=" * 60)

            # 创建验证器
            validators = [
                FileExistsValidator(work_dir=self.settings.claude.work_dir)
            ]

            # 准备任务信息（用于通知）
            chat_id = None
            if task_info.metadata and "tg_message" in task_info.metadata:
                tg_msg = task_info.metadata.get("tg_message")
                chat_id = tg_msg.metadata.get("chat_id", tg_msg.sender) if tg_msg else None

            task_exec_info = {
                "task_id": task_info.task_id,
                "task_type": refined.intent_type,
                "chat_id": chat_id
            }

            # 使用健康监控执行（无固定超时）
            monitored_result = self.health_monitor.execute_with_health_monitoring(
                executor=self.executor,
                prompt=refined.refined_prompt,
                work_dir=self.settings.claude.work_dir,
                validators=validators,
                task_info=task_exec_info
            )

            # 转换为标准执行结果格式
            exec_result = ExecutionResult(
                success=monitored_result.success,
                stdout=monitored_result.stdout,
                stderr=monitored_result.stderr,
                exit_code=monitored_result.exit_code,
                duration=monitored_result.duration,
                output_files=monitored_result.output_files,
                created_files=monitored_result.created_files,
                modified_files=monitored_result.modified_files,
                deleted_files=monitored_result.deleted_files,
                error=monitored_result.error
            )

            # 记录详细执行结果
            stdout_len = len(exec_result.stdout) if exec_result.stdout else 0
            stderr_len = len(exec_result.stderr) if exec_result.stderr else 0
            self.log.info("执行结果: success={}, exit_code={}, stdout_len={}, stderr_len={}".format(
                exec_result.success, getattr(exec_result, 'exit_code', 'N/A'), stdout_len, stderr_len))

            # 直接打印内容摘要
            if exec_result.stdout:
                preview = exec_result.stdout[:100].replace('\n', ' ')
                self.log.info("stdout预览: {}...".format(preview))
            if exec_result.stderr:
                preview = exec_result.stderr[:100].replace('\n', ' ')
                self.log.info("stderr预览: {}...".format(preview))

            # 超时智能处理（健康监控版本）
            if not exec_result.success and exec_result.error:
                error_lower = exec_result.error.lower()
                if "timed out" in error_lower or "无响应" in exec_result.error:
                    self.log.info("检测到执行中断，检查是否有输出...")
                    if exec_result.stdout and len(exec_result.stdout.strip()) > 0:
                        exec_result.success = True
                        exec_result.error = ""
                        self.log.info("实际已完成，忽略中断")
                    else:
                        # 健康监控触发的中断
                        self.log.warning("进程无响应，已被健康监控系统中断")

            elapsed = exec_result.duration if hasattr(exec_result, 'duration') else 0
            self.log.info("完成: {}, {}秒".format(exec_result.success, elapsed))

            # 回复用户（通过原渠道）
            if exec_result.success:
                output = exec_result.stdout.strip() if exec_result.stdout else "任务完成"

                # 检查文件是否创建
                output_files = exec_result.output_files or []
                if output_files:
                    file_info = "\n已创建文件：\n" + "\n".join("- " + f for f in output_files)
                else:
                    file_info = ""

                # ========== 生成 HTML 报告（回复之前生成） ==========
                try:
                    # 创建 RefinedResult 对象用于报告生成
                    refined_result = RefinedResult(
                        refined_prompt=refined.refined_prompt,
                        clarifications=refined.clarifications,
                        suggested_steps=refined.suggested_steps,
                        confidence=refined.confidence,
                        intent_type=refined.intent_type,
                        reasoning=refined.reasoning,
                        original_prompt=task_info.original_prompt
                    )

                    # 生成 HTML 报告
                    report_path = self.html_generator.generate(
                        task=task_info,
                        refined=refined_result,
                        exec_result=exec_result
                    )
                    self.log.info("HTML 报告已生成: {}".format(report_path))

                    # 如果是 GitHub Pages 模式，推送到 GitHub
                    if self.github_pusher:
                        github_url, success = self.github_pusher.push_report_file(
                            file_path=report_path,
                            task_id=task_info.task_id
                        )
                        if success:
                            self.log.info("报告已推送到 GitHub: {}".format(github_url))
                            task_info.report_url = github_url
                except Exception as report_err:
                    self.log.error("生成报告失败: {}".format(report_err))

                # Telegram 消息长度限制
                if len(output) + len(file_info) > 3000:
                    output = output[:2500] + "\n\n...（详细内容见附件）"

                # 添加报告链接
                report_info = ""
                if hasattr(task_info, 'report_url') and task_info.report_url:
                    report_info = "\n\n📊 完整报告: {}".format(task_info.report_url)
                else:
                    report_info = "\n\n📊 报告文件: {}".format(str(report_path))

                self._reply_to_user(task_info, "任务完成\n\n{}{}{}".format(output, file_info, report_info))
            else:
                error_msg = exec_result.stderr or exec_result.error or "执行失败"
                is_timeout = ("timed out" in error_msg.lower() or "无响应" in error_msg) and exec_result.stdout
                if is_timeout:
                    output = exec_result.stdout.strip() if exec_result.stdout else ""
                    if output:
                        self._reply_to_user(task_info, "部分完成（进程中断）\n\n{}".format(output[:3000]))
                    else:
                        self._reply_to_user(task_info, "任务超时")
                else:
                    self._reply_to_user(task_info, "任务失败\n\n{}".format(error_msg[:500]))

            # 更新状态
            self.state_manager.update_task_status(
                task_info.task_id,
                TaskStatus.COMPLETED.value if exec_result.success else TaskStatus.FAILED.value
            )
            for f in (exec_result.output_files or []):
                self.state_manager.add_file_change(f, "modified", "Claude")

            # ========== 生成任务 Markdown 文档 ==========
            self._generate_task_document(task_info, refined, exec_result)

            # ========== 保存交互到长期记忆 ==========
            self._save_to_memory(task_info, exec_result)

        except Exception as e:
            self.log.error("任务处理失败: {}".format(e))
            self._reply_to_user(task_info, "处理任务失败: {}".format(str(e)[:500]))
            self.state_manager.record_error(str(e))
            self.state_manager.update_task_status(task_info.task_id, TaskStatus.FAILED.value)

    def _generate_task_document(self, task_info, refined, exec_result):
        """生成任务 Markdown 文档"""
        try:
            doc_path = create_task_doc_from_result(
                task_id=task_info.task_id,
                original_prompt=task_info.original_prompt,
                refined_prompt=refined.refined_prompt,
                exec_result=exec_result,
                task_info=task_info,
                tasks_dir="./tasks",
                project_root="."
            )
            self.log.info("📄 任务文档已生成: {}".format(doc_path))
        except Exception as doc_err:
            self.log.error("生成任务文档失败: {}".format(doc_err))

    def _save_to_memory(self, task_info, exec_result):
        """保存交互到长期记忆"""
        try:
            # 获取用户 ID
            user_id = task_info.sender or "unknown"

            # 获取会话 ID
            session_id = task_info.metadata.get("session_id", "") if task_info.metadata else ""

            # 创建交互历史
            from src.core.memory.long_term import InteractionHistory
            history = InteractionHistory(
                session_id=task_info.task_id,
                user_id=user_id,
                task_summary=task_info.original_prompt[:200],
                outcome="success" if exec_result.success else "failed",
                file_changes={
                    "created": exec_result.created_files or [],
                    "modified": exec_result.modified_files or []
                },
                duration_seconds=exec_result.duration
            )

            # 保存到长期记忆
            if hasattr(self, 'long_term_memory'):
                self.long_term_memory.add_history(history)

            self.log.info("🧠 交互历史已保存到记忆系统")
        except Exception as mem_err:
            self.log.error("保存到记忆失败: {}".format(mem_err))

    def _handle_execution_result(
        self,
        task_info: TaskInfo,
        exec_result: ExecutionResult,
        original_task: TaskInfo = None
    ):
        """
        处理执行结果（回复用户、生成报告等）
        """
        try:
            # 记录详细执行结果
            stdout_len = len(exec_result.stdout) if exec_result.stdout else 0
            stderr_len = len(exec_result.stderr) if exec_result.stderr else 0
            self.log.info("执行结果: success={}, exit_code={}, stdout_len={}, stderr_len={}".format(
                exec_result.success, getattr(exec_result, 'exit_code', 'N/A'), stdout_len, stderr_len))

            # 直接打印内容摘要
            if exec_result.stdout:
                preview = exec_result.stdout[:100].replace('\n', ' ')
                self.log.info("stdout预览: {}...".format(preview))
            if exec_result.stderr:
                preview = exec_result.stderr[:100].replace('\n', ' ')
                self.log.info("stderr预览: {}...".format(preview))

            # 超时智能处理（健康监控版本）
            if not exec_result.success and exec_result.error:
                error_lower = exec_result.error.lower()
                if "timed out" in error_lower or "无响应" in exec_result.error:
                    self.log.info("检测到执行中断，检查是否有输出...")
                    if exec_result.stdout and len(exec_result.stdout.strip()) > 0:
                        exec_result.success = True
                        exec_result.error = ""
                        self.log.info("实际已完成，忽略中断")
                    else:
                        # 健康监控触发的中断
                        self.log.warning("进程无响应，已被健康监控系统中断")

            elapsed = exec_result.duration if hasattr(exec_result, 'duration') else 0
            self.log.info("完成: {}, {}秒".format(exec_result.success, elapsed))

            # 回复用户（通过原渠道）
            if exec_result.success:
                output = exec_result.stdout.strip() if exec_result.stdout else "任务完成"

                # 检查文件是否创建
                output_files = exec_result.output_files or []
                if output_files:
                    file_info = "\n已创建文件：\n" + "\n".join("- " + f for f in output_files)
                else:
                    file_info = ""

                # ========== 生成 HTML 报告（回复之前生成） ==========
                report_path = None
                try:
                    # 创建 RefinedResult 对象用于报告生成
                    refined_result = RefinedResult(
                        refined_prompt=original_task.refined_prompt if original_task else "",
                        confidence=original_task.confidence if original_task else 0.0,
                        intent_type="continue" if original_task else "new_task"
                    )

                    # 使用 original_task 或 task_info 作为任务信息
                    report_task = original_task or task_info

                    # 生成 HTML 报告
                    report_path = self.html_generator.generate(
                        task=report_task,
                        refined=refined_result,
                        exec_result=exec_result
                    )
                    self.log.info("HTML 报告已生成: {}".format(report_path))

                    # 如果是 GitHub Pages 模式，推送到 GitHub
                    if self.github_pusher:
                        github_url, success = self.github_pusher.push_report_file(
                            file_path=report_path,
                            task_id=report_task.task_id
                        )
                        if success:
                            self.log.info("报告已推送到 GitHub: {}".format(github_url))
                            report_task.report_url = github_url
                except Exception as report_err:
                    self.log.error("生成报告失败: {}".format(report_err))

                # Telegram 消息长度限制
                if len(output) + len(file_info) > 3000:
                    output = output[:2500] + "\n\n...（详细内容见附件）"

                # 添加报告链接
                report_info = ""
                if original_task and hasattr(original_task, 'report_url') and original_task.report_url:
                    report_info = "\n\n📊 完整报告: {}".format(original_task.report_url)
                elif report_path:
                    report_info = "\n\n📊 报告文件: {}".format(str(report_path))

                self._reply_to_user(task_info, "任务完成\n\n{}{}{}".format(output, file_info, report_info))
            else:
                error_msg = exec_result.stderr or exec_result.error or "执行失败"
                is_timeout = ("timed out" in error_msg.lower() or "无响应" in error_msg) and exec_result.stdout
                if is_timeout:
                    output = exec_result.stdout.strip() if exec_result.stdout else ""
                    if output:
                        self._reply_to_user(task_info, "部分完成（进程中断）\n\n{}".format(output[:3000]))
                    else:
                        self._reply_to_user(task_info, "任务超时")
                else:
                    self._reply_to_user(task_info, "任务失败\n\n{}".format(error_msg[:500]))

            # 更新原始任务状态
            if original_task:
                self.state_manager.update_task_status(
                    original_task.task_id,
                    TaskStatus.COMPLETED.value if exec_result.success else TaskStatus.FAILED.value
                )
                for f in (exec_result.output_files or []):
                    self.state_manager.add_file_change(f, "modified", "Claude")

        except Exception as e:
            self.log.error("处理失败: {}".format(e))
            self._reply_to_user(task_info, "处理任务失败: {}".format(str(e)[:500]))
            self.state_manager.record_error(str(e))
            self.state_manager.update_task_status(task_info.task_id, TaskStatus.FAILED.value)

    def _sleep(self, seconds=None):
        seconds = seconds or self.settings.task.poll_interval
        for _ in range(seconds * 10):
            if self._shutdown_requested:
                break
            import time
            time.sleep(0.1)

    def _handle_shutdown(self, signum, frame):
        self.log.info("停止信号")
        self._shutdown_requested = True

    def _cleanup(self):
        self.log.info("清理...")
        try:
            self.email_listener.disconnect()
            self.email_channel.disconnect()
            if self.telegram_channel:
                self.telegram_channel.disconnect()
        except:
            pass
        self.state_manager.update_status("idle")
        self._running = False
        self.log.info("已停止")

    def shutdown(self):
        self._shutdown_requested = True


def main():
    app = HermesApplication()
    app.run()


if __name__ == "__main__":
    main()
