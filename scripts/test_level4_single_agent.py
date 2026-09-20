"""Level 4：单个 Agent 冒烟测试（user_intent）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kg_builder.agents.user_intent import build_user_intent_agent
from kg_builder.core.agent_runner import make_agent_caller
from kg_builder.state import APPROVED_USER_GOAL, PERCEIVED_USER_GOAL


async def main():
    print("=" * 60)
    print("Level 4: user_intent Agent 冒烟测试")
    print("=" * 60)

    # 1. 创建 Agent
    agent = build_user_intent_agent()
    print(f"✅ Agent 已创建: {agent.name}")

    # 2. 创建 caller（这里不带 initial_state）
    caller = await make_agent_caller(agent)
    print(f"✅ Caller 已创建")

    # 3. 第一轮对话：描述目标
    print("\n" + "-" * 60)
    print("第 1 轮：描述目标")
    print("-" * 60)
    resp1 = await caller.chat(
        "我想要一个物料清单图谱，包含从供应商到成品的各个层级，支持根本原因分析。"
    )
    print(f"\n🤖 Agent:\n{resp1[:400]}...")

    # 4. 检查 state
    session = await caller.get_session()
    print(f"\n📊 当前 state 键: {list(session.state.keys())}")

    # 5. 第二轮对话：批准
    print("\n" + "-" * 60)
    print("第 2 轮：批准目标")
    print("-" * 60)
    resp2 = await caller.chat("批准那个目标。")
    print(f"\n🤖 Agent:\n{resp2[:400]}...")

    # 6. 最终检查
    session = await caller.get_session()
    state = session.state

    print("\n" + "=" * 60)
    print("最终状态检查")
    print("=" * 60)

    if APPROVED_USER_GOAL in state:
        print(f"✅ approved_user_goal: {state[APPROVED_USER_GOAL]}")
        print("\n✅ Level 4 通过")
    elif PERCEIVED_USER_GOAL in state:
        print(f"⚠️  只设置了 perceived_user_goal，说明 Agent 还没批准")
        print(f"   {state[PERCEIVED_USER_GOAL]}")
        print("   可以再发一次 '批准那个目标。' 试试")
    else:
        print("❌ 没有设置任何目标，Agent 可能没按预期调用工具")
        print(f"   State 内容: {state}")


if __name__ == "__main__":
    asyncio.run(main())