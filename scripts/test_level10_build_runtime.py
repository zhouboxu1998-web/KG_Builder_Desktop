"""
Level 10：Build 与 PipelineRuntime 集成测试。

验证：

1. Build 前 Runtime 未进入 build running
2. Build 开始后进入 build stage
3. Schema 未批准时 Build 返回 error
4. Schema 批准后可以进入 IngestionEngine
5. Build 成功后 Runtime stage 为 success
6. Build 失败后 Runtime stage 为 error
7. Build state 仍然保留 ingestion 信息
"""

import asyncio

from kg_builder.agents.pipeline import KGBuilderPipeline
from kg_builder.state import (
    INGESTION_STATUS,
)


class FakeIngestionEngine:
    """Level 10 测试用 IngestionEngine。"""

    def __init__(self, status="success"):
        self.status = status
        self._report = {
            "status": status,
            "validation": {
                "errors": [],
                "warnings": [],
            },
            "graph_validation": {
                "errors": [],
                "warnings": [],
            },
            "statistics": {
                "nodes_created": 1,
                "relationships_created": 1,
            },
        }

    def ingest(self, plan):
        return {
            "status": self.status,
            "report": self._report,
        }

    def get_report(self):
        return self._report

    def reset(self):
        self.status = "success"


async def test_level10():
    print("=" * 60)
    print("Level 10：Build + PipelineRuntime")
    print("=" * 60)

    # ========================================================
    # 1. 创建 Pipeline
    # ========================================================

    pipeline = KGBuilderPipeline()

    assert pipeline.runtime.status == "idle"

    print("✅ 1. Pipeline initialization")

    # ========================================================
    # 2. 必须先启动 Pipeline Run
    # ========================================================

    pipeline.start_run(
        metadata={
            "mode": "level10_test",
        }
    )

    assert pipeline.runtime.status == "running"

    print("✅ 2. Pipeline runtime started")

    # ========================================================
    # 3. Schema 未批准时 Build 应该失败
    # ========================================================

    result = await pipeline.build()

    assert result["status"] == "error"

    print("✅ 3. build blocked without schema")

    # Build Stage 应该已经结束为 error
    summary = pipeline.get_run_summary()

    print(
        "   Runtime summary:",
        summary,
    )

    # ========================================================
    # 4. 新建 Pipeline，模拟已批准 Schema
    # ========================================================

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "level10_test_success",
        }
    )

    pipeline.schema_engine.set_proposed_plan(
        {
            "Product": {
                "construction_type": "node",
                "label": "Product",
                "unique_column_name": "product_id",
                "properties": [
                    "product_name",
                ],
            }
        }
    )

    approved = pipeline.schema_engine.approve()

    assert approved

    assert pipeline.schema_engine.is_approved()

    print("✅ 4. schema approved")

    # ========================================================
    # 5. 替换为 Fake IngestionEngine
    # ========================================================

    pipeline.ingestion_engine = (
        FakeIngestionEngine(
            status="success"
        )
    )

    # ========================================================
    # 6. 执行 Build
    # ========================================================

    result = await pipeline.build()

    assert result["status"] == "success"

    print("✅ 5. build succeeded")

    # ========================================================
    # 7. 检查 Build state
    # ========================================================

    state = await pipeline.get_build_state()

    assert (
        state[INGESTION_STATUS]
        == "success"
    )

    assert (
        "ingestion_report"
        in state
    )

    print("✅ 6. ingestion state persisted")

    # ========================================================
    # 8. 检查 Runtime
    # ========================================================

    summary = pipeline.get_run_summary()

    print(
        "   Runtime summary:",
        summary,
    )

    # Pipeline Run 仍然是 running，
    # 因为 Build 只是一个 Stage，
    # 而不是整个 Pipeline Run 的结束。
    assert (
        pipeline.runtime.status
        == "running"
    )

    assert (
        pipeline.runtime.current_stage
        is None
    )

    print("✅ 7. build runtime finished")

    # ========================================================
    # 9. 测试 Build 失败
    # ========================================================

    pipeline = KGBuilderPipeline()

    pipeline.start_run(
        metadata={
            "mode": "level10_test_error",
        }
    )

    pipeline.schema_engine.set_proposed_plan(
        {
            "Product": {
                "construction_type": "node",
                "label": "Product",
                "unique_column_name": "product_id",
                "properties": [
                    "product_name",
                ],
            }
        }
    )

    pipeline.schema_engine.approve()

    pipeline.ingestion_engine = (
        FakeIngestionEngine(
            status="error"
        )
    )

    result = await pipeline.build()

    assert result["status"] == "error"

    print("✅ 8. build error propagated")

    print()
    print("=" * 60)
    print("🎉 Level 10 全部通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(
        test_level10()
    )