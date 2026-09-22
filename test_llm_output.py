"""诊断 SimpleKGPipeline 从 DeepSeek 拿到的原始输出。

用途：
    找出为什么 build-unstr 报 'nodes' KeyError。

运行：
    python test_llm_output.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from kg_builder.core.neo4j_graphrag import get_rag_llm


def main():
    print("=" * 70)
    print("测试 1: LLM 直接调用（模拟图谱抽取任务）")
    print("=" * 70)

    llm = get_rag_llm()

    prompt = """你是一种顶级的信息抽取算法，专门用于以结构化格式提取信息，以构建知识图谱。

从下面的文本中提取实体（节点），并指定每个实体的类型。
同时提取这些节点之间的关系。

使用以下格式将结果返回为 JSON：
{"nodes": [{"id": "0", "label": "Person", "properties": {"name": "John"}}],
"relationships": [{"type": "KNOWS", "start_node_id": "0", "end_node_id": "1", "properties": {}}]}

允许的节点类型：Product, Issue, Reviewer, Review
允许的关系类型：HAS_ISSUE, WRITTEN_BY

必须遵守：
- 只返回 JSON，不要任何其他文字
- 不要用反引号包裹

输入文本：

# Gothenburg Table Reviews

This table is beautiful but assembly was difficult. The pre-drilled holes didn't line up.

- @akollegger (Cambridge)
"""

    print("\n--- 发送请求 ---\n")

    try:
        response = llm.invoke(prompt)

        content = response.content

        print("--- 输出类型 ---")
        print(f"type: {type(content)}")
        print(f"长度: {len(content) if content else 0}")

        print("\n--- 原始输出（repr）---")
        print(repr(content))

        print("\n--- 可读输出 ---")
        print(content)

        # 尝试解析 JSON
        print("\n--- JSON 解析测试 ---")
        import json
        try:
            # 剥离可能的 markdown 代码块
            cleaned = content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])
            parsed = json.loads(cleaned)
            print(f"✅ 解析成功")
            print(f"顶层键: {list(parsed.keys())}")
            if "nodes" in parsed:
                print(f"nodes 数量: {len(parsed['nodes'])}")
            else:
                print(f"❌ 缺少 'nodes' 键！")
            if "relationships" in parsed:
                print(f"relationships 数量: {len(parsed['relationships'])}")
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
        except Exception as e:
            print(f"❌ 异常: {e}")

    except Exception as e:
        print(f"\n❌ LLM 调用失败: {e}")
        import traceback
        traceback.print_exc()

    # -----------------------------------------------------------
    print("\n\n" + "=" * 70)
    print("测试 2: 用 SimpleKGPipeline 的真实 prompt 模板")
    print("=" * 70)

    from kg_builder.tools.kg_build_tools_unstructured import (
        contextualize_er_extraction_prompt,
        file_context,
    )
    from kg_builder import config

    # 读取一个真实文件
    import_dir = Path(config.IMPORT_DIR)
    test_file = import_dir / "product_reviews" / "gothenburg_table_reviews.md"

    if not test_file.exists():
        print(f"\n⚠️ 测试文件不存在: {test_file}")
        # 尝试找任意一个 .md
        md_files = list((import_dir / "product_reviews").glob("*.md"))
        if md_files:
            test_file = md_files[0]
            print(f"使用替代文件: {test_file.name}")
        else:
            print("没有找到任何 .md 文件，跳过测试 2")
            return

    print(f"\n使用文件: {test_file.name}")

    # 读取前 10 行
    with open(test_file, "r", encoding="utf-8") as f:
        text = f.read()[:2000]

    context = file_context(str(test_file))
    template = contextualize_er_extraction_prompt(context)

    # 构造完整 prompt（模拟 SimpleKGPipeline 的渲染）
    entity_schema = {
        "node_types": ["Product", "Issue", "Reviewer", "Review"],
        "relationship_types": ["HAS_ISSUE", "WRITTEN_BY"],
        "patterns": [
            ["Product", "HAS_ISSUE", "Issue"],
            ["Review", "WRITTEN_BY", "Reviewer"],
        ],
    }

    full_prompt = template.replace("{schema}", str(entity_schema))
    full_prompt = full_prompt.replace("{text}", text)

    print(f"\nPrompt 总长度: {len(full_prompt)} 字符")
    print("\n--- 发送请求 ---\n")

    try:
        response = llm.invoke(full_prompt)
        content = response.content

        print(f"输出长度: {len(content) if content else 0}")
        print("\n--- 原始输出（repr，前 2000 字符）---")
        print(repr(content[:2000]))

        print("\n--- 可读输出（前 2000 字符）---")
        print(content[:2000])

        print("\n--- JSON 解析测试 ---")
        import json
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        try:
            parsed = json.loads(cleaned)
            print(f"✅ 解析成功，顶层键: {list(parsed.keys())}")
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")

    except Exception as e:
        print(f"\n❌ LLM 调用失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()