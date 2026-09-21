"""图谱结构设计面板：Agent 提议 → 用户批准。"""

import json

from kg_builder.state import PROPOSED_CONSTRUCTION_PLAN
from kg_builder.ui.panels.base_panel import BasePanel


class SchemaPanel(BasePanel):
    title = "3.图谱结构设计"
    subtitle = "Agent 提议节点与关系，请审查后批准"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        self._caller = None
        self._approved = False
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "点击发送，Agent 会分析已批准的结构化文件，提议构建计划。\n"
            "审查后输入「批准」以确认。"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._chat(text, on_chunk)

    # --------------------------------------------------------

    def _is_approval(self, text: str) -> bool:
        """判断用户输入是否是批准意图。"""
        t = text.strip().lower()
        if len(t) > 30:
            return False
        keywords = ["批准", "同意", "确认", "通过", "approve", "ok", "yes"]
        return any(k in t for k in keywords)

    async def _chat(self, text: str, on_chunk=None) -> str:
        # 1. 检测批准意图
        if self._is_approval(text):
            return await self._handle_approval()

        # 2. 正常对话
        if self._caller is None:
            self._caller = await self.pipeline.start_schema_proposal()

        response = await self._caller.chat(text, on_chunk=on_chunk)

        # 3. 展示当前计划摘要
        session = await self._caller.get_session()
        plan = session.state.get(PROPOSED_CONSTRUCTION_PLAN)
        if plan:
            summary = f"当前构建计划（{len(plan)} 条）：\n"
            for name, rule in plan.items():
                icon = "▪" if rule.get("construction_type") == "node" else "→"
                summary += f"  {icon} {name}\n"
            summary += "\n请审查。如果满意，输入「批准」。"
            self.add_system_message(summary, "info")

        return response

    async def _handle_approval(self) -> str:
        """处理用户批准。"""
        if self._approved:
            return "构建计划已经批准过了。"

        result = await self.pipeline.approve_schema_plan()

        if result["status"] != "success":
            self.add_system_message(
                f"❌ 批准失败：{result['message']}", "error"
            )
            return f"批准失败：{result['message']}"

        self._approved = True
        count = result["count"]
        self.add_system_message(
            f"✅ 构建计划已批准（共 {count} 条规则）",
            "success",
        )
        return (
            f"构建计划已批准。共 {count} 条规则。\n"
            f"可以进入「④ 非结构化文件」继续，"
            f"或者跳过直接到「⑦ 构建」。"
        )