"""快速版回归：验证新增核心模块之间的基本兼容性。"""
from kg_builder.core.entity_resolution_engine import EntityResolutionConfig, EntityResolutionEngine
from kg_builder.core.evaluation import threshold_sweep
from kg_builder.core.hybrid_retriever import HybridRetriever
from kg_builder.core.tool_runtime import ToolRuntime


def add(a, b):
    return a + b


def main():
    er = EntityResolutionEngine(neo4j_client=object(), config=EntityResolutionConfig(threshold=0.8, review_threshold=0.6))
    report = er.resolve_records(
        [{"id": "s1", "name": "Stockholm Chair", "color": "black"}],
        [{"id": "d1", "name": "stockholm chair", "color": "black"}],
        "name", "name", blocking_key="name", attribute_pairs=[("color", "color")],
    )
    assert report["matched_count"] == 1
    assert threshold_sweep(report["decisions"], [("s1", "d1")], [0.8])[0]["f1"] == 1.0

    fused = HybridRetriever.fuse({"result": [{"id": 1}]}, {"result": [{"id": 2}]})
    assert len(fused["results"]) == 2

    assert ToolRuntime(add).run(a=2, b=3) == 5
    print("🎉 Fast-track completion smoke test 全部通过")


if __name__ == "__main__":
    main()
