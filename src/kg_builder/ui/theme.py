"""UI 颜色与字体常量。"""
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg": "#1a1a2e",
    "panel": "#16213e",
    "accent": "#0f3460",
    "highlight": "#e94560",
    "text": "#eaeaea",
    "muted": "#8a8a9a",
    "success": "#4ade80",
    "warning": "#fbbf24",
    "error": "#f87171",
    "user_bubble": "#2a4a7a",
    "agent_bubble": "#2a2a3e",
}

FONT_FAMILY = "Microsoft YaHei UI"  # 中文友好
FONT_TITLE = (FONT_FAMILY, 20, "bold")
FONT_HEADER = (FONT_FAMILY, 15, "bold")
FONT_BODY = (FONT_FAMILY, 13)
FONT_SMALL = (FONT_FAMILY, 11)
FONT_MONO = ("Consolas", 12)