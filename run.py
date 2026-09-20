"""桌面版启动入口。"""
import sys
from pathlib import Path

# 让 src 可导入
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kg_builder.config import ensure_import_dir
from kg_builder.ui.app import App


def main():
    ensure_import_dir()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()