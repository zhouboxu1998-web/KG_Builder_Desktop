"""ADK 知识图谱构建器 - 主窗口（8 阶段现代化版）。

视觉风格：
    - 左侧导航栏：序号 + 名称
    - 当前项：靛蓝指示条 + 卡片背景 + 深色文字
    - 其他项：透明背景 + 灰色文字
    - 底部状态指示灯
    - 无 emoji，克制专业

修复记录：
    - FONT_FAMILY 导入缺失
    - 8 阶段 STEPS
    - alpha 0.99 触发 DWM 合成，减少切换焦点闪烁
    - 去掉"已访问绿点"（语义不清晰）
"""

import asyncio

import customtkinter as ctk

from kg_builder import config
from kg_builder.agents.pipeline import KGBuilderPipeline
from kg_builder.core.neo4j_client import graphdb
from kg_builder.ui.async_bridge import AsyncBridge
from kg_builder.ui.panels.build_panel import BuildPanel
from kg_builder.ui.panels.fact_panel import FactPanel
from kg_builder.ui.panels.goal_panel import GoalPanel
from kg_builder.ui.panels.ner_panel import NerPanel
from kg_builder.ui.panels.query_panel import QueryPanel
from kg_builder.ui.panels.schema_panel import SchemaPanel
from kg_builder.ui.panels.structured_files_panel import (
    StructuredFilesPanel,
)
from kg_builder.ui.panels.unstructured_files_panel import (
    UnstructuredFilesPanel,
)
from kg_builder.ui.theme import (
    BTN_RADIUS,
    COLORS,
    FONT_BODY,
    FONT_FAMILY,
    FONT_MONO_SM,
    FONT_SMALL,
    FONT_TINY,
    FONT_TITLE,
    SIDEBAR_WIDTH,
)


STEPS = [
    ("1", "定义目标",       GoalPanel),
    ("2", "结构化文件",     StructuredFilesPanel),
    ("3", "图谱结构",       SchemaPanel),
    ("4", "非结构化文件",   UnstructuredFilesPanel),
    ("5", "实体识别",       NerPanel),
    ("6", "事实类型",       FactPanel),
    ("7", "构建",           BuildPanel),
    ("8", "查询",           QueryPanel),
]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("知识图谱构建器")
        self.geometry("1180x800")
        self.minsize(1000, 640)
        self.configure(fg_color=COLORS["bg"])

        # 触发 Windows DWM 合成，减少切换焦点时的闪烁
        try:
            self.attributes("-alpha", 0.99)
        except Exception:
            pass

        self.bridge = AsyncBridge()
        self.pipeline = KGBuilderPipeline()
        self.panels = {}
        self.nav_items = {}
        self.current_panel_key = None

        self._build_layout()
        self._check_neo4j()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ========================================================
    # 布局
    # ========================================================
    def _build_layout(self):
        # ---------- 侧边栏 ----------
        self.sidebar = ctk.CTkFrame(
            self,
            width=SIDEBAR_WIDTH,
            fg_color=COLORS["panel"],
            corner_radius=0,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self._build_brand()
        self._build_nav()
        self._build_status()

        # ---------- 主区域 ----------
        self.container = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        self.container.pack(side="right", fill="both", expand=True)

        for key, _, panel_cls in STEPS:
            frame = panel_cls(self.container, self.bridge, self.pipeline)
            self.panels[key] = frame

        self.show_panel(STEPS[0][0])

    def _build_brand(self):
        """顶部品牌区。"""
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 18))

        # 品牌图标：方形色块 + KG 字母
        icon_box = ctk.CTkFrame(
            brand,
            width=36,
            height=36,
            fg_color=COLORS["primary"],
            corner_radius=10,
        )
        icon_box.pack(side="left")
        icon_box.pack_propagate(False)

        ctk.CTkLabel(
            icon_box,
            text="KG",
            font=(FONT_FAMILY, 13, "bold"),
            text_color="#ffffff",
        ).pack(expand=True)

        # 品牌名
        name_box = ctk.CTkFrame(brand, fg_color="transparent")
        name_box.pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            name_box,
            text="KG Builder",
            font=FONT_TITLE,
            text_color=COLORS["text"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            name_box,
            text="Google ADK",
            font=FONT_TINY,
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(anchor="w")

    def _build_nav(self):
        """导航项列表。"""
        ctk.CTkLabel(
            self.sidebar,
            text="工作流程",
            font=(FONT_TINY[0], 10, "bold"),
            text_color=COLORS["dim"],
            anchor="w",
        ).pack(fill="x", padx=22, pady=(12, 6))

        nav_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", padx=8)

        for key, label, _ in STEPS:
            self._create_nav_item(nav_frame, key, label)

    def _create_nav_item(self, parent, key: str, label: str):
        """创建单个导航项：指示条 + 序号 + 名称。"""
        item = ctk.CTkFrame(
            parent,
            height=42,
            fg_color="transparent",
            corner_radius=BTN_RADIUS,
        )
        item.pack(fill="x", pady=2)
        item.pack_propagate(False)

        # 左侧指示条
        indicator = ctk.CTkFrame(
            item,
            width=3,
            fg_color="transparent",
            corner_radius=2,
        )
        indicator.pack(side="left", fill="y", pady=9)

        # 序号（等宽字体）
        idx_lbl = ctk.CTkLabel(
            item,
            text=f"{key.zfill(2)}",
            font=FONT_MONO_SM,
            text_color=COLORS["dim"],
            width=24,
        )
        idx_lbl.pack(side="left", padx=(12, 8))

        # 名称
        name_lbl = ctk.CTkLabel(
            item,
            text=label,
            font=FONT_BODY,
            text_color=COLORS["text_soft"],
            anchor="w",
        )
        name_lbl.pack(side="left", fill="x", expand=True)

        # 点击事件
        for w in (item, idx_lbl, name_lbl):
            w.bind("<Button-1>", lambda e, k=key: self.show_panel(k))
            w.configure(cursor="hand2")

        # hover
        def on_enter(_e):
            if self.current_panel_key != key:
                item.configure(fg_color=COLORS["card_hover"])

        def on_leave(_e):
            if self.current_panel_key != key:
                item.configure(fg_color="transparent")

        item.bind("<Enter>", on_enter)
        item.bind("<Leave>", on_leave)

        self.nav_items[key] = {
            "frame": item,
            "indicator": indicator,
            "name": name_lbl,
            "idx": idx_lbl,
        }

    def _build_status(self):
        """底部状态栏。"""
        wrapper = ctk.CTkFrame(
            self.sidebar,
            fg_color=COLORS["card"],
            corner_radius=12,
        )
        wrapper.pack(side="bottom", fill="x", padx=14, pady=14)

        inner = ctk.CTkFrame(wrapper, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)

        # 状态指示点
        self._status_dot = ctk.CTkFrame(
            inner,
            width=8,
            height=8,
            fg_color=COLORS["muted"],
            corner_radius=4,
        )
        self._status_dot.pack(side="left")
        self._status_dot.pack_propagate(False)

        # 状态文字
        self._status_label = ctk.CTkLabel(
            inner,
            text="检测中",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            anchor="w",
        )
        self._status_label.pack(side="left", padx=(8, 0))

        # 整个卡片可点击
        for w in (wrapper, inner, self._status_dot, self._status_label):
            w.bind("<Button-1>", lambda e: self._check_neo4j())
            w.configure(cursor="hand2")

    # ========================================================
    # 面板切换
    # ========================================================
    def show_panel(self, key: str):
        if self.current_panel_key == key:
            return

        if self.current_panel_key is not None:
            self.panels[self.current_panel_key].pack_forget()

        panel = self.panels[key]
        panel.pack(fill="both", expand=True)
        self.current_panel_key = key

        self._update_nav_styles()

        try:
            panel.on_enter()
        except Exception as e:
            print(f"[App] 面板 {key} 的 on_enter 出错: {e}")

    def _update_nav_styles(self):
        """根据当前面板更新导航项样式（只有激活/未激活两种状态）。"""
        for k, w in self.nav_items.items():
            is_active = k == self.current_panel_key

            if is_active:
                w["frame"].configure(fg_color=COLORS["card"])
                w["indicator"].configure(fg_color=COLORS["primary"])
                w["name"].configure(text_color=COLORS["text"])
                w["idx"].configure(text_color=COLORS["primary"])
            else:
                w["frame"].configure(fg_color="transparent")
                w["indicator"].configure(fg_color="transparent")
                w["name"].configure(text_color=COLORS["text_soft"])
                w["idx"].configure(text_color=COLORS["muted"])

    # ========================================================
    # Neo4j 健康检查
    # ========================================================
    def _check_neo4j(self):
        self._status_dot.configure(fg_color=COLORS["warning"])
        self._status_label.configure(
            text="检测中", text_color=COLORS["muted"]
        )
        future = self.bridge.submit(self._async_ping(timeout=5.0))
        future.add_done_callback(self._on_ping_done)

    def _on_ping_done(self, future):
        try:
            result = future.result()
        except Exception as error:
            result = {
                "connected": False,
                "error_message": str(error),
            }

        def _update():
            if result.get("connected"):
                self._status_dot.configure(
                    fg_color=COLORS["success"]
                )
                self._status_label.configure(
                    text="Neo4j 已连接",
                    text_color=COLORS["success"],
                )
                return

            message = result.get(
                "error_message",
                "Neo4j 服务未连接。",
            )

            # 左下角保持简洁，只在未连接时显示第一段诊断信息。
            short_message = message.split("；", 1)[0]
            if len(short_message) > 28:
                short_message = short_message[:28] + "…"

            self._status_dot.configure(
                fg_color=COLORS["error"]
            )
            self._status_label.configure(
                text=f"Neo4j 未连接 · {short_message}",
                text_color=COLORS["error"],
            )

        try:
            self.after(0, _update)
        except Exception:
            pass

    async def _async_ping(self, timeout: float = 5.0) -> dict:
        loop = asyncio.get_running_loop()

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, graphdb.check_connection),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return {
                "connected": False,
                "error_code": "NEO4J_TIMEOUT",
                "error_message": "Neo4j 连接检查超时。",
            }
        except Exception as error:
            return {
                "connected": False,
                "error_code": "NEO4J_HEALTH_CHECK_ERROR",
                "error_message": str(error),
            }

    # ========================================================
    # 关闭
    # ========================================================
    def _on_close(self):
        try:
            graphdb.close()
        except Exception:
            pass
        try:
            self.bridge.stop()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


def main():
    from kg_builder.config import ensure_import_dir
    ensure_import_dir()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()