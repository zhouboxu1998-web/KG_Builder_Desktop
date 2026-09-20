from kg_builder.ui.panels.base_panel import BasePanel
from kg_builder.state import APPROVED_FILES, SUGGESTED_FILES


class FilesPanel(BasePanel):
    title = "2.选择文件"
    subtitle = "Agent 会推荐与目标相关的数据文件"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        self._caller = None
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "点击下方发送按钮，Agent 将列出可用文件并推荐相关文件。"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._chat(text, on_chunk)

    async def _chat(self, text: str, on_chunk=None) -> str:
        if self._caller is None:
            self._caller = await self.pipeline.start_file_selection()
        response = await self._caller.chat(text, on_chunk=on_chunk)

        session = await self._caller.get_session()
        state = session.state
        if SUGGESTED_FILES in state:
            self.add_system_message(
                f"📎 已建议文件: {state[SUGGESTED_FILES]}", "info"
            )
        if APPROVED_FILES in state:
            self.add_system_message(
                f"✅ 已批准文件: {state[APPROVED_FILES]}", "success"
            )
        return response