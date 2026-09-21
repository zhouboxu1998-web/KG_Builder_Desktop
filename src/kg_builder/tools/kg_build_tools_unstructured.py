"""非结构化图谱构建：手写 prompt + 关闭结构化输出。

核心：
    - 使用我们自定义的简洁 prompt（原始 notebook 版本）
    - LLMEntityRelationExtractor(use_structured_output=False)
    - 兼容 neo4j-graphrag 1.14+ / 1.19.0 的 import 路径
"""

import importlib
import inspect
import re
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from kg_builder import config
from kg_builder.core.neo4j_graphrag import (
    get_rag_driver,
    get_rag_embedder,
    get_rag_llm,
)


# ============================================================
# 一、兼容多版本导入
# ============================================================

def _import_any(module_paths: List[str], class_name: str):
    """从多个模块路径尝试导入同一个类。"""
    for mp in module_paths:
        try:
            mod = importlib.import_module(mp)
            if hasattr(mod, class_name):
                return getattr(mod, class_name)
        except ImportError:
            continue
    raise ImportError(f"找不到 {class_name}，尝试过: {module_paths}")


# 文本切分器
TextSplitter = _import_any(
    [
        "neo4j_graphrag.components.text_splitters.base",
        "neo4j_graphrag.experimental.components.text_splitters.base",
    ],
    "TextSplitter",
)

# 类型
_types_mod = None
for _p in [
    "neo4j_graphrag.components.types",
    "neo4j_graphrag.experimental.components.types",
]:
    try:
        _types_mod = importlib.import_module(_p)
        break
    except ImportError:
        continue
if _types_mod is None:
    raise ImportError("找不到 types 模块")

TextChunk = _types_mod.TextChunk
TextChunks = _types_mod.TextChunks

# 实体关系抽取器
_er_mod = None
for _p in [
    "neo4j_graphrag.components.entity_relation_extractor",
    "neo4j_graphrag.experimental.components.entity_relation_extractor",
]:
    try:
        _er_mod = importlib.import_module(_p)
        break
    except ImportError:
        continue
if _er_mod is None:
    raise ImportError("找不到 entity_relation_extractor 模块")

LLMEntityRelationExtractor = _er_mod.LLMEntityRelationExtractor
OnError = getattr(_er_mod, "OnError", None)

# Writer
Neo4jWriter = _import_any(
    [
        "neo4j_graphrag.components.kg_writer",
        "neo4j_graphrag.experimental.components.kg_writer",
        "neo4j_graphrag.experimental.components.neo4j_writer",
    ],
    "Neo4jWriter",
)


# ============================================================
# 二、参数过滤工具
# ============================================================

def _filter_kwargs(cls, **candidates):
    """只保留目标类 __init__ 签名中实际存在的参数。"""
    try:
        sig = inspect.signature(cls.__init__)
        valid = set(sig.parameters.keys())
    except Exception:
        valid = set(candidates.keys())
    return {k: v for k, v in candidates.items() if k in valid}


# ============================================================
# 三、★ 自定义 prompt（原始简洁版）
# ============================================================

def contextualize_er_extraction_prompt(context: str) -> str:
    """构造带有文件上下文的实体/关系抽取 Prompt（原始简洁版）。

    注意：
        - 保留 {schema} 和 {text} 占位符，库会替换它们
        - 返回的字符串将作为 LLMEntityRelationExtractor 的 prompt_template
    """

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


def file_context(file_path: str, num_lines: int = 5) -> str:
    """读取文件前几行作为上下文。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = []
            for _ in range(num_lines):
                line = f.readline()
                if not line:
                    break
                lines.append(line)
        return "\n".join(lines)
    except Exception:
        return ""


# ============================================================
# 四、自定义文本切分器
# ============================================================

class RegexTextSplitter(TextSplitter):
    """按正则分隔符切分文本。"""

    def __init__(self, pattern: str = "---"):
        self.pattern = pattern

    async def run(self, text: str) -> TextChunks:
        parts = re.split(self.pattern, text)
        chunks = []
        for i, p in enumerate(parts):
            stripped = (p or "").strip()
            if stripped and len(stripped) > 10:
                chunks.append(TextChunk(text=stripped, index=i))
        return TextChunks(chunks=chunks)


# ============================================================
# 五、Schema 构造
# ============================================================

def build_entity_schema(
    approved_entities: List[str],
    approved_facts: Dict[str, dict],
) -> dict:
    """把批准的实体类型和事实类型转成 schema dict。"""
    node_types = list(approved_entities)

    relationship_types = list({
        f["predicate_label"].upper()
        for f in approved_facts.values()
    })

    patterns = [
        [
            f["subject_label"],
            f["predicate_label"].upper(),
            f["object_label"],
        ]
        for f in approved_facts.values()
    ]

    return {
        "node_types": node_types,
        "relationship_types": relationship_types,
        "patterns": patterns,
        "additional_node_types": False,
    }


# ============================================================
# 六、主入口
# ============================================================

async def build_unstructured_graph(
    approved_files: List[str],
    approved_entities: List[str],
    approved_facts: Dict[str, dict],
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """使用底层组件从 Markdown 构建非结构化图谱。

    ★ 关键：
        - 使用我们自定义的简洁 prompt
        - use_structured_output=False（兼容 DeepSeek）
    """
    if not approved_entities:
        return {"status": "error", "error_message": "缺少 approved_entity_types"}

    if not approved_facts:
        return {"status": "error", "error_message": "缺少 approved_fact_types"}

    # 1. Schema
    schema_dict = build_entity_schema(approved_entities, approved_facts)
    print(
        f"[build-unstr] Schema 就绪: "
        f"{len(schema_dict['node_types'])} 节点, "
        f"{len(schema_dict['relationship_types'])} 关系"
    )

    # 2. 组件
    try:
        llm = get_rag_llm()
        driver = get_rag_driver()

        text_splitter = RegexTextSplitter(pattern="---")

        # ★ 构造自定义 prompt（用第一个文件的上下文，作为全局模板）
        # 由于 ERExtractionTemplate 需要 {schema} 和 {text} 占位符，
        # 我们先用空 context 生成一个基础模板
        custom_prompt = contextualize_er_extraction_prompt("")

        # extractor（动态过滤参数）
        extractor_kwargs = _filter_kwargs(
            LLMEntityRelationExtractor,
            llm=llm,
            on_error=OnError.RAISE if OnError else None,
            use_structured_output=False,
            structured_output=False,
            prompt_template=custom_prompt,       # ★ 传入自定义 prompt
            create_lexical_graph=False,
        )
        extractor_kwargs = {
            k: v for k, v in extractor_kwargs.items() if v is not None
        }
        print(f"[build-unstr] Extractor 参数: {list(extractor_kwargs.keys())}")

        extractor = LLMEntityRelationExtractor(**extractor_kwargs)

        # 兜底：直接设置属性
        for attr in ("use_structured_output", "structured_output"):
            if hasattr(extractor, attr):
                try:
                    setattr(extractor, attr, False)
                    print(f"[build-unstr] 强制 {attr}=False")
                except Exception:
                    pass

        # writer
        writer_kwargs = _filter_kwargs(
            Neo4jWriter,
            driver=driver,
            neo4j_database=(
                getattr(config, "NEO4J_DATABASE", None) or "neo4j"
            ),
        )
        print(f"[build-unstr] Writer 参数: {list(writer_kwargs.keys())}")
        writer = Neo4jWriter(**writer_kwargs)

    except Exception as e:
        traceback.print_exc()
        return {
            "status": "error",
            "error_message": f"初始化组件失败: {e}",
        }

    # 3. 逐文件处理
    import_dir = Path(config.IMPORT_DIR)
    results = {}

    for file_name in approved_files:
        if not file_name.lower().endswith((".md", ".markdown", ".txt")):
            continue

        file_path = import_dir / file_name
        if not file_path.exists():
            results[file_name] = {
                "status": "error",
                "error_message": f"文件不存在: {file_path}",
            }
            continue

        if progress_cb:
            progress_cb(file_name)

        try:
            # a. 读文件
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()

            # b. 切分
            chunks = await text_splitter.run(text)
            if not chunks.chunks:
                results[file_name] = {
                    "status": "error",
                    "error_message": "切分后无有效块",
                }
                continue

            # c. 抽取
            try:
                graph = await extractor.run(
                    chunks=chunks, schema=schema_dict
                )
            except TypeError:
                graph = await extractor.run(chunks, schema_dict)

            # d. 写入
            try:
                await writer.run(graph)
            except TypeError:
                await writer.run(graph=graph)

            # e. 统计
            nodes_count = 0
            for attr in ("nodes", "entities"):
                if hasattr(graph, attr):
                    try:
                        nodes_count = len(getattr(graph, attr))
                        break
                    except Exception:
                        pass

            results[file_name] = {
                "status": "success",
                "result": {
                    "resolver": {
                        "number_of_created_nodes": nodes_count,
                    }
                },
            }
            print(
                f"[build-unstr] ✓ {file_name} "
                f"({len(chunks.chunks)} 块, {nodes_count} 节点)"
            )

        except Exception as e:
            tb = traceback.format_exc()
            print(f"\n[build-unstr] ✗ {file_name} 失败：")
            print(tb)
            results[file_name] = {
                "status": "error",
                "error_message": str(e),
            }

    # 4. 汇总
    ok = sum(1 for v in results.values() if v.get("status") == "success")
    print(f"\n[build-unstr] 完成：{ok}/{len(results)}")

    return {"status": "success", "results": results}