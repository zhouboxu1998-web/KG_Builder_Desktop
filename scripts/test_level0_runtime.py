"""Level 0: Runtime 事件系统单元测试。

不依赖 LLM、Neo4j，只验证：
    - RuntimeEvent 数据类
    - RuntimeEventStore 存储
    - RuntimeEventListener 机制
    - StageDurationListener 耗时累加
    - Runtime.emit 广播

运行：
    python test_level0_runtime.py

期望：
    所有断言通过，输出 "全部通过"。
"""

import sys
from pathlib import Path

# 让 src 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kg_builder.core.events import (
    CompositeEventListener,
    Runtime,
    RuntimeEvent,
    RuntimeEventListener,
    RuntimeEventStore,
    generate_event_id,
    generate_run_id,
)
from kg_builder.core.listeners import (
    AGENT_TO_STAGE,
    ConsoleListener,
    StageDurationListener,
)


# ============================================================
# 工具函数
# ============================================================
def _sep(title: str):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def _ok(msg: str):
    print(f"  [OK] {msg}")


def _fail(msg: str):
    print(f"  [FAIL] {msg}")
    raise AssertionError(msg)


# ============================================================
# 测试 1：RuntimeEvent 基础功能
# ============================================================
def test_event_basics():
    _sep("测试 1：RuntimeEvent 基础功能")

    # 1.1 自动生成 event_id
    e1 = RuntimeEvent(event_type="test", run_id="run-001")
    e2 = RuntimeEvent(event_type="test", run_id="run-001")
    assert e1.event_id != e2.event_id
    _ok(f"自动生成 event_id: {e1.event_id[:8]}...")

    # 1.2 时间戳
    assert e1.timestamp
    _ok(f"时间戳: {e1.timestamp}")

    # 1.3 可选字段默认值
    assert e1.stage is None
    assert e1.agent is None
    assert e1.status is None
    assert e1.duration_ms is None
    assert e1.message is None
    assert e1.metadata == {}
    _ok("可选字段默认值正确")

    # 1.4 to_dict / to_json
    d = e1.to_dict()
    assert isinstance(d, dict)
    assert d["event_type"] == "test"
    assert d["run_id"] == "run-001"

    j = e1.to_json()
    assert '"event_type": "test"' in j
    _ok("to_dict / to_json 正确")

    # 1.5 generate_event_id 唯一性
    ids = {generate_event_id() for _ in range(100)}
    assert len(ids) == 100
    _ok("generate_event_id 生成 100 个不重复 ID")

    # 1.6 generate_run_id 格式
    rid = generate_run_id()
    assert len(rid) > 8
    assert "-" in rid
    _ok(f"generate_run_id 格式: {rid}")


# ============================================================
# 测试 2：RuntimeEventStore 存储
# ============================================================
def test_event_store():
    _sep("测试 2：RuntimeEventStore 存储")

    # 2.1 基本存储
    store = RuntimeEventStore(max_events=10)
    assert store.count() == 0
    _ok("初始 count = 0")

    store.append(RuntimeEvent(event_type="a", run_id="r1"))
    store.append(RuntimeEvent(event_type="b", run_id="r1"))
    store.append(RuntimeEvent(event_type="c", run_id="r2"))

    assert store.count() == 3
    _ok(f"追加 3 条，count = {store.count()}")

    # 2.2 get_all
    all_events = store.get_all()
    assert len(all_events) == 3
    assert all_events[0].event_type == "a"
    _ok("get_all 返回 3 条（按顺序）")

    # 2.3 get_by_run
    r1_events = store.get_by_run("r1")
    assert len(r1_events) == 2
    r2_events = store.get_by_run("r2")
    assert len(r2_events) == 1
    r3_events = store.get_by_run("r3")
    assert len(r3_events) == 0
    _ok("get_by_run 正确过滤")

    # 2.4 溢出保护
    for i in range(20):
        store.append(RuntimeEvent(event_type=f"overflow-{i}", run_id="r3"))
    assert store.count() == 10  # max_events=10
    _ok(f"溢出保护：追加 20 条后 count = {store.count()} (max=10)")

    # 2.5 clear
    store.clear()
    assert store.count() == 0
    _ok("clear 后 count = 0")

    # 2.6 无效参数
    try:
        RuntimeEventStore(max_events=0)
        _fail("max_events=0 应该抛异常")
    except ValueError:
        _ok("max_events=0 正确抛 ValueError")


# ============================================================
# 测试 3：Listener 机制
# ============================================================
def test_listener():
    _sep("测试 3：Listener 机制")

    # 自定义 Listener：收集事件
    class Collector(RuntimeEventListener):
        def __init__(self):
            self.events = []

        def on_event(self, event):
            self.events.append(event)

    # 3.1 单个 Listener
    c1 = Collector()
    runtime = Runtime(listener=CompositeEventListener([c1]))

    runtime.emit(RuntimeEvent(event_type="a", run_id="r1"))
    runtime.emit(RuntimeEvent(event_type="b", run_id="r1"))
    assert len(c1.events) == 2
    _ok("单个 Listener 收到 2 条事件")

    # 3.2 多个 Listener
    c2 = Collector()
    comp = CompositeEventListener([c1, c2])
    runtime2 = Runtime(listener=comp)

    runtime2.emit(RuntimeEvent(event_type="c", run_id="r2"))
    assert len(c1.events) == 3
    assert len(c2.events) == 1
    _ok("多个 Listener 同时收到事件")

    # 3.3 Listener 异常不影响主流程
    class BrokenListener(RuntimeEventListener):
        def on_event(self, event):
            raise RuntimeError("故意抛错")

    c3 = Collector()
    comp2 = CompositeEventListener([BrokenListener(), c3])
    runtime3 = Runtime(listener=comp2)

    runtime3.emit(RuntimeEvent(event_type="d", run_id="r3"))
    assert len(c3.events) == 1
    _ok("Listener 抛异常不影响其他 Listener")

    # 3.4 emit 同时写入 store 和广播
    store = RuntimeEventStore()
    collector = Collector()
    runtime4 = Runtime(store=store, listener=collector)

    runtime4.emit(RuntimeEvent(event_type="e", run_id="r4"))
    assert store.count() == 1
    assert len(collector.events) == 1
    _ok("emit 同时写入 store 和广播")


# ============================================================
# 测试 4：StageDurationListener 耗时累加
# ============================================================
def test_stage_duration_listener():
    _sep("测试 4：StageDurationListener 耗时累加")

    listener = StageDurationListener()

    # 4.1 非 agent_finished 事件被忽略
    listener.on_event(RuntimeEvent(
        event_type="agent_started", run_id="r1",
        stage="1", agent="user_intent_agent_v1",
    ))
    assert listener.get("1") == 0.0
    _ok("agent_started 事件被忽略")

    listener.on_event(RuntimeEvent(
        event_type="adk_event", run_id="r1", stage="1",
    ))
    assert listener.get("1") == 0.0
    _ok("adk_event 事件被忽略")

    # 4.2 无 stage 的 finished 事件被忽略
    listener.on_event(RuntimeEvent(
        event_type="agent_finished", run_id="r1",
        duration_ms=1000.0,
    ))
    assert listener.total() == 0.0
    _ok("无 stage 的 agent_finished 被忽略")

    # 4.3 正常累加
    listener.on_event(RuntimeEvent(
        event_type="agent_finished", run_id="r1",
        stage="1", duration_ms=1200.0,
    ))
    assert listener.get("1") == 1.2
    _ok(f"阶段 1 耗时 = {listener.get('1')}s")

    # 4.4 多次累加
    listener.on_event(RuntimeEvent(
        event_type="agent_finished", run_id="r2",
        stage="1", duration_ms=800.0,
    ))
    assert listener.get("1") == 2.0
    _ok(f"阶段 1 累加到 {listener.get('1')}s")

    # 4.5 多阶段独立
    listener.on_event(RuntimeEvent(
        event_type="agent_finished", run_id="r3",
        stage="2", duration_ms=500.0,
    ))
    assert listener.get("1") == 2.0
    assert listener.get("2") == 0.5
    _ok(f"阶段 2 独立记录 = {listener.get('2')}s")

    # 4.6 total
    assert listener.total() == 2.5
    _ok(f"total = {listener.total()}s")

    # 4.7 all
    all_dur = listener.all()
    assert all_dur == {"1": 2.0, "2": 0.5}
    _ok(f"all = {all_dur}")

    # 4.8 reset
    listener.reset()
    assert listener.total() == 0.0
    _ok("reset 后 total = 0")


# ============================================================
# 测试 5：AGENT_TO_STAGE 映射
# ============================================================
def test_agent_stage_mapping():
    _sep("测试 5：AGENT_TO_STAGE 映射")

    expected = {
        "user_intent_agent_v1": "1",
        "structured_file_agent_v1": "2",
        "schema_refinement_loop": "3",
        "unstructured_file_agent_v1": "4",
        "ner_schema_agent_v1": "5",
        "fact_type_extraction_agent_v1": "6",
    }

    for agent, stage in expected.items():
        actual = AGENT_TO_STAGE.get(agent)
        if actual != stage:
            _fail(f"{agent} 应映射到 {stage}，实际 {actual}")
    _ok(f"6 个 Agent 映射正确")

    # Build 伪 Agent 也应有映射
    for name in ("build_structured", "build_unstructured",
                 "build_resolve", "build_clear"):
        assert AGENT_TO_STAGE.get(name) == "7"
    _ok("4 个 Build 伪 Agent 映射到阶段 7")

    # 未登记的 Agent 返回 None
    assert AGENT_TO_STAGE.get("unknown_agent") is None
    _ok("未登记的 Agent 返回 None")


# ============================================================
# 测试 6：完整场景模拟
# ============================================================
def test_full_scenario():
    _sep("测试 6：完整场景模拟")

    # 模拟一次完整流程
    duration_listener = StageDurationListener()
    store = RuntimeEventStore()
    runtime = Runtime(
        store=store,
        listener=CompositeEventListener([duration_listener]),
    )

    # 模拟：阶段 1 启动 → 结束
    runtime.emit(RuntimeEvent(
        event_type="agent_started", run_id="run-001",
        agent="user_intent_agent_v1", stage="1", status="running",
    ))
    runtime.emit(RuntimeEvent(
        event_type="agent_finished", run_id="run-001",
        agent="user_intent_agent_v1", stage="1",
        status="success", duration_ms=1200.0,
    ))

    # 模拟：阶段 2
    runtime.emit(RuntimeEvent(
        event_type="agent_started", run_id="run-002",
        agent="structured_file_agent_v1", stage="2", status="running",
    ))
    runtime.emit(RuntimeEvent(
        event_type="agent_finished", run_id="run-002",
        agent="structured_file_agent_v1", stage="2",
        status="success", duration_ms=800.0,
    ))

    # 模拟：阶段 7 build
    runtime.emit(RuntimeEvent(
        event_type="agent_started", run_id="run-003",
        agent="build_structured", stage="7", status="running",
    ))
    runtime.emit(RuntimeEvent(
        event_type="agent_finished", run_id="run-003",
        agent="build_structured", stage="7",
        status="success", duration_ms=2400.0,
    ))

    # 断言
    assert duration_listener.get("1") == 1.2
    assert duration_listener.get("2") == 0.8
    assert duration_listener.get("7") == 2.4
    assert duration_listener.total() == 4.4
    _ok(f"阶段 1: {duration_listener.get('1')}s")
    _ok(f"阶段 2: {duration_listener.get('2')}s")
    _ok(f"阶段 7: {duration_listener.get('7')}s")
    _ok(f"总计:  {duration_listener.total()}s")

    assert store.count() == 6
    _ok(f"EventStore 收到 {store.count()} 条事件")

    # 按 run_id 查询
    run1 = store.get_by_run("run-001")
    assert len(run1) == 2
    _ok(f"run-001 有 {len(run1)} 条事件（started + finished）")


# ============================================================
# 测试 7：ConsoleListener
# ============================================================
def test_console_listener():
    _sep("测试 7：ConsoleListener")

    # 7.1 enabled=False 不打印
    listener = ConsoleListener(enabled=False)
    listener.on_event(RuntimeEvent(event_type="x", run_id="r1"))
    _ok("enabled=False 时静默")

    # 7.2 enabled=True 打印（不验证输出，只验证不抛异常）
    listener2 = ConsoleListener(enabled=True)
    print("  下方应出现一行 [Runtime] 事件：")
    listener2.on_event(RuntimeEvent(
        event_type="agent_finished", run_id="r1",
        agent="user_intent_agent_v1", stage="1",
        duration_ms=1234.5,
    ))
    _ok("enabled=True 正常打印")


# ============================================================
# 主入口
# ============================================================
def main():
    print("\n" + "=" * 60)
    print("Level 0: Runtime 事件系统测试")
    print("=" * 60)

    try:
        test_event_basics()
        test_event_store()
        test_listener()
        test_stage_duration_listener()
        test_agent_stage_mapping()
        test_full_scenario()
        test_console_listener()
    except AssertionError as e:
        print()
        print("=" * 60)
        print("[FAIL] 测试失败")
        print("=" * 60)
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 60)
        print("[ERROR] 未预期错误")
        print("=" * 60)
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print()
    print("=" * 60)
    print("[OK] 全部通过")
    print("=" * 60)
    print()
    print("结论：Runtime 事件系统工作正常。")
    print("下一步：进入 Level 1 测试（agent_runner 集成）")


if __name__ == "__main__":
    main()