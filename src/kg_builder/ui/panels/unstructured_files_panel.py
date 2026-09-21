"""非结构化文件选择面板。"""

from kg_builder.state import (
    APPROVED_UNSTRUCTURED_FILES,
    SUGGESTED_UNSTRUCTURED_FILES,
)
from kg_builder.ui.panels.base_panel import BasePanel


class UnstructuredFilesPanel(BasePanel):
    title = "4.选择非结构化文件"
    subtitle = "推荐 Markdown / TXT（用于构建主题图）"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        self._caller = None
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "点击发送，Agent 会列出可用的非结构化文件（MD/TXT），"
            "并推荐用于构建主题图（用户评论、反馈）的文件。\n"
            "结构化文件已经在上一个面板处理。"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._chat(text, on_chunk)

    async def _chat(self, text: str, on_chunk=None) -> str:
        if self._caller is None:
            self._caller = await self.pipeline.start_unstructured_selection()

        response = await self._caller.chat(text, on_chunk=on_chunk)

        session = await self._caller.get_session()
        state = session.state

        if SUGGESTED_UNSTRUCTURED_FILES in state:
            files = state[SUGGESTED_UNSTRUCTURED_FILES]
            self.add_system_message(
                f"📎 已建议 {len(files)} 个非结构化文件", "info"
            )
        if APPROVED_UNSTRUCTURED_FILES in state:
            files = state[APPROVED_UNSTRUCTURED_FILES]
            self.add_system_message(
                f"✅ 已批准 {len(files)} 个非结构化文件", "success"
            )
        return response