"""查询面板：支持直接 Cypher 验证与自然语言知识图谱查询。"""

import re

from kg_builder.ui.panels.base_panel import BasePanel


READ_ONLY_QUERY_STARTS = {
    "MATCH",
    "OPTIONAL",
    "WITH",
    "UNWIND",
    "RETURN",
    "SHOW",
    "PROFILE",
    "EXPLAIN",
    "CALL",
}


class QueryPanel(BasePanel):
    title = "8.查询"
    subtitle = "输入自然语言查询知识图谱，也可以直接运行 Cypher 验证"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "可以直接用中文提问，例如：\n"
            "  哪些产品由哪些供应商提供？\n"
            "  Product A 属于哪个 Assembly？\n"
            "\n"
            "也可以直接输入 Cypher，例如：\n"
            "  MATCH (n) RETURN labels(n) AS label, count(n) AS count\n"
            "  MATCH (p:Product) RETURN p.product_name LIMIT 5"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._run(text, on_chunk=on_chunk)

    @staticmethod
    def _looks_like_cypher(text: str) -> bool:
        """判断输入是否明显是一条 Cypher。"""

        normalized = text.strip()

        if not normalized:
            return False

        first_match = re.match(
            r"^([A-Za-z_][A-Za-z0-9_]*)",
            normalized,
        )

        if not first_match:
            return False

        first_keyword = (
            first_match.group(1)
            .upper()
        )

        return (
            first_keyword
            in READ_ONLY_QUERY_STARTS
        )

    async def _run(
        self,
        text: str,
        on_chunk=None,
    ) -> str:
        if not text.strip():
            return "请输入查询内容。"

        # ----------------------------------------------------
        # 直接 Cypher 模式
        # ----------------------------------------------------

        if self._looks_like_cypher(text):

            try:
                self.pipeline.ensure_query_run(
                    metadata={
                        "mode": "direct_cypher",
                    }
                )

                result = await self.pipeline.query(
                    text
                )

            except Exception as error:
                return f"错误: {error}"

            if result.get("status") == "success":
                return (
                    "查询结果：\n"
                    f"{result.get('result', [])}"
                )

            return (
                "错误: "
                f"{result.get('error_message', '查询失败。')}"
            )

        # ----------------------------------------------------
        # 自然语言模式
        # ----------------------------------------------------

        try:
            return await self.pipeline.query_chat(
                text,
                on_chunk=on_chunk,
            )
        except Exception as error:
            return f"错误: {error}"
