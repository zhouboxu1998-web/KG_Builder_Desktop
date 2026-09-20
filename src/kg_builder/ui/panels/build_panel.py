"""构建面板：支持结构化 CSV + 非结构化 Markdown + 实体解析。

支持的分类 state 键：
    - approved_structured_files    已批准的结构化文件（CSV/JSON）
    - approved_unstructured_files  已批准的非结构化文件（MD/TXT）

兼容旧字段：
    - approved_files               合并版（用于兜底）

命令：
    build        结构化导入（CSV → 领域图）
    build-unstr  非结构化抽取（MD → 主题图）
    resolve      实体解析（连接领域图和主题图）
    clear        清空数据库
    all          依次执行 build → build-unstr → resolve
"""

from kg_builder.tools.kg_build_tools import construct_domain_graph
from kg_builder.tools.kg_build_tools_unstructured import (
    build_unstructured_graph,
)
from kg_builder.tools.entity_resolution import (
    has_subject_graph,
    run_entity_resolution,
)
from kg_builder.ui.panels.base_panel import BasePanel
from kg_builder.state import (
    APPROVED_CONSTRUCTION_PLAN,
    APPROVED_ENTITIES,
    APPROVED_FACTS,
    APPROVED_FILES,
    PROPOSED_CONSTRUCTION_PLAN,
)


# ============================================================
# 分类 state 键（与 tools/file_selection.py 保持一致）
# ============================================================

APPROVED_STRUCTURED_FILES = "approved_structured_files"
APPROVED_UNSTRUCTURED_FILES = "approved_unstructured_files"

STRUCTURED_EXTS = (".csv", ".json", ".parquet", ".xlsx")
UNSTRUCTURED_EXTS = (".md", ".markdown", ".txt", ".pdf")


# ============================================================
# BuildPanel
# ============================================================

class BuildPanel(BasePanel):
    title = "⑥ 构建图谱"
    subtitle = "导入 CSV / 抽取 Markdown / 实体解析"

    def __init__(self, master, bridge, pipeline, **kwargs):
        self.pipeline = pipeline
        super().__init__(master, bridge, **kwargs)

    def on_enter_once(self):
        self.add_system_message(
            "可用命令：\n"
            "  · build         → 导入 CSV（结构化领域图）\n"
            "  · build-unstr   → 从 Markdown 抽取（非结构化主题图）\n"
            "  · resolve       → 实体解析（连接主题图 ↔ 领域图）\n"
            "  · clear         → 清空数据库（谨慎！）\n"
            "  · all           → 依次执行 build → build-unstr → resolve"
        )

    def on_send(self, text: str, on_chunk=None):
        # 构建命令是同步的，on_chunk 不用
        return self._handle(text)

    # ========================================================
    # 命令分发
    # ========================================================
    async def _handle(self, text: str) -> str:
        cmd = text.strip().lower()

        if cmd == "clear":
            return await self._clear()
        if cmd == "build":
            return await self._build_structured()
        if cmd in ("build-unstr", "build-unstructured"):
            return await self._build_unstructured()
        if cmd == "resolve":
            return await self._resolve()
        if cmd == "all":
            r1 = await self._build_structured()
            r2 = await self._build_unstructured()
            r3 = await self._resolve()
            return (
                f"## 结构化导入\n{r1}\n\n"
                f"## 非结构化抽取\n{r2}\n\n"
                f"## 实体解析\n{r3}"
            )

        return "可用命令: build / build-unstr / resolve / clear / all"

    # ========================================================
    # 辅助：读取分类文件列表（带兜底）
    # ========================================================
    async def _get_structured_files(self) -> list:
        """读取已批准的结构化文件。

        优先读分类 state；若不存在（旧会话），从合并列表里过滤。
        """
        files_caller = self.pipeline.session.files_caller
        if files_caller is None:
            return []

        state = (await files_caller.get_session()).state

        # 优先：分类 state
        files = state.get(APPROVED_STRUCTURED_FILES)
        if files:
            return list(files)

        # 兜底：从合并列表过滤
        merged = state.get(APPROVED_FILES, [])
        return [f for f in merged if f.lower().endswith(STRUCTURED_EXTS)]

    async def _get_unstructured_files(self) -> list:
        """读取已批准的非结构化文件。"""
        files_caller = self.pipeline.session.files_caller
        if files_caller is None:
            return []

        state = (await files_caller.get_session()).state

        # 优先：分类 state
        files = state.get(APPROVED_UNSTRUCTURED_FILES)
        if files:
            return list(files)

        # 兜底
        merged = state.get(APPROVED_FILES, [])
        return [f for f in merged if f.lower().endswith(UNSTRUCTURED_EXTS)]

    # ========================================================
    # clear
    # ========================================================
    async def _clear(self) -> str:
        from kg_builder.core.neo4j_client import graphdb
        r = graphdb.send_query(
            "MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
        )
        if r["status"] == "success":
            self.add_system_message("✅ 数据库已清空", "success")
            return "数据库已清空。"
        self.add_system_message(
            f"❌ 清空失败: {r.get('error_message')}", "error"
        )
        return f"清空失败: {r.get('error_message')}"

    # ========================================================
    # build（结构化）
    # ========================================================
    async def _build_structured(self) -> str:
        schema_caller = self.pipeline.session.schema_caller
        if schema_caller is None:
            msg = "❌ 请先完成「③ 图谱结构」阶段。"
            self.add_system_message(msg, "error")
            return msg

        # 检查是否有结构化文件被批准
        structured = await self._get_structured_files()
        if not structured:
            msg = "❌ 没有已批准的结构化文件（CSV/JSON），请回到「② 选择文件」重新批准。"
            self.add_system_message(msg, "warning")
            return msg

        session = await schema_caller.get_session()
        plan = session.state.get(APPROVED_CONSTRUCTION_PLAN) or \
               session.state.get(PROPOSED_CONSTRUCTION_PLAN)

        if not plan:
            msg = "❌ 没有可用的构建计划，请回到「③ 图谱结构」。"
            self.add_system_message(msg, "error")
            return msg

        self.add_system_message(
            f"开始导入 {len(plan)} 条规则（源文件 {len(structured)} 个）...",
            "info",
        )

        result = construct_domain_graph(plan)
        if result["status"] == "success":
            self.add_system_message("✅ 结构化导入成功！", "success")
            return "结构化图谱构建完成。"
        self.add_system_message(
            f"❌ 失败: {result.get('error_message')}", "error"
        )
        return f"结构化导入失败: {result.get('error_message')}"

    # ========================================================
    # build-unstr（非结构化）
    # ========================================================
    async def _build_unstructured(self) -> str:
        fact_caller = self.pipeline.session.fact_caller
        if fact_caller is None:
            msg = "❌ 请先完成「④ 实体识别」和「⑤ 事实类型」阶段。"
            self.add_system_message(msg, "error")
            return msg

        # 从 fact 阶段拿已批准的实体和事实
        fact_state = (await fact_caller.get_session()).state
        approved_entities = fact_state.get(APPROVED_ENTITIES, [])
        approved_facts = fact_state.get(APPROVED_FACTS, {})

        if not approved_entities:
            msg = "❌ 没有已批准的实体类型，请先完成「④ 实体识别」。"
            self.add_system_message(msg, "warning")
            return msg
        if not approved_facts:
            msg = "❌ 没有已批准的事实类型，请先完成「⑤ 事实类型」。"
            self.add_system_message(msg, "warning")
            return msg

        # 从分类 state 拿非结构化文件
        md_files = await self._get_unstructured_files()
        if not md_files:
            msg = (
                "❌ 没有已批准的非结构化文件（Markdown/TXT）。\n"
                "   请回到「② 选择文件」批准 .md 文件。"
            )
            self.add_system_message(msg, "warning")
            return msg

        self.add_system_message(
            f"开始从 {len(md_files)} 个非结构化文件抽取实体关系...",
            "info",
        )
        for f in md_files:
            self.add_system_message(f"  · {f}", "info")

        def progress(file_name):
            self.after(
                0,
                lambda fn=file_name: self.add_system_message(
                    f"  ⏳ 处理中: {fn}", "info"
                ),
            )

        result = await build_unstructured_graph(
            approved_files=md_files,
            approved_entities=approved_entities,
            approved_facts=approved_facts,
            progress_cb=progress,
        )

        if result["status"] != "success":
            msg = f"❌ 非结构化抽取失败: {result.get('error_message')}"
            self.add_system_message(msg, "error")
            return msg

        # 统计
        results = result.get("results", {})
        ok = sum(1 for v in results.values() if v.get("status") == "success")
        fail = len(results) - ok

        self.add_system_message(
            f"✅ 非结构化抽取完成：{ok}/{len(md_files)} 个文件成功"
            + (f"（{fail} 个失败）" if fail else ""),
            "success",
        )

        # 显示每个文件的统计
        for fname, v in results.items():
            if v.get("status") == "success":
                r = v.get("result", {})
                resolver = r.get("resolver", {}) if isinstance(r, dict) else {}
                n = resolver.get("number_of_created_nodes", "?")
                self.add_system_message(f"  · {fname}: 创建 {n} 个节点", "info")
            else:
                self.add_system_message(
                    f"  · {fname}: ❌ {v.get('error_message', '未知错误')}",
                    "error",
                )

        return f"完成。成功 {ok} / 共 {len(md_files)}。"

    # ========================================================
    # resolve（实体解析）
    # ========================================================
    async def _resolve(self) -> str:
        if not has_subject_graph():
            msg = (
                "⚠️ 数据库中没有 `__Entity__` 标签的节点。\n"
                "   实体解析需要主题图，请先执行：build-unstr"
            )
            self.add_system_message(msg, "warning")
            return msg

        self.add_system_message("开始实体解析...", "info")

        try:
            results = run_entity_resolution(similarity=0.8)
        except Exception as e:
            msg = f"❌ 实体解析失败: {e}"
            self.add_system_message(msg, "error")
            return msg

        matched = [r for r in results if r.get("matched")]
        self.add_system_message(
            f"✅ 实体解析完成：{len(matched)}/{len(results)} 个标签匹配成功",
            "success",
        )
        for r in matched:
            self.add_system_message(
                f"  · {r['label']}: {r['entity_key']} ↔ {r['domain_key']} "
                f"(相似度 {r['similarity']:.2f})",
                "info",
            )

        # 显示未匹配的
        unmatched = [r for r in results if not r.get("matched")]
        if unmatched:
            names = [r["label"] for r in unmatched]
            self.add_system_message(
                f"  ⚠️ 未匹配: {', '.join(names)}", "warning"
            )

        return f"完成。匹配 {len(matched)} / 共 {len(results)}。"