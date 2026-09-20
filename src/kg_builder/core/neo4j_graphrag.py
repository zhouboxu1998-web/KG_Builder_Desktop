"""GraphRAG 相关的 LLM / Embedding / Driver 配置。

用于 SimpleKGPipeline 从非结构化文本抽取实体和关系：
    - LLM:      DeepSeek（OpenAI 兼容接口）
    - Embedder: 阿里云百炼（OpenAI 兼容接口）
    - Driver:   复用已有的 graphdb.get_driver()
"""

from functools import lru_cache

from neo4j_graphrag.embeddings import OpenAIEmbeddings
from neo4j_graphrag.llm import OpenAILLM

from kg_builder import config
from kg_builder.core.neo4j_client import graphdb


@lru_cache(maxsize=1)
def get_rag_llm() -> OpenAILLM:
    """用于实体和关系抽取的 LLM。

    注意：DeepSeek 不支持 structured output，需要显式关闭。
    """
    model_name = config.DEEPSEEK_MODEL.replace("deepseek/", "")
    llm = OpenAILLM(
        model_name=model_name,
        model_params={"temperature": 0},
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
    )
    # 关键：告诉 GraphRAG 不要使用 Structured Output
    llm.supports_structured_output = False
    return llm


@lru_cache(maxsize=1)
def get_rag_embedder() -> OpenAIEmbeddings:
    """用于文本块 Embedding 的模型。"""
    return OpenAIEmbeddings(
        model=config.EMBEDDING_MODEL,
        api_key=config.DASHSCOPE_API_KEY,
        base_url=config.DASHSCOPE_BASE_URL,
    )


def get_rag_driver():
    """复用 Neo4j client 的 driver。"""
    return graphdb.get_driver()