"""封装 Google ADK 的 Runner / Session，支持真流式输出。

关键改动：
    在 runner.run_async() 中传入 RunConfig(streaming_mode=StreamingMode.SSE)，
    这样 ADK 会 yield partial=True 的增量事件，而非只返回 final event。
"""

from typing import Any, Callable, Dict, Optional

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


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
        streaming: bool = True,          # ★ 新增：是否启用流式
    ):
        self.agent = agent
        self.runner = runner
        self.user_id = user_id
        self.session_id = session_id
        self.session_service = session_service
        self.app_name = app_name
        self.streaming = streaming

    # ========================================================
    # chat（真流式版）
    # ========================================================
    async def chat(
        self,
        user_input: str,
        verbose: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """发送消息并获取回复。

        Args:
            user_input: 用户输入
            verbose: 是否打印每个事件
            on_chunk: 流式增量回调。当 streaming=True 时，
                      每收到一个 partial 文本片段就会调用一次。
                      在 bridge 线程中被调用，UI 层需自行 after(0, ...)。

        Returns:
            完整的最终响应文本。
        """
        message = types.Content(
            role="user", parts=[types.Part(text=user_input)]
        )

        # ★ 关键：构造 RunConfig
        run_config = RunConfig(
            streaming_mode=(
                StreamingMode.SSE if self.streaming
                else StreamingMode.NONE
            ),
        )

        final_text = ""
        has_streamed = False

        async for event in self.runner.run_async(
            user_id=self.user_id,
            session_id=self.session_id,
            new_message=message,
            run_config=run_config,           # ★ 传入 RunConfig
        ):
            if verbose:
                print(
                    f"[Event] author={event.author} "
                    f"final={event.is_final_response()} "
                    f"partial={getattr(event, 'partial', False)}"
                )

            # ---------- 提取文本 ----------
            text = ""
            if event.content and event.content.parts:
                for part in event.content.parts:
                    t = getattr(part, "text", None)
                    if t:
                        text += t

            if text:
                is_partial = bool(getattr(event, "partial", False))
                is_final = bool(event.is_final_response())

                # ★ partial 事件：流式增量
                if is_partial and on_chunk:
                    on_chunk(text)
                    has_streamed = True

                if is_final:
                    final_text = text
                elif is_partial:
                    final_text += text

            # 处理 escalate
            if getattr(event, "actions", None) and getattr(
                event.actions, "escalate", False
            ):
                break

        if verbose:
            print(
                f"[AgentCaller] has_streamed={has_streamed} "
                f"final_len={len(final_text)}"
            )

        return final_text

    # ========================================================
    # get_session
    # ========================================================
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
    streaming: bool = True,              # ★ 新增参数
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
        streaming=streaming,
    )