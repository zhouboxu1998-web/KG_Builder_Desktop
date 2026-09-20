"""Level 1：验证配置能正确读取。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kg_builder import config


def main():
    print("=" * 60)
    print("Level 1: 配置读取检查")
    print("=" * 60)

    checks = [
        ("DEEPSEEK_MODEL", config.DEEPSEEK_MODEL),
        ("DEEPSEEK_API_KEY", "***" + config.DEEPSEEK_API_KEY[-6:] if config.DEEPSEEK_API_KEY else "❌ 未设置"),
        ("DEEPSEEK_BASE_URL", config.DEEPSEEK_BASE_URL),
        ("IMPORT_DIR", str(config.IMPORT_DIR)),
        ("IMPORT_DIR 存在?", "✅" if config.IMPORT_DIR.exists() else "❌ 不存在"),
        ("DASHSCOPE_API_KEY", "***" + config.DASHSCOPE_API_KEY[-6:] if config.DASHSCOPE_API_KEY else "（可选，未设置）"),
    ]

    for name, value in checks:
        print(f"  {name:25s} = {value}")

    print()
    if not config.DEEPSEEK_API_KEY:
        print("❌ DEEPSEEK_API_KEY 未加载，请检查 .env 是否在项目根目录")
        sys.exit(1)
    if not config.IMPORT_DIR.exists():
        print(f"⚠️  import 目录不存在，正在创建: {config.IMPORT_DIR}")
        config.ensure_import_dir()
        print("✅ 已创建")

    print("✅ Level 1 通过")


if __name__ == "__main__":
    main()