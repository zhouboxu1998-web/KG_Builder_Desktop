"""文件相关工具：列出、采样、搜索。"""
from itertools import islice
from pathlib import Path
from typing import Optional

from google.adk.tools import ToolContext

from kg_builder import config
from kg_builder.core.neo4j_client import tool_error, tool_success
from kg_builder.state import ALL_AVAILABLE_FILES

SEARCH_RESULTS = "search_results"


def list_available_files(tool_context: ToolContext) -> dict:
    """列出 Neo4j import 目录下所有文件（相对路径）。"""
    import_dir = Path(config.IMPORT_DIR)
    if not import_dir.exists():
        return tool_error(f"import 目录不存在: {import_dir}")

    file_names = [
        str(x.relative_to(import_dir)).replace("\\", "/")
        for x in import_dir.rglob("*")
        if x.is_file()
    ]
    tool_context.state[ALL_AVAILABLE_FILES] = file_names
    return tool_success(ALL_AVAILABLE_FILES, file_names)


def sample_file(file_path: str, tool_context: Optional[ToolContext] = None) -> dict:
    """读取文本文件前 100 行。"""
    if Path(file_path).is_absolute():
        return tool_error("file_path 必须是相对于 import 目录的相对路径。")

    import_dir = Path(config.IMPORT_DIR)
    full = import_dir / file_path
    if not full.exists():
        return tool_error(f"文件不存在: {file_path}")
    if not full.is_file():
        return tool_error(f"不是文件: {file_path}")

    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = "".join(islice(f, 100))
        return tool_success("content", content)
    except Exception as e:
        return tool_error(f"读取文件出错: {e}")


def search_file(file_path: str, query: str) -> dict:
    """在文件中搜索字符串（不区分大小写）。"""
    import_dir = Path(config.IMPORT_DIR)
    p = import_dir / file_path
    if not p.exists():
        return tool_error(f"文件不存在: {file_path}")
    if not p.is_file():
        return tool_error(f"不是文件: {file_path}")

    if not query:
        return tool_success(
            SEARCH_RESULTS,
            {
                "metadata": {"path": file_path, "query": query, "lines_found": 0},
                "matching_lines": [],
            },
        )

    matches = []
    q = query.lower()
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if q in line.lower():
                    matches.append({"line_number": i, "content": line.strip()})
    except Exception as e:
        return tool_error(f"搜索文件出错: {e}")

    return tool_success(
        SEARCH_RESULTS,
        {
            "metadata": {
                "path": file_path,
                "query": query,
                "lines_found": len(matches),
            },
            "matching_lines": matches,
        },
    )