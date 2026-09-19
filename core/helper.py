import os
from dotenv import load_dotenv, find_dotenv
from google.adk.agents import Agent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
from typing import Optional, Dict, Any


def load_env():
    _ = load_dotenv(find_dotenv())


def get_neo4j_import_dir():
    """从环境变量中获取 Neo4j 导入目录"""
    load_env()
    # 如果环境变量没配置，默认使用当前目录下的 data/import
    neo4j_import_dir = os.getenv("NEO4J_IMPORT_DIR", "./data/import")

    # 确保目录存在
    os.makedirs(neo4j_import_dir, exist_ok=True)
    return neo4j_import_dir


class AgentCaller:
    """包装了 Runner 和 Session，方便与前端交互"""

    def __init__(
            self, agent: Agent, runner: Runner, user_id: str,
            session_id: str, session_service: InMemorySessionService,
            app_name: Optional[str] = None
    ):
        self.app_name = app_name if app_name else agent.name
        self.agent = agent
        self.user_id = user_id
        self.session_id = session_id
        self.runner = runner
        self.session_service = session_service
        self.session = None

    async def get_session(self):
        """获取当前状态记忆"""
        return await self.runner.session_service.get_session(
            app_name=self.runner.app_name,
            user_id=self.user_id,
            session_id=self.session_id
        )


async def make_agent_caller(
        agent: Agent,
        app_name: Optional[str] = None,
        initial_state: Optional[Dict[str, Any]] = None,
) -> AgentCaller:
    """创建 AgentCaller 实例，准备好 runner 和 session_service"""
    app_name = app_name or f"{agent.name}_app"
    user_id = f"{agent.name}_user"
    session_id = f"{agent.name}_session"

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=initial_state
    )

    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )

    return AgentCaller(
        agent=agent,
        runner=runner,
        user_id=user_id,
        session_id=session_id,
        session_service=session_service,
        app_name=app_name,
    )