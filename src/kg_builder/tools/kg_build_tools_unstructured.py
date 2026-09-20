"""非结构化图谱构建：从 Markdown 文件抽取实体和关系。

对应 knowledge_graph_construction_2.ipynb 的核心逻辑：
    1. 自定义 RegexTextSplitter（按 --- 切分评论）
    2. 自定义 MarkdownDataLoader（读 .md 文件）
    3. 把 approved_entity_types / approved_fact_types 转成 entity_schema
    4. 为每个文件构造 SimpleKGPipeline 并执行
"""

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neo4j_graphrag.experimental.components.pdf_loader import DataLoader
from neo4j_graphrag.experimental.components.text_splitters.base import TextSplitter
from neo4j_graphrag.experimental.components.types import (
    DocumentInfo,
    PdfDocument,
    TextChunk,
    TextChunks,
)
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline

from kg_builder import config
from kg_builder.core.neo4j_graphrag import (
    get_rag_driver,
    get_rag_embedder,
    get_rag_llm,
)


# ============================================================
# 自定义组件
# ============================================================

class RegexTextSplitter(TextSplitter):
    """按正则分隔符切分文本。"""

    def __init__(self, pattern: str = "---"):
        self.pattern = pattern

    async def run(self, text: str) -> TextChunks:
        parts = re.split(self.pattern, text)
        chunks = [
            TextChunk(text=str(part), index=i)
            for i, part in enumerate(parts)
        ]
        return TextChunks(chunks=chunks)


class MarkdownDataLoader(DataLoader):
    """加载 Markdown 文件，自动提取一级标题作为文档标题。"""

    @staticmethod
    def _extract_title(md_text: str) -> str:
        match = re.search(r"^# (.+)$", md_text, re.MULTILINE)
        return match.group(1) if match else "Untitled"

    async def run(self, filepath: Path, metadata: dict = None) -> PdfDocument:
        with open(filepath, "r", encoding="utf-8") as f:
            md_text = f.read()

        title = self._extract_title(md_text)
        info = DocumentInfo(
            path=str(filepath),
            metadata={"title": title},
        )
        return PdfDocument(text=md_text, document_info=info)


# ============================================================
# 上下文提取 + Prompt 构造
# ============================================================

def file_context(file_path: str, num_lines: int = 5) -> str:
    """读取文件前几行作为上下文。"""
    with open(file_path, "r", encoding="utf-8") as f:
        lines = []
        for _ in range(num_lines):
            line = f.readline()
            if not line:
                break
            lines.append(line)
    return "\n".join(lines)


def contextualize_er_extraction_prompt(context: str) -> str:
    """构造带有文件上下文的实体/关系抽取 Prompt。"""
    general_instructions = """
    你是一种顶级的信息抽取算法，专门用于以结构化格式提取信息，以构建知识图谱。

    从下面的文本中提取实体（节点），并指定每个实体的类型。
    同时提取这些节点之间的关系。

    使用以下格式将结果返回为 JSON：
    {"nodes": [ {"id": "0", "label": "Person", "properties": {"name": "John"}} ],
    "relationships": [{"type": "KNOWS", "start_node_id": "0", "end_node_id": "1", "properties": {}}] }

    只能使用下面提供的节点类型和关系类型：
    {schema}

    为每个节点分配一个唯一的 ID（字符串），并在定义关系时重复使用这个 ID。

    必须遵守关系的起点节点类型、终点节点类型以及关系方向。

    为确保生成有效的 JSON 对象，请遵守以下规则：
    - 除 JSON 之外，不要返回任何额外信息。
    - 不要在 JSON 外使用反引号，直接输出 JSON。
    - JSON 对象本身不能被包裹在列表中，它必须独立作为一个 JSON 对象。
    - 属性名称必须使用双引号括起来。
    """

    context_goes_here = f"""
    请考虑以下上下文，以帮助识别实体和关系：
    <context>
    {context}
    </context>
    """

    input_goes_here = """
    输入文本：

    {text}
    """

    return general_instructions + "\n" + context_goes_here + "\n" + input_goes_here


# ============================================================
# Entity Schema 构造
# ============================================================

def build_entity_schema(
    approved_entities: List[str],
    approved_facts: Dict[str, dict],
) -> dict:
    """把批准的实体类型和事实类型转成 SimpleKGPipeline 需要的 schema。"""
    node_types = list(approved_entities)
    relationship_types = [k.upper() for k in approved_facts.keys()]
    patterns = [
        [
            fact["subject_label"],
            fact["predicate_label"].upper(),
            fact["object_label"],
        ]
        for fact in approved_facts.values()
    ]

    return {
        "node_types": node_types,
        "relationship_types": relationship_types,
        "patterns": patterns,
        "additional_node_types": False,
    }


# ============================================================
# KG Builder 工厂
# ============================================================

def make_kg_builder(
    file_path: str,
    entity_schema: dict,
) -> SimpleKGPipeline:
    """为单个文件构造一个知识图谱构建 Pipeline。"""
    context = file_context(file_path)
    prompt = contextualize_er_extraction_prompt(context)

    return SimpleKGPipeline(
        llm=get_rag_llm(),
        driver=get_rag_driver(),
        embedder=get_rag_embedder(),
        from_pdf=True,
        pdf_loader=MarkdownDataLoader(),
        text_splitter=RegexTextSplitter("---"),
        schema=entity_schema,
        prompt_template=prompt,
    )


# ============================================================
# 批量执行
# ============================================================

async def build_unstructured_graph(
    approved_files: List[str],
    approved_entities: List[str],
    approved_facts: Dict[str, dict],
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """为已批准的所有 Markdown 文件构建非结构化图谱。

    Args:
        approved_files: 相对 IMPORT_DIR 的文件路径列表
        approved_entities: 已批准的实体类型
        approved_facts: 已批准的事实类型
        progress_cb: 可选回调，每处理完一个文件调用一次

    Returns:
        {'status': 'success', 'results': {...}}
        或
        {'status': 'error', 'error_message': '...'}
    """
    if not approved_entities:
        return {
            "status": "error",
            "error_message": "缺少 approved_entity_types，请先完成 NER 阶段",
        }
    if not approved_facts:
        return {
            "status": "error",
            "error_message": "缺少 approved_fact_types，请先完成事实类型阶段",
        }

    entity_schema = build_entity_schema(approved_entities, approved_facts)

    import_dir = Path(config.IMPORT_DIR)
    results = {}

    for file_name in approved_files:
        # 只处理 .md / .txt
        if not file_name.lower().endswith((".md", ".txt", ".markdown")):
            continue

        file_path = import_dir / file_name
        if not file_path.exists():
            results[file_name] = {"status": "error", "message": "文件不存在"}
            continue

        if progress_cb:
            progress_cb(file_name)

        try:
            builder = make_kg_builder(str(file_path), entity_schema)
            result = await builder.run_async(file_path=str(file_path))
            results[file_name] = {
                "status": "success",
                "result": result.result,
            }
        except Exception as e:
            results[file_name] = {
                "status": "error",
                "error_message": str(e),
            }

    return {"status": "success", "results": results}