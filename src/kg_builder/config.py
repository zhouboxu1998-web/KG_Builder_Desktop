"""集中式配置：环境变量、路径、模型名。"""
import os
from pathlib import Path

from dotenv import load_dotenv, find_dotenv

# 只加载一次
_ = load_dotenv(find_dotenv())

# ---------- 路径 ----------
PACKAGE_DIR = Path(__file__).parent
PROMPTS_DIR = PACKAGE_DIR / "prompts"
PROJECT_ROOT = PACKAGE_DIR.parent.parent


def _path_from_env(key: str, default: str) -> Path:
    raw = os.getenv(key, default)
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


IMPORT_DIR = _path_from_env("NEO4J_IMPORT_DIR", "./data/import")

# ---------- LLM ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# ---------- Embedding ----------
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
EMBEDDING_MODEL = os.getenv("EMD_MODEL_NAME", "qwen3.7-text-embedding")


def ensure_import_dir() -> Path:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    return IMPORT_DIR