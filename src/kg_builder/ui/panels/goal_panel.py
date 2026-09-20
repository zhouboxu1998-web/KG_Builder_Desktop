from kg_builder.ui.panels.base_panel import BasePanel


class GoalPanel(BasePanel):
    title = "1.定义目标"
    subtitle = "描述你想构建的知识图谱"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        self._caller = None
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "告诉我你想构建什么类型的知识图谱。例如："
            "'一个包含供应商到成品各层级的物料清单图谱，支持根本原因分析。'"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._chat(text, on_chunk)

    async def _chat(self, text: str, on_chunk=None) -> str:
        if self._caller is None:
            self._caller = await self.pipeline.start_intent()
        return await self._caller.chat(text, on_chunk=on_chunk)