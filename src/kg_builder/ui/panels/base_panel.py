"""Panel 基类：基于 tk.Text 的聊天气泡 + 查看完整内容弹窗。

特性：
    - 支持框选 + Ctrl+C + 右键菜单
    - 长文本无限制
    - 超过 5000 字 → 气泡内显示前 5000 字 + "查看完整内容"链接
    - 点击链接 → 弹出新窗口用 tk.Text 显示全文
    - 用户靠右、Agent 靠左、系统居中
    - 字号固定 14
"""

import tkinter as tk

import customtkinter as ctk

from kg_builder.ui.theme import (
    BTN_RADIUS,
    COLORS,
    CARD_RADIUS,
    FONT_FAMILY,
    PANEL_PAD,
)


# ============================================================
# 字体常量（想调字号只改这三个数）
# ============================================================
FONT_BODY_SIZE = 11
FONT_HEADER_SIZE = 8
FONT_SYSTEM_SIZE = 9

FONT_BODY = (FONT_FAMILY, FONT_BODY_SIZE)
FONT_HEADER = (FONT_FAMILY, FONT_HEADER_SIZE, "bold")
FONT_SYSTEM = (FONT_FAMILY, FONT_SYSTEM_SIZE)
FONT_THINKING = (FONT_FAMILY, FONT_BODY_SIZE, "italic")
FONT_LINK = (FONT_FAMILY, FONT_BODY_SIZE, "underline")


# ============================================================
# 常量
# ============================================================
TYPE_INTERVAL_MS = 20
THINKING_INTERVAL_MS = 400

MAX_LINES = 20000
TRIM_LINES = 5000

INDENT = 160
CARET = "▌"

# ★ 气泡内显示的字数阈值（超过就截断 + 加"查看完整内容"链接）
BUBBLE_THRESHOLD = 5000


class BasePanel(ctk.CTkFrame):
    title: str = "面板"
    subtitle: str = ""

    def __init__(self, master, bridge, **kwargs):
        super().__init__(master, fg_color=COLORS["bg"], **kwargs)
        self.bridge = bridge
        self._on_enter_done = False

        # 打字机状态
        self._tw_text = ""
        self._tw_shown = 0
        self._tw_running = False
        self._tw_after_id = None
        self._tw_overflow_text = None   # ★ 溢出的完整文本

        # 思考动画
        self._thinking_after_id = None
        self._thinking_frame = 0
        self._thinking_active = False

        # 流式累积
        self._stream_buffer = ""

        # ★ 嵌入的链接按钮（保持 Python 引用，防被 GC 回收）
        self._embedded_links = []

        self._build_ui()

    # ========================================================
    # UI
    # ========================================================
    def _build_ui(self):
        # 标题
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=PANEL_PAD, pady=(16, 10))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", anchor="w")

        ctk.CTkLabel(
            title_box, text=self.title,
            font=(FONT_FAMILY, 15, "bold"),
            text_color=COLORS["text"], anchor="w",
        ).pack(anchor="w")

        if self.subtitle:
            ctk.CTkLabel(
                title_box, text=self.subtitle,
                font=(FONT_FAMILY, 11),
                text_color=COLORS["muted"], anchor="w",
            ).pack(anchor="w", pady=(2, 0))

        # 聊天区容器
        chat_outer = ctk.CTkFrame(
            self, fg_color=COLORS["panel"], corner_radius=CARD_RADIUS
        )
        chat_outer.pack(
            fill="both", expand=True, padx=PANEL_PAD, pady=(0, 12)
        )

        # 滚动条
        self._scrollbar = ctk.CTkScrollbar(
            chat_outer, orientation="vertical",
            command=self._on_scrollbar_command, width=10,
            button_color=COLORS["sb_thumb"],
            button_hover_color=COLORS["sb_thumb_hover"],
            fg_color=COLORS["sb_track"],
        )
        self._scrollbar.pack(
            side="right", fill="y", padx=(0, 8), pady=8
        )

        # 聊天 Text
        self._chat_text = tk.Text(
            chat_outer,
            wrap="word",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["primary"],
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=8,
            pady=2,
            cursor="arrow",
            state="disabled",
            font=FONT_BODY,
            spacing1=0,
            spacing2=2,
            spacing3=0,
            yscrollcommand=self._on_text_yscroll,
        )
        self._chat_text.pack(
            side="left", fill="both", expand=True,
            padx=(14, 0), pady=8,
        )

        self._configure_tags()
        self._setup_context_menu()
        self._bind_mousewheel()

        # 输入区
        input_outer = ctk.CTkFrame(
            self, fg_color=COLORS["panel"], corner_radius=CARD_RADIUS
        )
        input_outer.pack(
            fill="x", padx=PANEL_PAD, pady=(0, PANEL_PAD)
        )

        input_inner = ctk.CTkFrame(input_outer, fg_color="transparent")
        input_inner.pack(fill="x", padx=12, pady=12)

        self.entry = ctk.CTkEntry(
            input_inner, height=48, font=FONT_BODY,
            placeholder_text="输入消息，回车发送",
            placeholder_text_color=COLORS["muted"],
            fg_color=COLORS["card"], border_color=COLORS["border"],
            border_width=1, corner_radius=BTN_RADIUS,
            text_color=COLORS["text"],
        )
        self.entry.pack(
            fill="x", side="left", expand=True, padx=(0, 10)
        )
        self.entry.bind("<Return>", lambda e: self._on_send_clicked())

        self.send_btn = ctk.CTkButton(
            input_inner, text="发送", width=100, height=48,
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            corner_radius=BTN_RADIUS, text_color="#ffffff",
            command=self._on_send_clicked,
        )
        self.send_btn.pack(side="right")

    # ========================================================
    # Tag 配置
    # ========================================================
    def _configure_tags(self):
        t = self._chat_text

        # 用户：靠右
        t.tag_configure(
            "user_header",
            foreground=COLORS["text"],
            font=FONT_HEADER,
            justify="right",
            spacing1=10, spacing3=2,
            lmargin1=INDENT, lmargin2=INDENT,
            rmargin=16,
        )
        t.tag_configure(
            "user_body",
            foreground=COLORS["text"],
            font=FONT_BODY,
            justify="right",
            spacing1=2, spacing3=10,
            lmargin1=INDENT, lmargin2=INDENT,
            rmargin=16,
        )

        # Agent：靠左
        t.tag_configure(
            "agent_header",
            foreground=COLORS["text"],
            font=FONT_HEADER,
            justify="left",
            spacing1=10, spacing3=2,
            lmargin1=16, lmargin2=16,
            rmargin=INDENT,
        )
        t.tag_configure(
            "agent_body",
            foreground=COLORS["text"],
            font=FONT_BODY,
            justify="left",
            spacing1=2, spacing3=10,
            lmargin1=16, lmargin2=16,
            rmargin=INDENT,
        )

        # 系统消息
        for kind, color in [
            ("system_info", COLORS["muted"]),
            ("system_success", COLORS["success"]),
            ("system_warning", COLORS["warning"]),
            ("system_error", COLORS["error"]),
        ]:
            t.tag_configure(
                kind,
                foreground=color,
                font=FONT_SYSTEM,
                justify="center",
                spacing1=4, spacing3=4,
                lmargin1=20, lmargin2=20,
                rmargin=20,
            )

        t.tag_configure(
            "thinking",
            foreground=COLORS["muted"],
            font=FONT_THINKING,
        )

    # ========================================================
    # 滚动条
    # ========================================================
    def _on_scrollbar_command(self, *args):
        try:
            self._chat_text.yview(*args)
        except Exception:
            pass

    def _on_text_yscroll(self, first, last):
        try:
            self._scrollbar.set(first, last)
        except Exception:
            pass

    def _scroll_to_bottom(self):
        try:
            self._chat_text.see("end")
            self._chat_text.update_idletasks()
            first, last = self._chat_text.yview()
            self._scrollbar.set(first, last)
        except Exception:
            pass

    # ========================================================
    # 滚轮
    # ========================================================
    def _bind_mousewheel(self):
        try:
            self._chat_text.bind_all(
                "<MouseWheel>", self._on_wheel, add="+"
            )
        except Exception:
            pass

    def _mouse_in_chat(self) -> bool:
        try:
            if not self.winfo_ismapped():
                return False
        except Exception:
            return False
        try:
            x, y = self._chat_text.winfo_pointerxy()
            cx = self._chat_text.winfo_rootx()
            cy = self._chat_text.winfo_rooty()
            cw = self._chat_text.winfo_width()
            ch = self._chat_text.winfo_height()
            return (cx <= x <= cx + cw) and (cy <= y <= cy + ch)
        except Exception:
            return False

    def _on_wheel(self, event):
        if not self._mouse_in_chat():
            return
        delta = event.delta
        if delta == 0:
            return
        if abs(delta) >= 120:
            step = int(-1 * (delta / 120))
        else:
            step = -1 if delta > 0 else 1
        self._chat_text.yview_scroll(step, "units")
        try:
            first, last = self._chat_text.yview()
            self._scrollbar.set(first, last)
        except Exception:
            pass

    # ========================================================
    # 右键菜单
    # ========================================================
    def _setup_context_menu(self):
        self._context_menu = tk.Menu(self, tearoff=0)
        self._context_menu.add_command(
            label="复制", command=self._copy_selection
        )
        self._context_menu.add_command(
            label="全选", command=self._select_all
        )
        self._context_menu.add_separator()
        self._context_menu.add_command(
            label="清空聊天", command=self.clear_chat
        )

        self._chat_text.bind("<Button-3>", self._show_context_menu)
        self._chat_text.bind(
            "<Control-c>", lambda e: self._copy_selection()
        )
        self._chat_text.bind(
            "<Control-a>", lambda e: self._select_all()
        )

    def _show_context_menu(self, event):
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _copy_selection(self):
        try:
            selected = self._chat_text.get("sel.first", "sel.last")
            if selected:
                self.clipboard_clear()
                self.clipboard_append(selected)
        except tk.TclError:
            pass

    def _select_all(self):
        self._chat_text.tag_add("sel", "1.0", "end-1c")
        return "break"

    # ========================================================
    # ★ 查看完整内容弹窗
    # ========================================================
    def _show_full_text(self, text: str, title: str = "完整内容"):
        """弹窗显示完整文本（用 tk.Text，无长度限制）。"""
        win = tk.Toplevel(self)
        win.title(f"{title}（共 {len(text)} 字）")
        win.geometry("900x700")
        win.configure(bg=COLORS["bg"])
        win.transient(self.winfo_toplevel())

        # 顶部工具栏
        toolbar = tk.Frame(win, bg=COLORS["panel"])
        toolbar.pack(fill="x", padx=10, pady=(10, 0))

        tk.Label(
            toolbar, text=f"共 {len(text)} 字",
            font=(FONT_FAMILY, 11),
            fg=COLORS["muted"], bg=COLORS["panel"],
        ).pack(side="left", padx=8)

        def _copy_all():
            win.clipboard_clear()
            win.clipboard_append(text)
            tk.Label(
                toolbar, text="已复制到剪贴板",
                font=(FONT_FAMILY, 10),
                fg=COLORS["success"], bg=COLORS["panel"],
            ).pack(side="left", padx=8)

        tk.Button(
            toolbar, text="复制全部",
            font=(FONT_FAMILY, 10),
            bg=COLORS["card"], fg=COLORS["text"],
            relief="flat", padx=12, pady=4,
            cursor="hand2", command=_copy_all,
        ).pack(side="right", padx=4)

        # 正文
        text_frame = tk.Frame(win, bg=COLORS["panel"])
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)

        sb = tk.Scrollbar(
            text_frame,
            bg=COLORS["sb_track"],
            troughcolor=COLORS["sb_track"],
            activebackground=COLORS["sb_thumb"],
            highlightthickness=0, borderwidth=0, width=12,
        )
        sb.pack(side="right", fill="y")

        txt = tk.Text(
            text_frame, wrap="word",
            bg=COLORS["panel"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["primary"],
            selectforeground="#ffffff",
            relief="flat", borderwidth=0, highlightthickness=0,
            padx=12, pady=8, font=FONT_BODY,
            yscrollcommand=sb.set,
        )
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)

        txt.insert("1.0", text)
        txt.configure(state="disabled")

        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_force()

    # ========================================================
    # 消息插入
    # ========================================================
    def _insert(self, text, *tags):
        self._chat_text.configure(state="normal")
        self._chat_text.insert("end", text, tags if tags else None)
        self._chat_text.configure(state="disabled")

    def _is_chat_empty(self) -> bool:
        try:
            content = self._chat_text.get("1.0", "end-1c")
            return not content.strip()
        except Exception:
            return True

    def _leading_newline(self) -> str:
        return "" if self._is_chat_empty() else "\n"

    # ★ 核心：可能带溢出的插入
    def _insert_maybe_overflow(self, text, body_tag):
        """插入正文，如果超过阈值就截断 + 加链接。"""
        n = len(text)
        if n <= BUBBLE_THRESHOLD:
            self._insert(text + "\n", body_tag)
            return

        preview = text[:BUBBLE_THRESHOLD]
        self._insert(preview, body_tag)
        self._insert_overflow_link(text)
        self._insert("\n")

    # ★ 在 Text 内嵌入"查看完整内容"链接
    def _insert_overflow_link(self, full_text):
        """嵌入一个链接按钮。"""
        remaining = len(full_text) - BUBBLE_THRESHOLD

        btn = tk.Button(
            self._chat_text,
            text=f"  查看完整内容（还有 {remaining} 字）  ",
            font=FONT_LINK,
            fg=COLORS["primary"],
            bg=COLORS["panel"],
            activeforeground=COLORS["primary"],
            activebackground=COLORS["panel"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=0,
            pady=6,
            cursor="hand2",
            anchor="w",
            command=lambda t=full_text: self._show_full_text(t),
        )

        self._chat_text.configure(state="normal")
        self._chat_text.window_create("end", window=btn, padx=16)
        self._chat_text.configure(state="disabled")

        # 保存引用，避免被 GC
        self._embedded_links.append(btn)

    # ========================================================
    # 对外 API
    # ========================================================
    def add_user_message(self, text: str):
        self._insert(self._leading_newline() + "你\n", "user_header")
        self._insert_maybe_overflow(text, "user_body")
        self._trim_if_needed()
        self.after(30, self._scroll_to_bottom)

    def add_agent_message(self, text: str):
        self._insert(self._leading_newline() + "Agent\n", "agent_header")
        self._insert_maybe_overflow(text, "agent_body")
        self._trim_if_needed()
        self.after(30, self._scroll_to_bottom)

    def add_system_message(self, text: str, kind: str = "info"):
        tag = {
            "info": "system_info",
            "success": "system_success",
            "warning": "system_warning",
            "error": "system_error",
        }.get(kind, "system_info")
        self._insert(self._leading_newline() + text + "\n", tag)
        self._trim_if_needed()
        self.after(30, self._scroll_to_bottom)

    def _trim_if_needed(self):
        try:
            end_line = int(
                self._chat_text.index("end-1c").split(".")[0]
            )
            if end_line > MAX_LINES:
                self._chat_text.configure(state="normal")
                self._chat_text.delete("1.0", f"{TRIM_LINES}.0")
                self._chat_text.configure(state="disabled")
        except Exception:
            pass

    def clear_chat(self):
        self._cancel_typewriter()
        self._stop_thinking_animation()
        self._chat_text.configure(state="normal")
        self._chat_text.delete("1.0", "end")
        self._chat_text.configure(state="disabled")
        self._embedded_links.clear()
        try:
            self._scrollbar.set(0, 1)
        except Exception:
            pass

    # ========================================================
    # 流式 / 思考 / 打字机
    # ========================================================
    def _start_agent_stream(self):
        self._cancel_typewriter()
        self._insert(
            self._leading_newline() + "Agent\n", "agent_header"
        )

        self._chat_text.configure(state="normal")
        self._chat_text.mark_set("thinking_mark", "end-1c")
        self._chat_text.mark_gravity("thinking_mark", "left")
        self._chat_text.configure(state="disabled")

        self._insert("思考中", "agent_body")
        self._insert("\n")
        self._start_thinking_animation()
        self.after(30, self._scroll_to_bottom)

    def _append_agent_chunk(self, chunk: str):
        if not chunk:
            return
        self._stop_thinking_animation()
        self._stream_buffer += chunk

    # ---------- 思考动画 ----------
    def _start_thinking_animation(self):
        self._stop_thinking_animation()
        self._thinking_active = True
        self._thinking_frame = 0
        self._thinking_tick()

    def _thinking_tick(self):
        if not self._thinking_active:
            return
        dots = "." * (self._thinking_frame % 4)
        text = f"思考中{dots}"

        try:
            self._chat_text.configure(state="normal")
            start = self._chat_text.index("thinking_mark")
            line_num = start.split(".")[0]
            end = f"{line_num}.end"
            self._chat_text.delete(start, end)
            self._chat_text.insert(start, text, "agent_body")
            self._chat_text.configure(state="disabled")
        except Exception:
            pass

        self._thinking_frame += 1
        self._thinking_after_id = self.after(
            THINKING_INTERVAL_MS, self._thinking_tick
        )

    def _stop_thinking_animation(self):
        self._thinking_active = False
        if self._thinking_after_id is not None:
            try:
                self.after_cancel(self._thinking_after_id)
            except Exception:
                pass
            self._thinking_after_id = None
        try:
            self._chat_text.configure(state="normal")
            start = self._chat_text.index("thinking_mark")
            line_num = start.split(".")[0]
            end = f"{line_num}.end"
            self._chat_text.delete(start, end)
            self._chat_text.configure(state="disabled")
        except Exception:
            pass

    # ---------- 打字机 ----------
    def _start_typewriter(self, full_text: str):
        self._stop_thinking_animation()

        if not full_text:
            self._end_agent_stream()
            self.set_busy(False)
            return

        # ★ 超长文本：只打字机前 BUBBLE_THRESHOLD 字
        if len(full_text) > BUBBLE_THRESHOLD:
            self._tw_text = full_text[:BUBBLE_THRESHOLD]
            self._tw_overflow_text = full_text
        else:
            self._tw_text = full_text
            self._tw_overflow_text = None

        self._tw_shown = 0
        self._tw_running = True
        self._tw_tick()

    def _tw_tick(self):
        if not self._tw_running:
            return

        total = len(self._tw_text)
        idx = self._tw_shown

        if idx >= total:
            self._tw_running = False
            self._tw_after_id = None
            self._end_agent_stream()
            self.set_busy(False)
            return

        progress = idx / total if total > 0 else 1.0
        if progress < 0.10:
            interval, chars = 20, 3
        elif progress < 0.30:
            interval, chars = 10, 10
        elif progress < 0.70:
            interval, chars = 5, 30
        else:
            interval, chars = 2, 80

        chunk = self._tw_text[idx:idx + chars]
        self._tw_shown += len(chunk)

        try:
            self._chat_text.configure(state="normal")
            self._chat_text.insert("end", chunk, "agent_body")
            self._chat_text.configure(state="disabled")
        except Exception:
            pass

        self._scroll_to_bottom()
        self._tw_after_id = self.after(interval, self._tw_tick)

    def _cancel_typewriter(self):
        self._tw_running = False
        if self._tw_after_id is not None:
            try:
                self.after_cancel(self._tw_after_id)
            except Exception:
                pass
            self._tw_after_id = None

    def _end_agent_stream(self):
        self._cancel_typewriter()
        self._stop_thinking_animation()

        # 确保打字机内容都显示
        if self._tw_running is False and self._tw_shown < len(self._tw_text):
            try:
                rest = self._tw_text[self._tw_shown:]
                self._chat_text.configure(state="normal")
                self._chat_text.insert("end", rest, "agent_body")
                self._chat_text.configure(state="disabled")
            except Exception:
                pass

        # ★ 如果有溢出 → 插入"查看完整内容"链接
        if self._tw_overflow_text:
            self._insert_overflow_link(self._tw_overflow_text)

        self._insert("\n")
        self._tw_text = ""
        self._tw_shown = 0
        self._tw_overflow_text = None
        self._trim_if_needed()
        self.after(30, self._scroll_to_bottom)

    # ========================================================
    # 输入
    # ========================================================
    def _on_send_clicked(self):
        text = self.entry.get().strip()
        if not text:
            return

        if len(text) > 3000:
            from tkinter import messagebox
            ok = messagebox.askyesno(
                "输入过长",
                f"你的输入有 {len(text)} 字，"
                f"可能导致 Agent 生成时间较长。\n\n确定要继续吗？",
            )
            if not ok:
                return

        self.entry.delete(0, "end")
        self.add_user_message(text)
        self._start_agent_stream()
        self.set_busy(True)

        try:
            future = self.bridge.submit(self._invoke_on_send(text))
            future.add_done_callback(self._on_stream_done)
        except Exception as e:
            self._finalize_stream(f"[错误] {e}")

    async def _invoke_on_send(self, text: str) -> str:
        def on_chunk(chunk: str):
            self.after(
                0, lambda c=chunk: self._append_agent_chunk(c)
            )
        return await self.on_send(text, on_chunk=on_chunk)

    def _on_stream_done(self, future):
        try:
            final = future.result()
        except Exception as e:
            final = f"[错误] {e}"
        self.after(0, lambda f=final: self._finalize_stream(f))

    def _finalize_stream(self, final_text: str):
        text = self._stream_buffer or final_text
        if text:
            self._start_typewriter(text)
        else:
            self._end_agent_stream()
            self.set_busy(False)

    def set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        try:
            self.send_btn.configure(state=state)
            self.entry.configure(state=state)
            self.send_btn.configure(
                text="生成中" if busy else "发送"
            )
        except Exception:
            pass

    # ========================================================
    # 生命周期
    # ========================================================
    def on_enter(self):
        if not self._on_enter_done:
            self._on_enter_done = True
            self.on_enter_once()
        else:
            self.on_enter_again()

    def on_enter_once(self):
        pass

    def on_enter_again(self):
        pass

    def on_send(self, text: str, on_chunk=None):
        raise NotImplementedError