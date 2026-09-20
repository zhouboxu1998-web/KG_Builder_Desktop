"""Level 5：逐阶段测试，验证状态继承。"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kg_builder.agents.pipeline import KGBuilderPipeline


def print_state(label, state, keys):
    print(f"\n📊 {label}")
    for k in keys:
        if k in state:
            v = json.dumps(state[k], ensure_ascii=False)
            if len(v) > 150:
                v = v[:150] + "..."
            print(f"   {k}: {v}")


async def main():
    print("=" * 70)
    print("Level 5: 逐阶段验证")
    print("=" * 70)

    pipeline = KGBuilderPipeline()

    # ============ 阶段 ① ============
    print("\n" + "🟦 " * 20)
    print("阶段 ① 用户意图")
    print("🟦 " * 20)
    caller = await pipeline.start_intent()
    await caller.chat(
        "我想要一个物料清单图谱（BOM），包含从供应商到成品的各个层级，"
        "支持根本原因分析。"
    )
    await caller.chat("批准那个目标。")
    await pipeline.finalize_intent()

    state = await pipeline.get_current_state("intent")
    print_state("① 结束状态", state, ["approved_user_goal"])

    assert "approved_user_goal" in state, "❌ 用户目标未批准"
    print("✅ 阶段 ① 通过")

    input("\n>>> 按回车继续到阶段 ② ...")

    # ============ 阶段 ② ============
    print("\n" + "🟦 " * 20)
    print("阶段 ② 文件选择")
    print("🟦 " * 20)
    caller = await pipeline.start_file_selection()
    await caller.chat("我们能用哪些文件进行导入？")
    await caller.chat("好的，就这么做！")
    await pipeline.finalize_file_selection()

    state = await pipeline.get_current_state("files")
    print_state("② 结束状态", state, ["approved_files"])

    assert "approved_files" in state, "❌ 文件未批准"
    print("✅ 阶段 ② 通过")

    input("\n>>> 按回车继续到阶段 ③ ...")

    # ============ 阶段 ③ ============
    print("\n" + "🟦 " * 20)
    print("阶段 ③ Schema 提议/审查循环")
    print("🟦 " * 20)
    caller = await pipeline.start_schema_proposal()
    await caller.chat("如何导入这些文件来构建知识图谱？")
    await pipeline.finalize_schema_proposal()

    state = await pipeline.get_current_state("schema")
    print_state(
        "③ 结束状态",
        state,
        ["proposed_construction_plan", "feedback"],
    )

    assert "proposed_construction_plan" in state, "❌ 未生成构建计划"
    print("✅ 阶段 ③ 通过")

    input("\n>>> 按回车继续到阶段 ④ ...")

    # ============ 阶段 ④ ============
    print("\n" + "🟦 " * 20)
    print("阶段 ④ NER")
    print("🟦 " * 20)
    caller = await pipeline.start_ner()
    await caller.chat("将产品评论添加到知识图谱中，以便追溯根本原因。")
    await caller.chat("批准这些建议的实体。")
    await pipeline.finalize_ner()

    state = await pipeline.get_current_state("ner")
    print_state("④ 结束状态", state, ["approved_entity_types"])

    assert "approved_entity_types" in state, "❌ 实体未批准"
    print("✅ 阶段 ④ 通过")

    input("\n>>> 按回车继续到阶段 ⑤ ...")

    # ============ 阶段 ⑤ ============
    print("\n" + "🟦 " * 20)
    print("阶段 ⑤ 事实类型")
    print("🟦 " * 20)
    caller = await pipeline.start_fact()
    await caller.chat("建议可以从文本中找到的事实类型。")
    await caller.chat("批准这些建议的事实类型。")
    await pipeline.finalize_fact()

    state = await pipeline.get_current_state("fact")
    print_state("⑤ 结束状态", state, ["approved_fact_types"])

    assert "approved_fact_types" in state, "❌ 事实类型未批准"
    print("✅ 阶段 ⑤ 通过")

    # ============ 总结 ============
    print("\n" + "=" * 70)
    print("🎉 Level 5 全部通过！")
    print("=" * 70)

    snap = pipeline.session.snapshot()
    print("\n各阶段 snapshot 键:")
    for k, v in snap.items():
        print(f"  [{k}] keys: {list(v.keys())}")


if __name__ == "__main__":
    asyncio.run(main())

