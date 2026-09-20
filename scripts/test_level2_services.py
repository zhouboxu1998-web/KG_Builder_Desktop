"""Level 2：Neo4j + DeepSeek 连通性检查。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kg_builder.core.neo4j_client import graphdb
from kg_builder.core.llm import get_llm


def check_neo4j():
    print("\n" + "-" * 60)
    print("2.1 Neo4j 连接检查")
    print("-" * 60)

    result = graphdb.send_query("RETURN 'Neo4j is Ready!' AS message")
    print(f"  原始返回: {result}")

    if result["status"] != "success":
        print(f"  ❌ 连接失败: {result.get('error_message')}")
        return False

    print(f"  ✅ Neo4j 可用: {result['query_result']}")

    # 额外检查 APOC 是否可用（后续实体解析会用到）
    apoc = graphdb.send_query("RETURN apoc.version() AS v")
    if apoc["status"] == "success":
        print(f"  ✅ APOC 版本: {apoc['query_result']}")
    else:
        print(f"  ⚠️  APOC 未安装: {apoc.get('error_message')}")
        print("     （部分高级功能不可用，但基础流程能跑）")

    return True


def check_deepseek():
    print("\n" + "-" * 60)
    print("2.2 DeepSeek LLM 检查")
    print("-" * 60)

    try:
        llm = get_llm()
        resp = llm.llm_client.completion(
            model=llm.model,
            messages=[{"role": "user", "content": "只回复两个字：你好"}],
            tools=[],
        )
        content = resp.choices[0].message.content
        print(f"  ✅ DeepSeek 回复: {content}")
        return True
    except Exception as e:
        print(f"  ❌ 调用失败: {e}")
        return False


def main():
    print("=" * 60)
    print("Level 2: 外部服务连通性检查")
    print("=" * 60)

    ok_neo4j = check_neo4j()
    ok_llm = check_deepseek()

    print("\n" + "=" * 60)
    if ok_neo4j and ok_llm:
        print("✅ Level 2 全部通过")
    else:
        print("❌ Level 2 未通过，请先解决上面的错误")
        sys.exit(1)


if __name__ == "__main__":
    main()