import asyncio

from kg_builder.core.tool_runtime import ToolRuntime
from kg_builder.core.errors import ToolInputError, ToolExecutionError


def add(a: int, b: int):
    return a + b


async def async_add(a: int, b: int):
    return a + b


def boom():
    raise ValueError("boom")


def main():
    assert ToolRuntime(add).run(a=1, b=2) == 3
    try:
        ToolRuntime(add).run(a=1)
    except ToolInputError:
        pass
    else:
        raise AssertionError("expected ToolInputError")
    try:
        ToolRuntime(boom).run()
    except ToolExecutionError:
        pass
    else:
        raise AssertionError("expected ToolExecutionError")
    assert asyncio.run(ToolRuntime(async_add).run_async(a=2, b=3)) == 5
    print("🎉 Level 23 Tool Runtime 全部通过")


if __name__ == "__main__":
    main()
