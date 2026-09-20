"""Panel 基类：Canvas + Frame 气泡聊天区 + 打字机 + 真流式 + 可见滚动条。

功能：
    - 真气泡（圆角、背景色、左右对齐）
    - 打字机效果（模型不流式时兜底）
    - 真流式支持（模型流式时逐字显示）
    - 可见滚动条（CTkScrollbar）
    - on_enter_once / on_enter_again 生命周期
    - 气泡数量上限（防内存泄漏）

⚠️ 注意：本文件绝不能 import 任何 *panel.py（会循环导入）。
   它只被其他 panel 继承，不依赖它们。
"""

import tkinter as tk

import customtkinter as ctk

from kg_builder.ui.theme import (
    COLORS,
    FONT_BODY,
    FONT_FAMILY,
    FONT_HEADER,
    FONT_SMALL,
)


# ============================================================
# 常量
# ============================================================

BUBBLE_MAX_WIDTH_RATIO = 0.72      # 气泡最大宽度 = Canvas 宽度 × 此比例
MAX_BUBBLES = 200                  # 气泡数量上限

TYPE_INTERVAL_MS = 20              # 打字机 tick 间隔（毫秒）
TYPE_CHARS_PER_TICK = 2            # 每 tick 吐出几个字符

STREAM_FLUSH_MS = 30               # 真流式节流间隔（毫秒）

SCROLLBAR_TRACK = "#1a2332"        # 滚动条轨道
SCROLLBAR_THUMB = "#4a5568"        # 滚动条滑块
SCROLLBAR_THUMB_HOVER = "#718096"  # 滚动条悬停

CARET = "▌"                        # 打字机光标


# ============================================================
# BasePanel
# ============================================================

class BasePanel(ctk.CTkFrame):
    """所有阶段面板的基类。"""

    title: str = "面板"
    subtitle: str = ""

    def __init__(self, master, bridge, **kwargs):
        super().__init__(master, fg_color=COLORS["bg"], **kwargs)
        self.bridge = bridge
        self._on_enter_done = False

        # -------- 流式 / 打字机状态 --------
        self._streaming_label = None       # 当前正在更新的 Label
        self._stream_buffer = ""           # 真流式累积的文本
        self._flush_scheduled = False      # 流式节流标志

        # -------- 打字机状态 --------
        self._typewriter_text = ""         # 待吐的完整文本
        self._typewriter_index = 0         # 已吐字符数
        self._typewriter_running = False
        self._typewriter_after_id = None

        self._build_ui()

    # ========================================================
    # UI 构建
    # ========================================================
    def _build_ui(self):
        # ---------- 顶部标题 ----------
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))

        ctk.CTkLabel(
            header,
            text=self.title,
            font=FONT_HEADER,
            text_color=COLORS["text"],
        ).pack(side="left")

        if self.subtitle:
            ctk.CTkLabel(
                header,
                text=self.subtitle,
                font=FONT_SMALL,
                text_color=COLORS["muted"],
            ).pack(side="left", padx=(12, 0))

        # ---------- 聊天区容器 ----------
        chat_outer = ctk.CTkFrame(
            self, fg_color=COLORS["panel"], corner_radius=10
        )
        chat_outer.pack(fill="both", expand=True, padx=20, pady=10)

        # ---------- 滚动条（先 pack，避免被 Canvas 挤出）----------
        self._scrollbar = ctk.CTkScrollbar(
            chat_outer,
            orientation="vertical",
            command=self._on_scrollbar_command,
            width=14,
            button_color=SCROLLBAR_THUMB,
            button_hover_color=SCROLLBAR_THUMB_HOVER,
            fg_color=SCROLLBAR_TRACK,
        )
        self._scrollbar.pack(side="right", fill="y", padx=(0, 6), pady=8)

        # ---------- Canvas ----------
        self._canvas = tk.Canvas(
            chat_outer,
            bg=COLORS["panel"],
            highlightthickness=0,
            borderwidth=0,
        )
        self._canvas.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(8, 0),
            pady=8,
        )
        self._canvas.configure(yscrollcommand=self._on_canvas_yscroll)

        # ---------- Inner frame ----------
        self._inner = tk.Frame(self._canvas, bg=COLORS["panel"])
        self._inner_id = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw"
        )

        # ---------- 尺寸同步 ----------
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._inner.bind("<Configure>", self._on_inner_configure)

        # ---------- 滚轮 ----------
        self._bind_mousewheel()

        # ---------- 输入区 ----------
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", padx=20, pady=(0, 15))

        self.entry = ctk.CTkTextbox(
            input_frame, height=70, font=FONT_BODY, wrap="word"
        )
        self.entry.pack(fill="x", side="left", expand=True, padx=(0, 10))
        self.entry.bind("<Control-Return>", lambda e: self._on_send_clicked())

        self.send_btn = ctk.CTkButton(
            input_frame,
            text="发送  ▶",
            width=100,
            font=FONT_BODY,
            fg_color=COLORS["highlight"],
            hover_color="#c73a52",
            command=self._on_send_clicked,
        )
        self.send_btn.pack(side="right")

    # ========================================================
    # 滚动条 <-> Canvas 双向同步
    # ========================================================
    def _on_scrollbar_command(self, *args):
        """用户拖动滚动条 → 滚动 Canvas。"""
        try:
            self._canvas.yview(*args)
        except Exception:
            pass

    def _on_canvas_yscroll(self, first, last):
        """Canvas 内容滚动 → 更新滚动条位置。"""
        try:
            self._scrollbar.set(first, last)
        except Exception:
            pass

    # ========================================================
    # Canvas 尺寸同步
    # ========================================================
    def _on_canvas_configure(self, event):
        """Canvas 宽度变化 → inner frame 同步宽度。"""
        self._canvas.itemconfig(self._inner_id, width=event.width)

    def _on_inner_configure(self, event):
        """inner frame 高度变化 → 更新 scrollregion。"""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        try:
            first, last = self._canvas.yview()
            self._scrollbar.set(first, last)
        except Exception:
            pass

    def _refresh_scrollregion(self):
        """强制刷新 scrollregion + 滚动条显示。"""
        self._inner.update_idletasks()
        bbox = self._canvas.bbox("all")
        if bbox:
            self._canvas.configure(scrollregion=bbox)
        try:
            first, last = self._canvas.yview()
            self._scrollbar.set(first, last)
        except Exception:
            pass

    # ========================================================
    # 鼠标滚轮
    # ========================================================
    def _bind_mousewheel(self):
        def _on_wheel(event):
            delta = event.delta
            if delta == 0:
                return
            if abs(delta) >= 120:
                step = int(-1 * (delta / 120))
            else:
                step = -1 if delta > 0 else 1
            self._canvas.yview_scroll(step, "units")
            try:
                first, last = self._canvas.yview()
                self._scrollbar.set(first, last)
            except Exception:
                pass

        self._canvas.bind_all("<MouseWheel>", _on_wheel)
        self._canvas.bind_all(
            "<Button-4>", lambda e: self._canvas.yview_scroll(-1, "units")
        )
        self._canvas.bind_all(
            "<Button-5>", lambda e: self._canvas.yview_scroll(1, "units")
        )

    # ========================================================
    # 气泡尺寸 / 裁剪
    # ========================================================
    def _get_bubble_max_width(self) -> int:
        w = self._canvas.winfo_width()
        if w <= 1:
            w = 800
        return max(200, int(w * BUBBLE_MAX_WIDTH_RATIO))

    def _trim_bubbles(self):
        """超过上限时删除最早的 widget。"""
        children = self._inner.winfo_children()
        if len(children) > MAX_BUBBLES:
            for old in children[: len(children) - MAX_BUBBLES]:
                old.destroy()

    # ========================================================
    # 普通气泡
    # ========================================================
    def _add_bubble(
        self,
        who: str,
        text: str,
        bubble_color: str,
        header_color: str,
        anchor: str,
        body_color: str = None,
    ):
        if body_color is None:
            body_color = COLORS["text"]

        wrapper = tk.Frame(self._inner, bg=COLORS["panel"])
        wrapper.pack(fill="x", padx=12, pady=6)

        bubble = ctk.CTkFrame(
            wrapper, fg_color=bubble_color, corner_radius=14
        )
        bubble.pack(anchor=anchor)

        ctk.CTkLabel(
            bubble,
            text=who,
            font=(FONT_FAMILY, 10, "bold"),
            text_color=header_color,
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(8, 0))

        ctk.CTkLabel(
            bubble,
            text=text,
            font=(FONT_FAMILY, 13),
            text_color=body_color,
            justify="left",
            anchor="w",
            wraplength=self._get_bubble_max_width(),
        ).pack(anchor="w", padx=14, pady=(2, 10))

        self._refresh_scrollregion()
        self._trim_bubbles()
        self.after(30, self._scroll_to_bottom)

    # ========================================================
    # 流式气泡
    # ========================================================
    def _start_agent_stream(self):
        """创建一个空的 Agent 气泡（准备流式 / 打字机）。"""
        self._cancel_typewriter()

        wrapper = tk.Frame(self._inner, bg=COLORS["panel"])
        wrapper.pack(fill="x", padx=12, pady=6)

        bubble = ctk.CTkFrame(
            wrapper, fg_color=COLORS["agent_bubble"], corner_radius=14
        )
        bubble.pack(anchor="w")

        ctk.CTkLabel(
            bubble,
            text="🤖 Agent",
            font=(FONT_FAMILY, 10, "bold"),
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(8, 0))

        label = ctk.CTkLabel(
            bubble,
            text=f"思考中…{CARET}",
            font=(FONT_FAMILY, 13),
            text_color=COLORS["text"],
            justify="left",
            anchor="w",
            wraplength=self._get_bubble_max_width(),
        )
        label.pack(anchor="w", padx=14, pady=(2, 10))

        self._streaming_label = label
        self._stream_buffer = ""
        self._flush_scheduled = False
        self._refresh_scrollregion()
        self.after(30, self._scroll_to_bottom)

    # ---------- 真流式：追加 chunk ----------
    def _append_agent_chunk(self, chunk: str):
        """真流式：向气泡追加 chunk（30ms 节流）。"""
        if not chunk:
            return
        self._stream_buffer += chunk

        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        self.after(STREAM_FLUSH_MS, self._flush_stream)

    def _flush_stream(self):
        self._flush_scheduled = False
        if self._streaming_label is None:
            return
        try:
            self._streaming_label.configure(
                text=self._stream_buffer + CARET
            )
        except Exception:
            return
        self._refresh_scrollregion()
        self._scroll_to_bottom()

    # ---------- 打字机：逐字吐出 ----------
    def _start_typewriter(self, full_text: str):
        """启动打字机，在 streaming_label 上逐字显示 full_text。"""
        if self._streaming_label is None or not full_text:
            self._end_agent_stream()
            self.set_busy(False)
            return

        self._typewriter_text = full_text
        self._typewriter_index = 0
        self._typewriter_running = True
        self._typewriter_tick()

    def _typewriter_tick(self):
        if not self._typewriter_running or self._streaming_label is None:
            return

        full = self._typewriter_text
        idx = self._typewriter_index

        # 完成
        if idx >= len(full):
            self._typewriter_running = False
            self._typewriter_after_id = None
            self._end_agent_stream()
            self.set_busy(False)
            return

        # 前进
        idx = min(idx + TYPE_CHARS_PER_TICK, len(full))
        self._typewriter_index = idx
        display = full[:idx] + CARET

        try:
            self._streaming_label.configure(text=display)
        except Exception:
            return

        self._refresh_scrollregion()
        self._scroll_to_bottom()

        self._typewriter_after_id = self.after(
            TYPE_INTERVAL_MS, self._typewriter_tick
        )

    def _cancel_typewriter(self):
        self._typewriter_running = False
        if self._typewriter_after_id is not None:
            try:
                self.after_cancel(self._typewriter_after_id)
            except Exception:
                pass
            self._typewriter_after_id = None

    # ---------- 结束流式 / 打字机 ----------
    def _end_agent_stream(self):
        """去掉光标，清理状态。"""
        self._cancel_typewriter()

        if self._streaming_label is None:
            return

        try:
            final = (
                self._stream_buffer
                or self._typewriter_text
                or "（无响应）"
            )
            self._streaming_label.configure(text=final)
        except Exception:
            pass

        self._streaming_label = None
        self._stream_buffer = ""
        self._typewriter_text = ""
        self._typewriter_index = 0
        self._flush_scheduled = False

        self._refresh_scrollregion()
        self._trim_bubbles()
        self.after(30, self._scroll_to_bottom)

    # ========================================================
    # 对外消息 API
    # ========================================================
    def add_user_message(self, text: str):
        self._add_bubble(
            who="👤 你",
            text=text,
            bubble_color=COLORS["user_bubble"],
            header_color="#a8c8f8",
            anchor="e",
        )

    def add_agent_message(self, text: str):
        """非流式：直接添加完整的 Agent 气泡。"""
        self._add_bubble(
            who="🤖 Agent",
            text=text,
            bubble_color=COLORS["agent_bubble"],
            header_color=COLORS["muted"],
            anchor="w",
        )

    def add_system_message(self, text: str, kind: str = "info"):
        color = {
            "info": COLORS["muted"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"],
        }.get(kind, COLORS["muted"])

        lbl = ctk.CTkLabel(
            self._inner,
            text=text,
            font=(FONT_FAMILY, 11, "italic"),
            text_color=color,
            justify="center",
            anchor="center",
            wraplength=self._get_bubble_max_width() + 100,
        )
        lbl.pack(fill="x", padx=20, pady=4)

        self._refresh_scrollregion()
        self._trim_bubbles()
        self.after(30, self._scroll_to_bottom)

    def clear_chat(self):
        self._cancel_typewriter()
        for w in self._inner.winfo_children():
            w.destroy()
        self._canvas.configure(scrollregion=(0, 0, 0, 0))
        try:
            self._scrollbar.set(0, 1)
        except Exception:
            pass

    def _scroll_to_bottom(self):
        try:
            self._canvas.update_idletasks()
            self._canvas.yview_moveto(1.0)
            first, last = self._canvas.yview()
            self._scrollbar.set(first, last)
        except Exception:
            pass

    # ========================================================
    # 输入处理
    # ========================================================
    def _on_send_clicked(self):
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        self.entry.delete("1.0", "end")

        self.add_user_message(text)
        self._start_agent_stream()
        self.set_busy(True)

        try:
            future = self.bridge.submit(self._invoke_on_send(text))
            future.add_done_callback(self._on_stream_done)
        except Exception as e:
            self._finalize_stream(f"[错误] {e}")

    async def _invoke_on_send(self, text: str) -> str:
        """在 bridge 线程里跑 on_send，chunks 通过 after 回主线程。"""
        def on_chunk(chunk: str):
            self.after(0, lambda c=chunk: self._append_agent_chunk(c))

        return await self.on_send(text, on_chunk=on_chunk)

    def _on_stream_done(self, future):
        """异步任务完成 → 切主线程处理。"""
        try:
            final = future.result()
        except Exception as e:
            final = f"[错误] {e}"
        self.after(0, lambda f=final: self._finalize_stream(f))

    def _finalize_stream(self, final_text: str):
        """决定：直接结束 或 启动打字机。"""
        if self._streaming_label is None:
            self.set_busy(False)
            return

        # 真流式走过 → buffer 非空 → 直接结束
        if self._stream_buffer:
            print(f"[UI] 真流式：buffer 长度={len(self._stream_buffer)}")
            self._end_agent_stream()
            self.set_busy(False)
        else:
            # 未走真流式 → 打字机兜底
            print(
                f"[UI] 打字机：final_text 长度="
                f"{len(final_text) if final_text else 0}"
            )
            if final_text:
                self._start_typewriter(final_text)
            else:
                self._end_agent_stream()
                self.set_busy(False)

    def set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        try:
            self.send_btn.configure(state=state)
            self.entry.configure(state=state)
            self.send_btn.configure(
                text="思考中…" if busy else "发送  ▶"
            )
        except Exception:
            pass

    # ========================================================
    # 生命周期
    # ========================================================
    def on_enter(self):
        """面板被激活时调用。首次 on_enter_once，之后 on_enter_again。"""
        if not self._on_enter_done:
            self._on_enter_done = True
            self.on_enter_once()
        else:
            self.on_enter_again()

    def on_enter_once(self):
        """面板首次被激活时调用（子类覆写）。"""
        pass

    def on_enter_again(self):
        """面板非首次被激活时调用（子类覆写，默认空）。"""
        pass

    def on_send(self, text: str, on_chunk=None):
        """子类必须实现。返回 coroutine。"""
        raise NotImplementedError