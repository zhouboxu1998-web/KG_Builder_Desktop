"""ADK 知识图谱构建器 - 主窗口。

结构：
    左侧：导航栏（7 个阶段按钮 + 状态栏）
    右侧：面板容器

关键修复记录：
    v1: 状态栏永远"检查中…" —— future 未绑定回调
    v2: 修复为 add_done_callback + after(0, ...) 切主线程
    v3: 加入 run_in_executor + wait_for，避免 TCP 阻塞
    v4: 状态栏改为可点击按钮
    v5: STEPS 从 5 步扩展到 7 步（加入 NER 和 Fact）
"""

import asyncio

import customtkinter as ctk

from kg_builder.agents.pipeline import KGBuilderPipeline
from kg_builder.core.neo4j_client import graphdb
from kg_builder.ui.async_bridge import AsyncBridge
from kg_builder.ui.panels.build_panel import BuildPanel
from kg_builder.ui.panels.fact_panel import FactPanel
from kg_builder.ui.panels.files_panel import FilesPanel
from kg_builder.ui.panels.goal_panel import GoalPanel
from kg_builder.ui.panels.ner_panel import NerPanel
from kg_builder.ui.panels.query_panel import QueryPanel
from kg_builder.ui.panels.schema_panel import SchemaPanel
from kg_builder.ui.theme import (
    COLORS,
    FONT_BODY,
    FONT_HEADER,
    FONT_SMALL,
)


# ============================================================
# 7 个阶段定义
# ============================================================

STEPS = [
    ("1", "定义目标", GoalPanel),
    ("2", "选择文件", FilesPanel),
    ("3", "图谱结构", SchemaPanel),
    ("4", "实体识别", NerPanel),
    ("5", "事实类型", FactPanel),
    ("6", "构建", BuildPanel),
    ("7", "查询", QueryPanel),
]


# ============================================================
# 主窗口
# ============================================================

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ---------- 窗口基本设置 ----------
        self.title("🧠 ADK 知识图谱构建器")
        self.geometry("1100x760")
        self.minsize(900, 600)
        self.configure(fg_color=COLORS["bg"])

        # ---------- 内部状态 ----------
        self.bridge = AsyncBridge()
        self.pipeline = KGBuilderPipeline()
        self.panels = {}
        self.current_panel_key = None

        # ---------- 构建 UI ----------
        self._build_layout()

        # ---------- 首次检查 Neo4j ----------
        self._check_neo4j()

        # ---------- 关闭钩子 ----------
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ========================================================
    # 布局
    # ========================================================
    def _build_layout(self):
        # ---------- 左侧导航栏 ----------
        self.sidebar = ctk.CTkFrame(
            self,
            width=220,
            fg_color=COLORS["panel"],
            corner_radius=0,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # 标题
        ctk.CTkLabel(
            self.sidebar,
            text="🧠 KG Builder",
            font=FONT_HEADER,
            text_color=COLORS["text"],
        ).pack(pady=(24, 8), padx=20, anchor="w")

        ctk.CTkLabel(
            self.sidebar,
            text="基于 Google ADK",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(padx=20, anchor="w")

        # 分隔线
        ctk.CTkFrame(
            self.sidebar, height=1, fg_color=COLORS["accent"]
        ).pack(fill="x", padx=12, pady=16)

        # 阶段按钮
        self.nav_buttons = {}
        for key, label, _ in STEPS:
            btn = ctk.CTkButton(
                self.sidebar,
                text=f"{key}.  {label}",
                anchor="w",
                height=40,
                font=FONT_BODY,
                fg_color="transparent",
                hover_color=COLORS["accent"],
                text_color=COLORS["text"],
                command=lambda k=key: self.show_panel(k),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = btn

        # ---------- 底部状态（可点击刷新）----------
        status_wrapper = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        status_wrapper.pack(side="bottom", fill="x", pady=15, padx=12)

        self.status_btn = ctk.CTkButton(
            status_wrapper,
            text="● 检查中…",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            fg_color="transparent",
            hover_color=COLORS["accent"],
            anchor="w",
            height=28,
            command=self._check_neo4j,
        )
        self.status_btn.pack(fill="x")

        ctk.CTkLabel(
            status_wrapper,
            text="（点击可重新检查）",
            font=(FONT_SMALL[0], 9),
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=8)

        # ---------- 右侧面板容器 ----------
        self.container = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        self.container.pack(side="right", fill="both", expand=True)

        # 预创建所有面板
        for key, _, panel_cls in STEPS:
            frame = panel_cls(self.container, self.bridge, self.pipeline)
            self.panels[key] = frame

        # 默认显示第一个
        self.show_panel(STEPS[0][0])

    # ========================================================
    # 面板切换
    # ========================================================
    def show_panel(self, key: str):
        if self.current_panel_key == key:
            return

        # 隐藏旧面板
        if self.current_panel_key is not None:
            self.panels[self.current_panel_key].pack_forget()
            self.nav_buttons[self.current_panel_key].configure(
                fg_color="transparent"
            )

        # 显示新面板
        panel = self.panels[key]
        panel.pack(fill="both", expand=True)
        self.nav_buttons[key].configure(fg_color=COLORS["accent"])
        self.current_panel_key = key

        # 触发面板的 on_enter
        try:
            panel.on_enter()
        except Exception as e:
            print(f"[App] 面板 {key} 的 on_enter 出错: {e}")

    # ========================================================
    # Neo4j 健康检查
    # ========================================================
    def _check_neo4j(self):
        """异步 ping Neo4j，完成后更新状态栏。"""
        self.status_btn.configure(
            text="● 检查中…",
            text_color=COLORS["muted"],
        )

        future = self.bridge.submit(self._async_ping(timeout=5.0))
        future.add_done_callback(self._on_ping_done)

    def _on_ping_done(self, future):
        """在 bridge 线程里被调用，必须用 self.after 切回主线程。"""
        try:
            ok = future.result()
        except Exception as e:
            print(f"[Neo4j] ping future 异常: {e}")
            ok = False

        text = "● Neo4j 已连接" if ok else "● Neo4j 未连接"
        color = COLORS["success"] if ok else COLORS["error"]

        try:
            self.after(0, lambda: self.status_btn.configure(
                text=text, text_color=color
            ))
        except Exception:
            pass

    async def _async_ping(self, timeout: float = 5.0) -> bool:
        """带超时的异步 ping（避免 TCP 阻塞）。"""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, graphdb.ping),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            print(f"[Neo4j] ping 超时 (>{timeout}s)")
            return False
        except Exception as e:
            print(f"[Neo4j] ping 异常: {e}")
            return False

    # ========================================================
    # 关闭
    # ========================================================
    def _on_close(self):
        """关闭窗口时清理资源。"""
        try:
            graphdb.close()
        except Exception as e:
            print(f"[App] 关闭 Neo4j 出错: {e}")

        try:
            self.bridge.stop()
        except Exception as e:
            print(f"[App] 关闭 bridge 出错: {e}")

        try:
            self.destroy()
        except Exception:
            pass


# ============================================================
# 调试入口
# ============================================================

def main():
    """供 `python -m kg_builder.ui.app` 直接启动用。"""
    from kg_builder.config import ensure_import_dir
    ensure_import_dir()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()