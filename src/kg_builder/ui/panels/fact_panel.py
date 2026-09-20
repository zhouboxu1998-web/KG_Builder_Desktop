"""事实类型面板：提议事实类型（三元组）。"""

import json

from kg_builder.state import APPROVED_FACTS, PROPOSED_FACTS
from kg_builder.ui.panels.base_panel import BasePanel


class FactPanel(BasePanel):
    title = "⑤ 事实类型"
    subtitle = "提议 (主语, 谓语, 宾语) 关系"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        self._caller = None
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "点击发送，Agent 会基于已批准的实体类型，"
            "提议可以从文本中提取的事实类型。\n"
            "输入 '批准这些建议的事实类型' 完成确认。"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._chat(text, on_chunk)

    async def _chat(self, text: str, on_chunk=None) -> str:
        if self._caller is None:
            self._caller = await self.pipeline.start_fact()

        response = await self._caller.chat(text, on_chunk=on_chunk)

        session = await self._caller.get_session()
        state = session.state
        if PROPOSED_FACTS in state:
            summary = "📋 建议事实：\n"
            for k, v in state[PROPOSED_FACTS].items():
                summary += (
                    f"  · ({v['subject_label']}) -[{k}]-> "
                    f"({v['object_label']})\n"
                )
            self.add_system_message(summary, "info")
        if APPROVED_FACTS in state:
            self.add_system_message(
                f"✅ 已批准 {len(state[APPROVED_FACTS])} 条事实类型",
                "success",
            )
        return response