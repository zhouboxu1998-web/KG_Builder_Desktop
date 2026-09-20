"""NER 面板：从非结构化文本提议实体类型。"""

from kg_builder.state import APPROVED_ENTITIES, PROPOSED_ENTITIES
from kg_builder.ui.panels.base_panel import BasePanel


class NerPanel(BasePanel):
    title = "④ 实体识别（NER）"
    subtitle = "从 Markdown 评论中提议实体类型"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        self._caller = None
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "点击发送，Agent 会分析已批准的 Markdown 文件，"
            "提议可以从文本中提取的实体类型。\n"
            "输入 '批准这些建议的实体' 完成确认。"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._chat(text, on_chunk)

    async def _chat(self, text: str, on_chunk=None) -> str:
        if self._caller is None:
            self._caller = await self.pipeline.start_ner()

        response = await self._caller.chat(text, on_chunk=on_chunk)

        # 同步 state
        session = await self._caller.get_session()
        state = session.state
        if PROPOSED_ENTITIES in state:
            self.add_system_message(
                f"📋 建议实体: {state[PROPOSED_ENTITIES]}", "info"
            )
        if APPROVED_ENTITIES in state:
            self.add_system_message(
                f"✅ 已批准实体: {state[APPROVED_ENTITIES]}", "success"
            )
        return response