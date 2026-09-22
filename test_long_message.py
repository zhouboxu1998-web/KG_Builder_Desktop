"""独立测试：验证 BasePanel 在各字数档位下能否完整容纳长文本。

用法：
    python test_long_message.py

快捷键（窗口获得焦点时按）：
    Ctrl + 1    注入 ~1,000 字（多段落）
    Ctrl + 2    注入 ~5,000 字（多段落）
    Ctrl + 3    注入 ~10,000 字（多段落）
    Ctrl + 4    注入 ~30,000 字（多段落）
    Ctrl + 5    注入 ~50,000 字（无换行，极限换行测试）
    Ctrl + 6    注入 ~100,000 字（混合类型，终极压力测试）
    Ctrl + 7    注入 ~20,000 字（JSON 风格，模拟图谱结构输出）
    Ctrl + 8    注入 ~8,000 字（Markdown 列表风格）
    Ctrl + 0    清空聊天区

验证标准：
    每条注入消息末尾都有唯一的结束标记：
        ┌────────────────────────────┐
        │ 【END-XXXXXXXX】           │
        │ 累计字数: XXXXX            │
        └────────────────────────────┘

    在气泡内能滚动到末尾看到这个标记 = 显示完整
    或点击"查看完整内容"按钮，在弹窗里看到标记 = 完整
    滚动到底也看不到标记 = 显示被裁切（异常）

    每次注入后，Run 窗口会打印：
        [注入] 类型=多段落, 目标=30000, 实际=30045 字
    可用于核对。
"""

import json
import random
import sys
from pathlib import Path

# 把 src/ 加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import customtkinter as ctk

from kg_builder.ui.panels.base_panel import BasePanel


# ============================================================
# 假 Bridge（不走 LLM）
# ============================================================

class _FakeBridge:
    """占位 bridge：测试不走 LLM，所以不需要真的 submit。"""

    def submit(self, coro):
        class _DummyFuture:
            def add_done_callback(self, cb):
                pass
        return _DummyFuture()

    def stop(self):
        pass


# ============================================================
# 测试 Panel
# ============================================================

class TestPanel(BasePanel):
    title = "长文本显示测试"
    subtitle = "Ctrl+1~8 注入不同字数 · Ctrl+0 清空"

    def on_send(self, text, on_chunk=None):
        async def _noop():
            return ""
        return _noop()


# ============================================================
# 文本生成器
# ============================================================

# 中文常用字（用于生成无意义但有真实感的文本）
_WORDS = [
    "系统", "数据", "图谱", "节点", "关系", "构建", "分析", "模型",
    "文档", "字段", "索引", "查询", "结果", "处理", "验证", "输出",
    "输入", "配置", "参数", "状态", "过程", "方法", "策略", "方案",
    "架构", "组件", "模块", "接口", "服务", "资源", "对象", "属性",
    "特征", "规律", "模式", "结构", "层级", "维度", "指标", "度量",
    "检测", "监控", "预警", "响应", "恢复", "调度", "编排", "流程",
    "业务", "场景", "需求", "目标", "任务", "计划", "执行", "反馈",
    "优化", "迭代", "演进", "扩展", "集成", "部署", "运维", "治理",
]

_PUNCT = ["。", "，", "；", "：", "、", "！", "？"]


def _random_sentence(min_len=20, max_len=60) -> str:
    """生成一个随机中文句子，长度在 [min_len, max_len] 之间。"""
    target = random.randint(min_len, max_len)
    parts = []
    while sum(len(p) for p in parts) < target:
        parts.append(random.choice(_WORDS))
    parts.append(random.choice(_PUNCT))
    return "".join(parts)


def _random_paragraph(target=150) -> str:
    """生成一个段落（由若干句子组成），总字数约 target。"""
    sentences = []
    length = 0
    while length < target:
        s = _random_sentence()
        sentences.append(s)
        length += len(s)
    return "".join(sentences)


def make_paragraphs_text(approx_chars: int) -> str:
    """生成多段落文本，每段之间用双换行分隔。"""
    parts = []
    total = 0
    i = 0
    while total < approx_chars:
        i += 1
        header = f"【第 {i:04d} 段】"
        body = _random_paragraph(150)
        block = f"{header}\n{body}"
        parts.append(block)
        total += len(block) + 2  # +2 for '\n\n'
    return "\n\n".join(parts)


def make_no_break_text(approx_chars: int) -> str:
    """生成一整段无换行文本（换行压力测试）。"""
    chunks = []
    total = 0
    while total < approx_chars:
        s = _random_sentence(40, 80)
        chunks.append(s)
        total += len(s)
    return "".join(chunks)


def make_json_text(approx_chars: int) -> str:
    """生成 JSON 风格文本（模拟图谱结构输出）。"""
    data = {
        "construction_plan": {},
        "metadata": {
            "kind_of_graph": "供应链分析",
            "description": "多层级物料清单，用于根本原因分析",
            "approved_files": [
                "products.csv",
                "assemblies.csv",
                "components.csv",
                "parts.csv",
                "suppliers.csv",
                "part_supplier_mapping.csv",
            ],
        },
        "notes": [],
    }

    # 生成大量节点/关系条目
    total = len(json.dumps(data, ensure_ascii=False, indent=2))
    i = 0
    while total < approx_chars:
        i += 1
        key = f"Item_{i:05d}"
        data["construction_plan"][key] = {
            "construction_type": "node" if i % 3 != 0 else "relationship",
            "source_file": random.choice([
                "products.csv", "assemblies.csv", "components.csv",
                "suppliers.csv", "part_supplier_mapping.csv",
            ]),
            "label": random.choice(_WORDS) + str(i),
            "unique_column_name": f"id_{i}",
            "properties": [_random_sentence(4, 12) for _ in range(3)],
            "description": _random_sentence(30, 80),
        }
        total = len(json.dumps(data, ensure_ascii=False, indent=2))
    return json.dumps(data, ensure_ascii=False, indent=2)


def make_markdown_text(approx_chars: int) -> str:
    """生成 Markdown 列表风格文本。"""
    lines = ["# 图谱分析报告\n"]
    i = 0
    total = 0
    while total < approx_chars:
        i += 1
        lines.append(f"\n## 第 {i} 节\n")
        lines.append(f"- 要点 A：{_random_sentence(30, 60)}")
        lines.append(f"- 要点 B：{_random_sentence(30, 60)}")
        lines.append(f"- 要点 C：{_random_sentence(30, 60)}")
        lines.append(f"\n{_random_paragraph(100)}\n")
        total = len("".join(lines))
    return "".join(lines)


# ============================================================
# 主窗口
# ============================================================

class TestWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("长文本显示测试")
        self.geometry("1000x750")
        self.minsize(700, 500)
        self.configure(fg_color="#f7f7fa")

        self.panel = TestPanel(self, _FakeBridge())
        self.panel.pack(fill="both", expand=True)

        # ---------- 快捷键 ----------
        self.bind_all("<Control-Key-1>", lambda e: self._inject("paragraphs", 1000))
        self.bind_all("<Control-Key-2>", lambda e: self._inject("paragraphs", 5000))
        self.bind_all("<Control-Key-3>", lambda e: self._inject("paragraphs", 10000))
        self.bind_all("<Control-Key-4>", lambda e: self._inject("paragraphs", 30000))
        self.bind_all("<Control-Key-5>", lambda e: self._inject("nobreak", 50000))
        self.bind_all("<Control-Key-6>", lambda e: self._inject("mixed", 100000))
        self.bind_all("<Control-Key-7>", lambda e: self._inject("json", 20000))
        self.bind_all("<Control-Key-8>", lambda e: self._inject("markdown", 8000))
        self.bind_all("<Control-Key-0>", lambda e: self.panel.clear_chat())

        # 启动提示
        self.after(300, self._show_help)

    # --------------------------------------------------------

    def _show_help(self):
        help_text = (
            "【长文本显示测试】\n"
            "  Ctrl+1   →   1,000 字（多段落）\n"
            "  Ctrl+2   →   5,000 字（多段落）\n"
            "  Ctrl+3   →  10,000 字（多段落）\n"
            "  Ctrl+4   →  30,000 字（多段落）\n"
            "  Ctrl+5   →  50,000 字（无换行）\n"
            "  Ctrl+6   → 100,000 字（混合）\n"
            "  Ctrl+7   →  20,000 字（JSON 风格）\n"
            "  Ctrl+8   →   8,000 字（Markdown 列表）\n"
            "  Ctrl+0   →  清空聊天区\n"
            "\n"
            "【验证方法】\n"
            "  每次注入后，滚动到底部，应能看到：\n"
            "    ┌──────────────────────────────┐\n"
            "    │ 【END-XXXXXXXX】             │\n"
            "    └──────────────────────────────┘\n"
            "  能看到 = 完整显示。看不到 = 被裁切。\n"
            "  或点击气泡里「查看完整内容」按钮，在弹窗里检查。"
        )
        self.panel.add_system_message(help_text, "info")

    # --------------------------------------------------------

    def _inject(self, kind: str, target: int):
        """注入长文本。"""
        # 根据类型生成文本
        if kind == "paragraphs":
            text = make_paragraphs_text(target)
            label = "多段落"
        elif kind == "nobreak":
            text = make_no_break_text(target)
            label = "无换行"
        elif kind == "json":
            text = make_json_text(target)
            label = "JSON 风格"
        elif kind == "markdown":
            text = make_markdown_text(target)
            label = "Markdown 列表"
        elif kind == "mixed":
            # 混合：多段落 + 无换行 + JSON 片段
            seg1 = make_paragraphs_text(target // 3)
            seg2 = make_no_break_text(target // 3)
            seg3 = make_json_text(target // 3)
            text = (
                "=== 第一部分：多段落 ===\n\n"
                + seg1
                + "\n\n=== 第二部分：无换行 ===\n\n"
                + seg2
                + "\n\n=== 第三部分：JSON ===\n\n"
                + seg3
            )
            label = "混合"
        else:
            text = make_paragraphs_text(target)
            label = "未知类型"

        total = len(text)

        # 生成唯一 ID
        import uuid
        uid = uuid.uuid4().hex[:8].upper()

        # 结束标记（关键：唯一，方便在滚动中核对）
        end_marker = (
            f"\n\n"
            f"┌──────────────────────────────┐\n"
            f"│  【END-{uid}】                │\n"
            f"│  类型: {label}              │\n"
            f"│  目标字数: {target:,}          │\n"
            f"│  实际字数: {total:,}          │\n"
            f"└──────────────────────────────┘\n"
        )

        final_text = text + end_marker

        # 打印到控制台（便于核对）
        print(
            f"[注入] 类型={label:8s}, "
            f"目标={target:>7,}, "
            f"实际={len(final_text):>7,} 字, "
            f"ID={uid}"
        )

        # 注入到面板
        self.panel.add_system_message(
            f"▼ 开始注入 [ID={uid}] 类型={label} 字数={len(final_text):,} ▼",
            "info",
        )
        self.panel.add_agent_message(final_text)
        self.panel.add_system_message(
            f"▲ 注入结束 [ID={uid}] 请看气泡末尾是否显示 【END-{uid}】 ▲",
            "success",
        )

        # 延迟滚到底
        self.after(500, self.panel._scroll_to_bottom)


# ============================================================

if __name__ == "__main__":
    # 固定随机种子便于复现（可选）
    # random.seed(42)

    app = TestWindow()
    app.mainloop()