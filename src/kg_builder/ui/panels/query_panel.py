from kg_builder.core.neo4j_client import graphdb
from kg_builder.ui.panels.base_panel import BasePanel


class QueryPanel(BasePanel):
    title = "5.查询验证"
    subtitle = "直接运行 Cypher 语句验证图谱"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "输入 Cypher 语句执行查询。例如：\n"
            "  MATCH (n) RETURN labels(n) AS label, count(n) AS count\n"
            "  MATCH (p:Product) RETURN p.product_name LIMIT 5"
        )

    def on_send(self, text: str, on_chunk=None):
        return self._run(text)

    async def _run(self, text: str) -> str:
        if any(kw in text.upper() for kw in ("MATCH", "RETURN", "CALL")):
            r = graphdb.send_query(text)
            if r["status"] == "success":
                return f"结果:\n{r['query_result']}"
            return f"错误: {r.get('error_message')}"
        return "请输入 Cypher 查询语句。"