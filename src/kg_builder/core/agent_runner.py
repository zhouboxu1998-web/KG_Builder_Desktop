"""
封装 Google ADK 的 Runner / Session。

本模块同时负责：

    1. ADK AgentCaller
    2. Session 创建
    3. ADK Event 解析
    4. Runtime 可观测性
    5. Reasoning 泄漏过滤

Reasoning 泄漏过滤（保守版）：
    只在开头明确是推理句式时才切。

    特征：
        - "The user ..."
        - "I should ..."
        - "Let me ..."
        - "First, I ..."
        - "Okay, ..." / "Hmm, ..." / "Wait, ..."

    切到第一个空行就停。
    遇到中文立即停。
    其他情况原样返回。
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable, Dict, Optional

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from kg_builder import config
from kg_builder.core.errors import AgentExecutionError, KGBuilderError, OperationTimeoutError
from kg_builder.core.logger import logged_operation
from kg_builder.core.retry import RetryPolicy, TimeoutPolicy, run_async_with_policy

from kg_builder.core.runtime import (
    AgentRuntime,
    default_runtime,
)


# ============================================================
# 明确推理句式
# ============================================================

_REASONING_PATTERNS = [
    re.compile(
        r"^The user\s+(?:just|is|said|wants|asks|has)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^I\s+(?:should|need|will|must|can|am going to|have to)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Let me\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"^First,\s+I\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Okay,\s+(?:I|let)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Hmm,\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Wait,\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Alright,\s+(?:I|let)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Now,\s+I\s+",
        re.IGNORECASE,
    ),
]


def _looks_like_reasoning(text: str) -> bool:
    """判断文本开头是否像推理。"""
    if not text:
        return False

    first_line = text.split(
        "\n",
        1,
    )[0].strip()

    for pattern in _REASONING_PATTERNS:
        if pattern.match(first_line):
            return True

    return False


def _strip_reasoning(text: str) -> str:
    """
    剥离 LLM reasoning 泄漏。

    这是一个保守实现：

        如果不像 reasoning：
            原样返回

        如果像 reasoning：
            尝试寻找正式回答的起点

    宁可少过滤，也不要误删正常回答。
    """
    if not text:
        return text

    stripped = text.lstrip()

    if not _looks_like_reasoning(stripped):
        return text

    lines = stripped.split("\n")

    for i, line in enumerate(lines):
        s = line.strip()

        # 空行通常意味着 reasoning 与正式回答之间的段落分隔。
        if not s:
            rest = "\n".join(
                lines[i + 1:]
            ).strip()

            if rest:
                return rest

            break

        # 中文内容通常已经进入正式回答。
        if any(
            "\u4e00" <= ch <= "\u9fff"
            for ch in s
        ):
            rest = "\n".join(
                lines[i:]
            ).strip()

            if rest:
                return rest

            break

        # Markdown 结构通常意味着正式输出开始。
        if s.startswith(
            (
                "#",
                "- ",
                "* ",
                "|",
                "```",
                "1. ",
                "2. ",
            )
        ):
            rest = "\n".join(
                lines[i:]
            ).strip()

            if rest:
                return rest

            break

        # 最多检查前 5 行。
        if i >= 5:
            return text

    return text


# ============================================================
# AgentCaller
# ============================================================

class AgentCaller:
    """
    一个 Agent + 一个 ADK Session 的轻量封装。

    Phase 1 新增：

        - runtime
        - run_id
        - execution timing
        - ADK Event tracking
        - error tracking

    原有调用方式保持兼容：

        caller = await make_agent_caller(agent)

        response = await caller.chat("...")
    """

    def __init__(
        self,
        agent: Agent,
        runner: Runner,
        user_id: str,
        session_id: str,
        session_service: InMemorySessionService,
        app_name: str,
        runtime: Optional[AgentRuntime] = None,
        run_id: Optional[str] = None,
        stage: Optional[str] = None,
        retry_policy: Optional[RetryPolicy] = None,
        timeout_policy: Optional[TimeoutPolicy] = None,
    ):
        self.agent = agent
        self.runner = runner

        self.user_id = user_id
        self.session_id = session_id
        self.session_service = session_service
        self.app_name = app_name

        # Runtime
        self.runtime = runtime or default_runtime

        # 如果外部没有指定，则每个 Caller 自己创建一个 Run。
        self.run_id = run_id or self.runtime.start_run(
            agent_name=self.agent.name,
            stage=stage,
        )

        self.stage = stage

        # Phase 1-C：统一 Retry / Timeout 策略。
        # 默认最大尝试次数为 1，保持已有 Agent 行为不变。
        self.retry_policy = retry_policy or RetryPolicy(
            max_attempts=config.KG_RETRY_MAX_ATTEMPTS,
            initial_delay=config.KG_RETRY_INITIAL_DELAY,
            max_delay=config.KG_RETRY_MAX_DELAY,
            multiplier=config.KG_RETRY_BACKOFF_MULTIPLIER,
            jitter=config.KG_RETRY_JITTER,
        )

        self.timeout_policy = timeout_policy or TimeoutPolicy(
            timeout_seconds=config.AGENT_TIMEOUT_SECONDS,
        )

    # ========================================================
    # Chat
    # ========================================================

    async def _chat_once(
        self,
        user_input: str,
        verbose: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        向 Agent 发送一条消息。

        Runtime 会记录：

            agent_started
                ↓
            adk_event
                ↓
            adk_event
                ↓
            agent_finished

        如果出现异常：

            agent_error
        """

        message = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=user_input
                )
            ],
        )

        final_text = ""

        start_time = time.perf_counter()

        self.runtime.agent_started(
            run_id=self.run_id,
            agent_name=self.agent.name,
            stage=self.stage,
        )

        try:
            async for event in self.runner.run_async(
                user_id=self.user_id,
                session_id=self.session_id,
                new_message=message,
            ):
                # ------------------------------------------------
                # Runtime Event
                # ------------------------------------------------

                self.runtime.adk_event(
                    run_id=self.run_id,
                    event=event,
                    agent_name=self.agent.name,
                    stage=self.stage,
                )

                if verbose:
                    print(
                        f"[Event] "
                        f"run={self.run_id} "
                        f"author={event.author} "
                        f"final={event.is_final_response()} "
                        f"partial={getattr(event, 'partial', False)}"
                    )

                # ------------------------------------------------
                # 提取文本
                # ------------------------------------------------

                text = ""

                if event.content and event.content.parts:
                    for part in event.content.parts:
                        t = getattr(
                            part,
                            "text",
                            None,
                        )

                        if t:
                            text += t

                if text:
                    is_partial = bool(
                        getattr(
                            event,
                            "partial",
                            False,
                        )
                    )

                    # Streaming
                    if is_partial and on_chunk:
                        on_chunk(text)

                    # 最终响应
                    if event.is_final_response():
                        final_text = text

                    # Partial response
                    elif is_partial:
                        final_text += text

                # ------------------------------------------------
                # ADK escalate
                # ------------------------------------------------

                actions = getattr(
                    event,
                    "actions",
                    None,
                )

                if (
                    actions
                    and getattr(
                        actions,
                        "escalate",
                        False,
                    )
                ):
                    break

            # ----------------------------------------------------
            # Reasoning 过滤
            # ----------------------------------------------------

            cleaned = _strip_reasoning(
                final_text
            )

            elapsed_ms = (
                time.perf_counter()
                - start_time
            ) * 1000

            self.runtime.agent_finished(
                run_id=self.run_id,
                agent_name=self.agent.name,
                duration_ms=elapsed_ms,
                stage=self.stage,
            )

            if verbose:
                if cleaned != final_text:
                    print(
                        "[AgentCaller] "
                        f"剥离 reasoning："
                        f"{len(final_text)} → "
                        f"{len(cleaned)} 字符"
                    )
                else:
                    print(
                        "[AgentCaller] "
                        "无 reasoning 需要剥离"
                    )

                print(
                    "[AgentCaller] "
                    f"duration={elapsed_ms:.2f}ms"
                )

            return cleaned

        except KGBuilderError as exc:
            elapsed_ms = (
                time.perf_counter()
                - start_time
            ) * 1000

            self.runtime.agent_error(
                run_id=self.run_id,
                agent_name=self.agent.name,
                error=exc,
                duration_ms=elapsed_ms,
                stage=self.stage,
            )

            raise

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter()
                - start_time
            ) * 1000

            wrapped = AgentExecutionError.from_exception(
                exc,
                message=(
                    f"Agent {self.agent.name} 执行失败。"
                ),
                details={
                    "agent": self.agent.name,
                    "stage": self.stage,
                },
            )

            self.runtime.agent_error(
                run_id=self.run_id,
                agent_name=self.agent.name,
                error=wrapped,
                duration_ms=elapsed_ms,
                stage=self.stage,
            )

            raise wrapped from exc

    @logged_operation("agent_caller.chat")
    async def chat(
        self,
        user_input: str,
        verbose: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        带统一 Retry / Timeout 策略的 Agent 调用。

        注意：
            Agent Tool 可能具有副作用，因此默认 max_attempts=1。
            如需启用 Agent 重试，应只针对已经确认幂等的 Agent 流程开启。
        """

        try:
            return await run_async_with_policy(
                self._chat_once,
                user_input,
                verbose=verbose,
                on_chunk=on_chunk,
                retry_policy=self.retry_policy,
                timeout_policy=self.timeout_policy,
                operation_name=f"agent:{self.agent.name}",
            )

        except OperationTimeoutError:
            raise

        except TimeoutError as error:
            wrapped = OperationTimeoutError(
                f"Agent {self.agent.name} 执行超时。",
                details={
                    "agent": self.agent.name,
                    "stage": self.stage,
                    "timeout_seconds": self.timeout_policy.timeout_seconds,
                },
                cause=error,
            )

            self.runtime.agent_error(
                run_id=self.run_id,
                agent_name=self.agent.name,
                error=wrapped,
                stage=self.stage,
            )

            raise wrapped from error

    # ========================================================
    # Session
    # ========================================================

    async def get_session(self):
        """获取当前 ADK Session。"""
        return await self.runner.session_service.get_session(
            app_name=self.runner.app_name,
            user_id=self.user_id,
            session_id=self.session_id,
        )

    # ========================================================
    # Runtime
    # ========================================================

    def get_runtime_events(self):
        """获取当前 Agent Caller 的全部 Runtime Events。"""
        return self.runtime.get_run_events(
            self.run_id
        )

    def get_run_summary(self) -> Dict[str, Any]:
        """
        返回当前 Run 的简单统计。

        这个接口后面会直接用于 UI。
        """

        events = self.get_runtime_events()

        errors = [
            event
            for event in events
            if event.event_type == "agent_error"
        ]

        finished = [
            event
            for event in events
            if event.event_type == "agent_finished"
        ]

        duration_ms = None

        if finished:
            duration_ms = finished[-1].duration_ms

        return {
            "run_id": self.run_id,
            "agent": self.agent.name,
            "stage": self.stage,
            "event_count": len(events),
            "error_count": len(errors),
            "duration_ms": duration_ms,
            "status": (
                "error"
                if errors
                else "success"
            ),
        }


# ============================================================
# 工厂
# ============================================================

async def make_agent_caller(
    agent: Agent,
    app_name: Optional[str] = None,
    initial_state: Optional[Dict[str, Any]] = None,
    runtime: Optional[AgentRuntime] = None,
    run_id: Optional[str] = None,
    stage: Optional[str] = None,
    retry_policy: Optional[RetryPolicy] = None,
    timeout_policy: Optional[TimeoutPolicy] = None,
) -> AgentCaller:
    """
    创建 AgentCaller。

    新增参数：

        runtime:
            指定 Runtime。

        run_id:
            允许多个 Agent 共享同一个 Run ID。

        stage:
            标识当前 Agent 所属 Pipeline 阶段。

    旧代码：

        await make_agent_caller(agent)

    仍然完全兼容。
    """

    app_name = (
        app_name
        or f"{agent.name}_app"
    )

    user_id = (
        f"{agent.name}_user"
    )

    session_id = (
        f"{agent.name}_session"
    )

    service = InMemorySessionService()

    await service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=initial_state or {},
    )

    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=service,
    )

    return AgentCaller(
        agent=agent,
        runner=runner,
        user_id=user_id,
        session_id=session_id,
        session_service=service,
        app_name=app_name,
        runtime=runtime,
        run_id=run_id,
        stage=stage,
        retry_policy=retry_policy,
        timeout_policy=timeout_policy,
    )