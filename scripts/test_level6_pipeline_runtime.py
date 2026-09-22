"""
Phase 2 / Level 6

Pipeline Runtime 测试。

测试目标：

    1. PipelineRuntime 初始状态正确。
    2. start() 可以创建 Pipeline Run。
    3. Pipeline 状态可以从 idle -> running。
    4. Stage 可以从 pending -> running -> success。
    5. Pipeline 和 Stage 使用统一 run_id。
    6. RuntimeEvent 可以被记录。
    7. Stage duration 可以统计。
    8. Pipeline summary 正确。
    9. error 生命周期正确。
    10. reset() 可以恢复 idle。

注意：

    本测试不启动任何真实 Agent。

    因此：

        不需要 API Key
        不需要 Neo4j
        不需要 Google ADK Agent 调用

    只测试 Runtime 架构本身。
"""

import sys
from pathlib import Path


# ============================================================
# Python Path
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

SRC = ROOT / "src"

sys.path.insert(
    0,
    str(SRC),
)


# ============================================================
# Imports
# ============================================================

from kg_builder.core.pipeline_runtime import (
    PipelineRuntime,
)


# ============================================================
# 1. 初始化
# ============================================================


def test_initial_state():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "1. Pipeline Runtime 初始化"
    )

    runtime = PipelineRuntime()

    assert runtime.status == "idle"

    assert runtime.run_id is None

    assert runtime.current_stage is None

    assert runtime.stage_history == []

    assert runtime.get_stage(
        "intent"
    ).status == "pending"

    assert runtime.get_stage(
        "schema"
    ).status == "pending"

    print(
        "  ✅ 初始状态正确"
    )

    return runtime


# ============================================================
# 2. Pipeline Start
# ============================================================


def test_pipeline_start(
    runtime: PipelineRuntime,
):

    print(
        "\n"
        + "-" * 60
    )

    print(
        "2. Pipeline Run"
    )

    run_id = runtime.start(
        metadata={
            "test": True,
        }
    )

    assert run_id

    assert runtime.run_id == run_id

    assert runtime.status == "running"

    assert runtime.started_at is not None

    print(
        f"  ✅ Run ID: {run_id}"
    )

    print(
        "  ✅ Pipeline Run 创建"
    )


# ============================================================
# 3. Stage Lifecycle
# ============================================================


def test_stage_lifecycle(
    runtime: PipelineRuntime,
):

    print(
        "\n"
        + "-" * 60
    )

    print(
        "3. Stage Lifecycle"
    )

    stage = runtime.start_stage(
        "intent",
        agent_name="user_intent",
    )

    assert stage.status == "running"

    assert runtime.status == "running"

    assert runtime.current_stage == "intent"

    assert runtime.stage_history == [
        "intent"
    ]

    runtime.finish_stage(
        "intent",
        status="success",
    )

    assert stage.status == "success"

    assert stage.started_at is not None

    assert stage.finished_at is not None

    assert stage.duration_ms is not None

    assert stage.duration_ms >= 0

    assert runtime.current_stage is None

    print(
        "  ✅ Stage pending → running → success"
    )

    print(
        f"  ✅ Stage duration: "
        f"{stage.duration_ms:.3f} ms"
    )


# ============================================================
# 4. 多 Stage
# ============================================================


def test_multiple_stages(
    runtime: PipelineRuntime,
):

    print(
        "\n"
        + "-" * 60
    )

    print(
        "4. Multiple Stages"
    )

    runtime.start_stage(
        "structured_files",
        agent_name="structured_file_agent",
    )

    runtime.finish_stage(
        "structured_files"
    )

    runtime.start_stage(
        "schema",
        agent_name="schema_refinement_loop",
    )

    runtime.finish_stage(
        "schema"
    )

    assert runtime.stage_history == [
        "intent",
        "structured_files",
        "schema",
    ]

    assert (
        runtime.get_stage(
            "structured_files"
        ).status
        == "success"
    )

    assert (
        runtime.get_stage(
            "schema"
        ).status
        == "success"
    )

    print(
        "  ✅ 多 Stage 生命周期正确"
    )

    print(
        "  ✅ 所有 Stage 共用同一个 Pipeline Run"
    )


# ============================================================
# 5. Runtime Events
# ============================================================


def test_runtime_events(
    runtime: PipelineRuntime,
):

    print(
        "\n"
        + "-" * 60
    )

    print(
        "5. Runtime Events"
    )

    events = runtime.get_events()

    assert len(events) >= 1

    event_types = [
        event.event_type
        for event in events
    ]

    assert (
        "run_started"
        in event_types
    )

    assert (
        "pipeline_stage_started"
        in event_types
    )

    assert (
        "pipeline_stage_finished"
        in event_types
    )

    for event in events:

        assert (
            event.run_id
            == runtime.run_id
        )

    print(
        f"  ✅ RuntimeEvent 数量: "
        f"{len(events)}"
    )

    print(
        "  ✅ Event 全部绑定到同一个 run_id"
    )


# ============================================================
# 6. Pipeline Finish
# ============================================================


def test_pipeline_finish(
    runtime: PipelineRuntime,
):

    print(
        "\n"
        + "-" * 60
    )

    print(
        "6. Pipeline Finish"
    )

    runtime.finish(
        status="success",
        message="test finished",
    )

    assert runtime.status == "success"

    assert runtime.finished_at is not None

    assert runtime.duration_ms is not None

    assert runtime.duration_ms >= 0

    print(
        "  ✅ Pipeline 状态：running → success"
    )

    print(
        f"  ✅ Pipeline duration: "
        f"{runtime.duration_ms:.3f} ms"
    )


# ============================================================
# 7. Summary
# ============================================================


def test_summary(
    runtime: PipelineRuntime,
):

    print(
        "\n"
        + "-" * 60
    )

    print(
        "7. Pipeline Summary"
    )

    summary = runtime.get_summary()

    assert (
        summary["run_id"]
        == runtime.run_id
    )

    assert (
        summary["status"]
        == "success"
    )

    assert (
        "intent"
        in summary["stages"]
    )

    assert (
        "schema"
        in summary["stages"]
    )

    assert (
        summary["stage_history"]
        == [
            "intent",
            "structured_files",
            "schema",
        ]
    )

    print(
        "  ✅ Summary 正确"
    )

    print(
        f"  ✅ Stage history: "
        f"{summary['stage_history']}"
    )


# ============================================================
# 8. Error Lifecycle
# ============================================================


def test_error_lifecycle():

    print(
        "\n"
        + "-" * 60
    )

    print(
        "8. Error Lifecycle"
    )

    runtime = PipelineRuntime()

    runtime.start()

    runtime.start_stage(
        "ner",
        agent_name="ner_agent",
    )

    runtime.fail_stage(
        "ner",
        error="模拟 NER 错误",
    )

    stage = runtime.get_stage(
        "ner"
    )

    assert stage.status == "error"

    assert (
        stage.error
        == "模拟 NER 错误"
    )

    assert runtime.current_stage is None

    runtime.finish(
        status="error",
        message="Pipeline failed",
    )

    assert runtime.status == "error"

    print(
        "  ✅ Stage error 生命周期正确"
    )

    print(
        "  ✅ Pipeline error 生命周期正确"
    )


# ============================================================
# 9. Reset
# ============================================================


def test_reset(
    runtime: PipelineRuntime,
):

    print(
        "\n"
        + "-" * 60
    )

    print(
        "9. Reset"
    )

    runtime.reset()

    assert runtime.status == "idle"

    assert runtime.run_id is None

    assert runtime.current_stage is None

    assert runtime.stage_history == []

    assert (
        runtime.get_stage(
            "intent"
        ).status
        == "pending"
    )

    print(
        "  ✅ Pipeline Runtime 已恢复 idle"
    )

    print(
        "  ✅ Stage 已恢复 pending"
    )


# ============================================================
# Main
# ============================================================


def main():

    print(
        "=" * 60
    )

    print(
        "Phase 2 / Level 6"
    )

    print(
        "Pipeline Runtime 测试"
    )

    print(
        "=" * 60
    )

    runtime = test_initial_state()

    test_pipeline_start(
        runtime
    )

    test_stage_lifecycle(
        runtime
    )

    test_multiple_stages(
        runtime
    )

    test_runtime_events(
        runtime
    )

    test_pipeline_finish(
        runtime
    )

    test_summary(
        runtime
    )

    test_error_lifecycle()

    test_reset(
        runtime
    )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "🎉 Phase 2 / Level 6 全部通过！"
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()