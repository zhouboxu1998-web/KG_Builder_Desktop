import os
import re
from pathlib import Path
from rapidfuzz import fuzz

from core.neo4j_client import graphdb
from core.helper import get_neo4j_import_dir
from core.tools import create_uniqueness_constraint, load_nodes_from_csv


# ==========================================
# 第一部分：结构化数据构建 (CSV -> Neo4j)
# ==========================================
def import_relationships(relationship_construction: dict) -> dict:
    """根据关系构建规则导入关系 (CSV)"""
    from_node_column = relationship_construction["from_node_column"]
    to_node_column = relationship_construction["to_node_column"]

    query = f"""LOAD CSV WITH HEADERS FROM "file:///" + $source_file AS row
    CALL (row) {{
        MATCH (from_node:$($from_node_label) {{ {from_node_column} : row[$from_node_column] }}),
              (to_node:$($to_node_label) {{ {to_node_column} : row[$to_node_column] }} )
        MERGE (from_node)-[r:$($relationship_type)]->(to_node)
        FOREACH (k IN $properties | SET r[k] = row[k])
    }} IN TRANSACTIONS OF 1000 ROWS
    """
    return graphdb.send_query(query, {
        "source_file": relationship_construction["source_file"],
        "from_node_label": relationship_construction["from_node_label"],
        "from_node_column": relationship_construction["from_node_column"],
        "to_node_label": relationship_construction["to_node_label"],
        "to_node_column": relationship_construction["to_node_column"],
        "relationship_type": relationship_construction["relationship_type"],
        "properties": relationship_construction["properties"]
    })


def construct_domain_graph(construction_plan: dict) -> dict:
    """构建完整的结构化图谱"""
    # 1. 导入节点
    node_constructions = [v for v in construction_plan.values() if v.get('construction_type') == 'node']
    for nc in node_constructions:
        res1 = create_uniqueness_constraint(nc["label"], nc["unique_column_name"])
        if res1.get("status") == "error": return res1
        res2 = load_nodes_from_csv(nc["source_file"], nc["label"], nc["unique_column_name"], nc["properties"])
        if res2.get("status") == "error": return res2

    # 2. 导入关系
    rel_constructions = [v for v in construction_plan.values() if v.get('construction_type') == 'relationship']
    for rc in rel_constructions:
        res = import_relationships(rc)
        if res.get("status") == "error": return res

    return {"status": "success", "message": "结构化图谱构建完成！"}


# ==========================================
# 第二部分：非结构化数据构建 (Markdown -> Neo4j)
# ==========================================
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from neo4j_graphrag.experimental.components.text_splitters.base import TextSplitter
from neo4j_graphrag.experimental.components.types import TextChunk, TextChunks
from neo4j_graphrag.experimental.components.pdf_loader import DataLoader
from neo4j_graphrag.experimental.components.types import PdfDocument, DocumentInfo
from neo4j_graphrag.llm import OpenAILLM
from neo4j_graphrag.embeddings import OpenAIEmbeddings


class RegexTextSplitter(TextSplitter):
    def __init__(self, re_pattern: str):
        self.re = re_pattern

    async def run(self, text: str) -> TextChunks:
        texts = re.split(self.re, text)
        chunks = [TextChunk(text=str(t), index=i) for i, t in enumerate(texts)]
        return TextChunks(chunks=chunks)


class MarkdownDataLoader(DataLoader):
    def extract_title(self, markdown_text):
        match = re.search(r'^# (.+)$', markdown_text, re.MULTILINE)
        return match.group(1) if match else "Untitled"

    async def run(self, filepath: Path, metadata={}) -> PdfDocument:
        with open(filepath, "r", encoding='utf-8') as f:
            markdown_text = f.read()
        doc_headline = self.extract_title(markdown_text)
        return PdfDocument(text=markdown_text,
                           document_info=DocumentInfo(path=str(filepath), metadata={"title": doc_headline}))


def file_context(file_path: str, num_lines=5) -> str:
    """提取文件开头作为上下文"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return "".join([f.readline() for _ in range(num_lines) if f.readline()])


async def build_unstructured_graph(approved_files: list, approved_entities: list, approved_fact_types: dict):
    """利用 GraphRAG 处理 Markdown 构建非结构化图谱"""
    # 过滤出 Markdown 文件
    md_files = [f for f in approved_files if str(f).endswith(".md")]
    if not md_files: return {"status": "success", "message": "没有找到 Markdown 文件，跳过非结构化处理。"}

    # 配置 LLM 和 Embedder (根据你的原代码)
    llm_for_neo4j = OpenAILLM(
        model_name=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        model_params={"temperature": 0},
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
    llm_for_neo4j.supports_structured_output = False

    embedder = OpenAIEmbeddings(
        model="qwen3.7-text-embedding",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # 构建 Schema
    schema_patterns = [[fact['subject_label'], fact['predicate_label'].upper(), fact['object_label']] for fact in
                       approved_fact_types.values()]
    entity_schema = {
        "node_types": approved_entities,
        "relationship_types": [k.upper() for k in approved_fact_types.keys()],
        "patterns": schema_patterns,
        "additional_node_types": False,
    }

    neo4j_import_dir = get_neo4j_import_dir()
    for file_name in md_files:
        file_path = os.path.join(neo4j_import_dir, file_name)
        context = file_context(file_path)
        prompt_template = f"上下文:\n<context>{context}</context>\n\n输入文本:\n{{text}}\n\n请提取符合以下Schema的实体和关系:\n{{schema}}"

        kg_builder = SimpleKGPipeline(
            llm=llm_for_neo4j, driver=graphdb.get_driver(), embedder=embedder,
            from_pdf=True, pdf_loader=MarkdownDataLoader(), text_splitter=RegexTextSplitter("---"),
            schema=entity_schema, prompt_template=prompt_template
        )
        await kg_builder.run_async(file_path=str(file_path))

    return {"status": "success", "message": "非结构化图谱构建完成！"}


# ==========================================
# 第三部分：实体消歧 (将两部分图谱融合)
# ==========================================
def run_entity_resolution():
    """执行实体消歧，利用 Jaro-Winkler 距离链接相同实体"""
    # 获取所有的 Entity 标签
    res = graphdb.send_query(
        """MATCH (n) WHERE n:`__Entity__` WITH DISTINCT labels(n) AS ls UNWIND ls AS l WITH l WHERE NOT l STARTS WITH "__" RETURN collect(distinct l) as labels""")
    if res.get("status") == "error": return res
    entity_labels = res["query_result"][0]["labels"]

    for label in entity_labels:
        # 你的原代码逻辑，简化执行 JaroWinkler 融合
        graphdb.send_query(f"""
        MATCH (entity:`{label}`:`__Entity__`), (domain:`{label}`)
        WHERE NOT domain:`__Entity__`
        // 假设大多数结构化节点有名为 name 或 id 的字段，非结构化节点有名为 id 的字段
        AND apoc.text.jaroWinklerDistance(entity.id, coalesce(domain.name, domain.id, '')) < 0.2
        MERGE (entity)-[r:CORRESPONDS_TO]->(domain)
        ON CREATE SET r.created_at = datetime()
        """)
    return {"status": "success", "message": "实体消歧与融合完成！"}