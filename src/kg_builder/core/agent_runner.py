"""封装 Google ADK 的 Runner / Session。

Reasoning 泄漏过滤（保守版）：
    只在**开头明确是推理句式**时才切。
    特征：
        - "The user ..."
        - "I should ..."
        - "Let me ..."
        - "First, I ..."
        - "Okay, ..." / "Hmm, ..." / "Wait, ..."

    切到**第一个空行**就停。
    遇到中文立即停。
    其他情况原样返回（宁可留泄漏，也不误删内容）。
"""

import re
from typing import Any, Callable, Dict, Optional

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


# ============================================================
# 明确推理句式（大小写不敏感）
# ============================================================
_REASONING_PATTERNS = [
    re.compile(r"^The user\s+(?:just|is|said|wants|asks|has)", re.IGNORECASE),
    re.compile(r"^I\s+(?:should|need|will|must|can|am going to|have to)", re.IGNORECASE),
    re.compile(r"^Let me\s+", re.IGNORECASE),
    re.compile(r"^First,\s+I\s+", re.IGNORECASE),
    re.compile(r"^Okay,\s+(?:I|let)", re.IGNORECASE),
    re.compile(r"^Hmm,\s+", re.IGNORECASE),
    re.compile(r"^Wait,\s+", re.IGNORECASE),
    re.compile(r"^Alright,\s+(?:I|let)", re.IGNORECASE),
    re.compile(r"^Now,\s+I\s+", re.IGNORECASE),
]


def _looks_like_reasoning(text: str) -> bool:
    """判断文本开头是否像推理。"""
    if not text:
        return False
    first_line = text.split("\n", 1)[0].strip()
    for pat in _REASONING_PATTERNS:
        if pat.match(first_line):
            return True
    return False


def _strip_reasoning(text: str) -> str:
    """剥离 LLM 推理泄漏（保守版）。

    只在**开头明确是推理句式**时切，遇到第一个空行就停。
    其他情况**原样返回**。
    """
    if not text:
        return text

    stripped = text.lstrip()

    # 不以推理句式开头 → 原样返回
    if not _looks_like_reasoning(stripped):
        return text

    # 找第一个空行（\n\n）作为切分点
    lines = stripped.split("\n")

    for i, line in enumerate(lines):
        s = line.strip()

        # 遇到空行 → 认为是段落分隔
        if not s:
            rest = "\n".join(lines[i + 1:]).strip()
            if rest:
                return rest
            break

        # 遇到中文 → 认为正式内容开始
        if any("\u4e00" <= ch <= "\u9fff" for ch in s):
            rest = "\n".join(lines[i:]).strip()
            if rest:
                return rest
            break

        # 遇到 markdown 结构 → 认为正式内容开始
        if s.startswith(("#", "- ", "* ", "|", "```", "1. ", "2. ")):
            rest = "\n".join(lines[i:]).strip()
            if rest:
                return rest
            break

        # 只检查前 5 行（超过就不是纯推理了）
        if i >= 5:
            return text

    # 兜底：没找到切分点 → 原样返回（宁可留泄漏）
    return text


# ============================================================
# AgentCaller
# ============================================================

class AgentCaller:
    """一个 Agent + 一个会话的轻量封装。"""

    def __init__(
        self,
        agent: Agent,
        runner: Runner,
        user_id: str,
        session_id: str,
        session_service: InMemorySessionService,
        app_name: str,
    ):
        self.agent = agent
        self.runner = runner
        self.user_id = user_id
        self.session_id = session_id
        self.session_service = session_service
        self.app_name = app_name

    async def chat(
        self,
        user_input: str,
        verbose: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        message = types.Content(
            role="user", parts=[types.Part(text=user_input)]
        )

        final_text = ""

        async for event in self.runner.run_async(
            user_id=self.user_id,
            session_id=self.session_id,
            new_message=message,
        ):
            if verbose:
                print(
                    f"[Event] author={event.author} "
                    f"final={event.is_final_response()} "
                    f"partial={getattr(event, 'partial', False)}"
                )

            text = ""
            if event.content and event.content.parts:
                for part in event.content.parts:
                    t = getattr(part, "text", None)
                    if t:
                        text += t

            if text:
                is_partial = bool(getattr(event, "partial", False))

                if is_partial and on_chunk:
                    on_chunk(text)

                if event.is_final_response():
                    final_text = text
                elif is_partial:
                    final_text += text

            if getattr(event, "actions", None) and getattr(
                event.actions, "escalate", False
            ):
                break

        # 过滤 reasoning 泄漏
        cleaned = _strip_reasoning(final_text)

        if verbose:
            if cleaned != final_text:
                print(
                    f"[AgentCaller] 剥离 reasoning："
                    f"{len(final_text)} → {len(cleaned)} 字符"
                )
            else:
                print(f"[AgentCaller] 无 reasoning 需要剥离")

        return cleaned

    async def get_session(self):
        return await self.runner.session_service.get_session(
            app_name=self.runner.app_name,
            user_id=self.user_id,
            session_id=self.session_id,
        )


# ============================================================
# 工厂
# ============================================================

async def make_agent_caller(
    agent: Agent,
    app_name: Optional[str] = None,
    initial_state: Optional[Dict[str, Any]] = None,
) -> AgentCaller:
    app_name = app_name or f"{agent.name}_app"
    user_id = f"{agent.name}_user"
    session_id = f"{agent.name}_session"

    service = InMemorySessionService()
    await service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=initial_state or {},
    )
    runner = Runner(app_name=app_name, agent=agent, session_service=service)
    return AgentCaller(
        agent=agent,
        runner=runner,
        user_id=user_id,
        session_id=session_id,
        session_service=service,
        app_name=app_name,
    )