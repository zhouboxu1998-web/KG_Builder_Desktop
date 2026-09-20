"""Level 3：工具函数纯逻辑测试（不调用 LLM）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kg_builder.tools.entity_tools import (
    approve_proposed_entities,
    get_approved_entities,
    get_proposed_entities,
    get_well_known_types,
    set_proposed_entities,
)
from kg_builder.tools.fact_tools import (
    add_proposed_fact,
    approve_proposed_facts,
    get_proposed_facts,
)


class FakeToolContext:
    """模拟 ADK 的 ToolContext，只提供 state 字典。"""
    def __init__(self, initial_state=None):
        self.state = initial_state or {}


def test_entity_tools():
    print("\n" + "-" * 60)
    print("3.1 entity_tools 测试")
    print("-" * 60)

    ctx = FakeToolContext()

    # 提议（故意加脏数据）
    r = set_proposed_entities(
        ["Product", " Product ", "Part", "", "Assembly"], ctx
    )
    assert r["status"] == "success"
    assert r["proposed_entity_types"] == ["Product", "Part", "Assembly"]
    print(f"  ✅ 提议 + 清洗: {r['proposed_entity_types']}")

    # 批准
    r = approve_proposed_entities(ctx)
    assert r["status"] == "success"
    print(f"  ✅ 批准: {r['approved_entity_types']}")

    # 读取
    r = get_approved_entities(ctx)
    assert r["approved_entity_types"] == ["Product", "Part", "Assembly"]
    print(f"  ✅ 读取: {r['approved_entity_types']}")

    # 错误路径：空状态批准
    ctx2 = FakeToolContext()
    r = approve_proposed_entities(ctx2)
    assert r["status"] == "error"
    print(f"  ✅ 空状态批准 → 正确报错")

    # get_well_known_types
    ctx3 = FakeToolContext({
        "approved_construction_plan": {
            "Product": {"construction_type": "node", "label": "Product"},
            "Part": {"construction_type": "node", "label": "Part"},
            "CONTAINS": {"construction_type": "relationship", "label": "CONTAINS"},
        }
    })
    r = get_well_known_types(ctx3)
    assert r["approved_labels"] == ["Part", "Product"]
    print(f"  ✅ 提取已知标签（过滤了关系）: {r['approved_labels']}")


def test_fact_tools():
    print("\n" + "-" * 60)
    print("3.2 fact_tools 测试")
    print("-" * 60)

    ctx = FakeToolContext({
        "approved_entity_types": ["Product", "Issue", "Review"],
    })

    # 添加合法事实
    r = add_proposed_fact("Review", "mentions", "Issue", ctx)
    assert r["status"] == "success"
    print(f"  ✅ 添加合法事实: Review -mentions-> Issue")

    # 添加非法事实（宾语不在白名单）
    r = add_proposed_fact("Review", "mentions", "FakeEntity", ctx)
    assert r["status"] == "error"
    print(f"  ✅ 非法宾语 → 正确拒绝")

    # 批准
    r = approve_proposed_facts(ctx)
    assert r["status"] == "success"
    print(f"  ✅ 批准事实: {list(r['approved_fact_types'].keys())}")


def main():
    print("=" * 60)
    print("Level 3: 工具函数纯逻辑测试")
    print("=" * 60)
    test_entity_tools()
    test_fact_tools()
    print("\n" + "=" * 60)
    print("✅ Level 3 全部通过")
    print("=" * 60)


if __name__ == "__main__":
    main()