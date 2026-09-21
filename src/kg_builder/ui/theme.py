"""UI 主题：配色、字体、尺寸。

风格：Notion / Linear Light 风格的浅色主题
    - 干净的白色背景
    - 微妙的分层
    - 靛蓝主色
    - 无 emoji
"""

import customtkinter as ctk

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


# ============================================================
# 配色（浅色）
# ============================================================
COLORS = {
    # ---------- 层次背景 ----------
    "bg":             "#f7f7fa",   # 主背景（极浅灰）
    "panel":          "#ffffff",   # 面板（纯白）
    "card":           "#f1f1f5",   # 卡片（浅灰）
    "card_hover":     "#e8e8ee",   # 卡片悬停
    "border":         "#e0e0e8",   # 边框
    "divider":        "#ececf2",   # 分隔线

    # ---------- 文本 ----------
    "text":           "#1a1a1f",   # 主文本（近黑）
    "text_soft":      "#4a4a55",   # 次要文本
    "muted":          "#757585",   # 弱文本
    "dim":            "#a0a0aa",   # 极弱文本

    # ---------- 强调色 ----------
    "primary":        "#4f46e5",   # 靛蓝
    "primary_hover":  "#6366f1",
    "primary_soft":   "#eef2ff",

    "accent":         "#0891b2",   # 青色
    "accent_hover":   "#06b6d4",

    # ---------- 语义色 ----------
    "success":        "#059669",
    "warning":        "#d97706",
    "error":          "#dc2626",
    "info":           "#2563eb",

    # ---------- 气泡 ----------
    "user_bubble":    "#4f46e5",   # 靛蓝（深色气泡）
    "user_text":      "#ffffff",   # 白色文字
    "agent_bubble":   "#f1f1f5",   # 浅灰气泡
    "agent_text":     "#1a1a1f",   # 深色文字

    # ---------- 滚动条 ----------
    "sb_track":       "#f0f0f5",   # 浅灰轨道
    "sb_thumb":       "#c8c8d4",   # 中灰滑块
    "sb_thumb_hover": "#a0a0b0",

    # ---------- 兼容旧键 ----------
    "highlight":      "#4f46e5",
}


# ============================================================
# 字体
# ============================================================
FONT_FAMILY = "Microsoft YaHei UI"
FONT_MONO_FAMILY = "Consolas"

FONT_TITLE   = (FONT_FAMILY, 20, "bold")
FONT_HEADER  = (FONT_FAMILY, 15, "bold")
FONT_SUBHEAD = (FONT_FAMILY, 13, "bold")
FONT_BODY    = (FONT_FAMILY, 13)
FONT_SMALL   = (FONT_FAMILY, 11)
FONT_TINY    = (FONT_FAMILY, 10)
FONT_MONO    = (FONT_MONO_FAMILY, 12)
FONT_MONO_SM = (FONT_MONO_FAMILY, 10)


# ============================================================
# 尺寸
# ============================================================
SIDEBAR_WIDTH = 240
PANEL_PAD = 24
CARD_RADIUS = 14
BUBBLE_RADIUS = 16
BTN_RADIUS = 10