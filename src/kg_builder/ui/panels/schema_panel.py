import json

from kg_builder.ui.panels.base_panel import BasePanel
from kg_builder.state import PROPOSED_CONSTRUCTION_PLAN


class SchemaPanel(BasePanel):
    title = "3.图谱结构设计"
    subtitle = "Agent 会提议节点与关系"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        self._caller = None
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "点击发送，Agent 会分析已批准文件，提议构建计划。"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._chat(text, on_chunk)

    async def _chat(self, text: str, on_chunk=None) -> str:
        if self._caller is None:
            self._caller = await self.pipeline.start_schema_proposal()
        response = await self._caller.chat(text, on_chunk=on_chunk)

        # 拿 state 里的 plan 摘要
        session = await self._caller.get_session()
        plan = session.state.get(PROPOSED_CONSTRUCTION_PLAN)
        if plan:
            summary = f"📋 当前构建计划（{len(plan)} 条）：\n"
            for name, rule in plan.items():
                icon = "🟦" if rule.get("construction_type") == "node" else "🔗"
                summary += f"  {icon} {name}\n"
            self.add_system_message(summary, "info")
        return response