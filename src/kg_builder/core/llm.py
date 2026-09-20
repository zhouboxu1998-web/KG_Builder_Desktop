"""LLM 工厂，返回 Google ADK 的 LiteLlm 实例。"""
from functools import lru_cache

from google.adk.models.lite_llm import LiteLlm

from kg_builder import config


@lru_cache(maxsize=1)
def get_llm() -> LiteLlm:
    return LiteLlm(model=config.DEEPSEEK_MODEL)