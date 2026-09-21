"""桌面版启动入口。

关键：
    DPI 感知代码必须在 import tkinter 之前执行。
    否则 Tkinter 使用系统默认 DPI，字号会显得比系统其他软件小。
"""

import ctypes
import sys
from pathlib import Path


# ============================================================
# ★ DPI 感知（必须在 import tkinter 之前）
# ============================================================
def _enable_dpi_awareness():
    """启用 Windows DPI 感知，让界面跟随系统缩放。"""
    if sys.platform != "win32":
        return

    # Windows 8.1+：Per-Monitor DPI Aware
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    # Windows 8.1：System DPI Aware（降级）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass

    # Windows 7/8：传统 API
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()


# ============================================================
# 让 src 可导入
# ============================================================
_PROJECT_ROOT = Path(__file__).resolve().parent
_SRC = _PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ============================================================
# 启动
# ============================================================
from kg_builder.config import ensure_import_dir
from kg_builder.ui.app import App


def main():
    ensure_import_dir()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()