"""端到端测试：一次跑完 5 个阶段，验证整条流水线是否工作。

用途：
    在项目根目录执行：python test_pipeline.py
    或在 PyCharm 中右键 → Run 'test_pipeline'

前提：
    - 已执行 pip install -e .
    - .env 已正确配置（DEEPSEEK_API_KEY / NEO4J_*）
    - data/import/ 下已有 CSV / Markdown 数据文件
    - Neo4j 已启动（本脚本不依赖 Neo4j，但下游 build 阶段会用到）
"""

import asyncio
import json
import sys
import traceback
from pathlib import Path

# 把 src/ 加入模块搜索路径（因为脚本和 src 平级）
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kg_builder.agents.pipeline import KGBuilderPipeline


# ============================================================
# 工具函数：美化输出
# ============================================================

def _sep(char="=", width=72):
    print(char * width)


def _print_state(label: str, state: dict, keys: list, max_len: int = 200):
    """只打印指定的几个键，超长自动截断。"""
    print(f"\n📊 {label}")
    for k in keys:
        if k not in state:
            print(f"   {k}: (缺失)")
            continue
        v = state[k]
        s = json.dumps(v, ensure_ascii=False)
        if len(s) > max_len:
            s = s[:max_len] + f"...(共 {len(s)} 字符)"
        print(f"   {k}: {s}")


def _check_keys(state: dict, required: list, stage_name: str) -> bool:
    """检查 state 是否包含所有必需的键。"""
    missing = [k for k in required if k not in state]
    if missing:
        print(f"\n❌ [{stage_name}] 缺少必需的 state 键: {missing}")
        return False
    print(f"✅ [{stage_name}] 通过")
    return True


# ============================================================
# 主流程
# ============================================================

async def run_pipeline() -> bool:
    _sep()
    print("🚀 端到端流水线测试")
    _sep()

    pipeline = KGBuilderPipeline(max_schema_iterations=2)

    # ========================================================
    # 阶段 ① 用户意图
    # ========================================================
    _sep("-")
    print("阶段 ① 用户意图")
    _sep("-")

    try:
        caller = await pipeline.start_intent()
        user_goal_prompt = (
            "我想要一个物料清单图谱（BOM），它包含从供应商到成品的各个层级，"
            "并能支持根本原因分析。"
        )
        print(f"\n👤 输入: {user_goal_prompt}")
        resp = await caller.chat(user_goal_prompt)
        print(f"\n🤖 {resp[:300]}{'...' if len(resp) > 300 else ''}")

        # 用户批准
        print(f"\n👤 输入: 批准那个目标。")
        resp = await caller.chat("批准那个目标。")
        print(f"\n🤖 {resp[:200]}{'...' if len(resp) > 200 else ''}")

        await pipeline.finalize_intent()
        state = await pipeline.get_current_state("intent")
        _print_state("阶段 ① 结束状态", state, ["approved_user_goal"])

        if not _check_keys(state, ["approved_user_goal"], "阶段 ①"):
            return False
    except Exception as e:
        print(f"\n❌ 阶段 ① 异常: {e}")
        traceback.print_exc()
        return False

    # ========================================================
    # 阶段 ② 文件选择
    # ========================================================
    _sep("-")
    print("阶段 ② 文件选择")
    _sep("-")

    try:
        caller = await pipeline.start_file_selection()
        print(f"\n👤 输入: 我们能用哪些文件进行导入？")
        resp = await caller.chat("我们能用哪些文件进行导入？")
        print(f"\n🤖 {resp[:400]}{'...' if len(resp) > 400 else ''}")

        # 用户批准
        print(f"\n👤 输入: 好的，就这么做！")
        resp = await caller.chat("好的，就这么做！")
        print(f"\n🤖 {resp[:200]}{'...' if len(resp) > 200 else ''}")

        await pipeline.finalize_file_selection()
        state = await pipeline.get_current_state("files")
        _print_state("阶段 ② 结束状态", state, ["approved_files"])

        if not _check_keys(state, ["approved_files"], "阶段 ②"):
            return False
    except Exception as e:
        print(f"\n❌ 阶段 ② 异常: {e}")
        traceback.print_exc()
        return False

    # ========================================================
    # 阶段 ③ Schema 提议 / 审查循环
    # ========================================================
    _sep("-")
    print("阶段 ③ Schema 提议 / 审查循环")
    _sep("-")

    try:
        caller = await pipeline.start_schema_proposal()
        print(f"\n👤 输入: 如何导入这些文件来构建知识图谱？")
        resp = await caller.chat("如何导入这些文件来构建知识图谱？")
        print(f"\n🤖 {resp[:400]}{'...' if len(resp) > 400 else ''}")

        await pipeline.finalize_schema_proposal()
        state = await pipeline.get_current_state("schema")
        _print_state(
            "阶段 ③ 结束状态",
            state,
            ["proposed_construction_plan", "feedback"],
            max_len=500,
        )

        if not _check_keys(
            state, ["proposed_construction_plan"], "阶段 ③"
        ):
            return False
    except Exception as e:
        print(f"\n❌ 阶段 ③ 异常: {e}")
        traceback.print_exc()
        return False

    # ========================================================
    # 阶段 ④ NER
    # ========================================================
    _sep("-")
    print("阶段 ④ NER（命名实体识别）")
    _sep("-")

    try:
        caller = await pipeline.start_ner()
        ner_prompt = (
            "将产品评论添加到知识图谱中，以便追溯产品投诉的根本原因。"
        )
        print(f"\n👤 输入: {ner_prompt}")
        resp = await caller.chat(ner_prompt)
        print(f"\n🤖 {resp[:400]}{'...' if len(resp) > 400 else ''}")

        # 用户批准
        print(f"\n👤 输入: 批准这些建议的实体。")
        resp = await caller.chat("批准这些建议的实体。")
        print(f"\n🤖 {resp[:200]}{'...' if len(resp) > 200 else ''}")

        await pipeline.finalize_ner()
        state = await pipeline.get_current_state("ner")
        _print_state(
            "阶段 ④ 结束状态",
            state,
            ["approved_entity_types"],
        )

        if not _check_keys(
            state, ["approved_entity_types"], "阶段 ④"
        ):
            return False
    except Exception as e:
        print(f"\n❌ 阶段 ④ 异常: {e}")
        traceback.print_exc()
        return False

    # ========================================================
    # 阶段 ⑤ 事实类型
    # ========================================================
    _sep("-")
    print("阶段 ⑤ 事实类型")
    _sep("-")

    try:
        caller = await pipeline.start_fact()
        print(f"\n👤 输入: 建议可以从文本中找到的事实类型。")
        resp = await caller.chat("建议可以从文本中找到的事实类型。")
        print(f"\n🤖 {resp[:400]}{'...' if len(resp) > 400 else ''}")

        # 用户批准
        print(f"\n👤 输入: 批准这些建议的事实类型。")
        resp = await caller.chat("批准这些建议的事实类型。")
        print(f"\n🤖 {resp[:200]}{'...' if len(resp) > 200 else ''}")

        await pipeline.finalize_fact()
        state = await pipeline.get_current_state("fact")
        _print_state(
            "阶段 ⑤ 结束状态",
            state,
            ["approved_fact_types"],
            max_len=500,
        )

        if not _check_keys(state, ["approved_fact_types"], "阶段 ⑤"):
            return False
    except Exception as e:
        print(f"\n❌ 阶段 ⑤ 异常: {e}")
        traceback.print_exc()
        return False

    # ========================================================
    # 总结
    # ========================================================
    _sep()
    print("📋 各阶段最终状态快照")
    _sep()

    snapshot = pipeline.session.snapshot()
    for stage_name in ["intent", "files", "schema", "ner", "fact"]:
        if stage_name not in snapshot:
            print(f"\n--- [{stage_name}] 未执行 ---")
            continue
        state = snapshot[stage_name]
        print(f"\n--- [{stage_name}] ---")
        for k in (
            "approved_user_goal",
            "approved_files",
            "proposed_construction_plan",
            "approved_construction_plan",
            "approved_entity_types",
            "approved_fact_types",
            "feedback",
        ):
            if k in state:
                v = json.dumps(state[k], ensure_ascii=False)
                if len(v) > 150:
                    v = v[:150] + "..."
                print(f"   {k}: {v}")

    _sep()
    print("🎉 端到端流水线测试全部通过！")
    _sep()
    return True


def main():
    try:
        ok = asyncio.run(run_pipeline())
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(130)


if __name__ == "__main__":
    main()