import flet as ft
import asyncio
import json
from core.orchestrator import KGOrchestrator


# ==========================================
# 自定义 UI 组件：聊天消息气泡
# ==========================================
class ChatMessage(ft.Row):
    def __init__(self, text: str, is_user: bool = False, is_system: bool = False):
        super().__init__()
        self.is_user = is_user
        self.alignment = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START

        # 不同的角色对应不同的头像和气泡颜色
        if is_user:
            avatar_color = ft.colors.BLUE_GREY
            avatar_text = "我"
            bg_color = ft.colors.BLUE_700
            text_color = ft.colors.WHITE
        elif is_system:
            avatar_color = ft.colors.ORANGE
            avatar_text = "SYS"
            bg_color = ft.colors.TRANSPARENT
            text_color = ft.colors.ORANGE_300
        else:
            avatar_color = ft.colors.GREEN_700
            avatar_text = "AI"
            bg_color = ft.colors.SURFACE_VARIANT
            text_color = ft.colors.ON_SURFACE_VARIANT

        self.controls = [
            ft.CircleAvatar(
                content=ft.Text(avatar_text, size=12),
                color=ft.colors.WHITE,
                bgcolor=avatar_color,
            ) if not is_user else ft.Container(),

            ft.Container(
                content=ft.Markdown(
                    text,
                    selectable=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                ) if not is_system else ft.Text(text, color=text_color, italic=True),
                bgcolor=bg_color,
                border_radius=10,
                padding=15,
                max_width=600,
            ),

            ft.CircleAvatar(
                content=ft.Text(avatar_text, size=12),
                color=ft.colors.WHITE,
                bgcolor=avatar_color,
            ) if is_user else ft.Container(),
        ]


# ==========================================
# 主程序
# ==========================================
async def main(page: ft.Page):
    page.title = "Google ADK - 自动化知识图谱构建流水线"
    page.theme_mode = ft.ThemeMode.DARK  # 护眼暗色模式
    page.padding = 0

    # 1. 初始化后端大脑 (Orchestrator)
    orchestrator = KGOrchestrator()
    await orchestrator.initialize()

    # 2. UI 控件定义
    chat_list = ft.ListView(expand=True, spacing=15, padding=20, auto_scroll=True)
    user_input = ft.TextField(
        hint_text="输入您的目标或指令 (例如：我想构建一个供应链图谱)...",
        expand=True,
        border_radius=20,
        shift_enter=True,
        on_submit=lambda e: asyncio.create_task(send_message_click(e))
    )

    # 左侧状态监控面板的文本框
    stage_text = ft.Text("当前阶段: 意图收集 (INTENT)", size=16, weight="bold", color=ft.colors.BLUE_400)
    state_display = ft.Text("{}", font_family="Consolas", size=12, color=ft.colors.GREEN_300)

    # 3. 核心交互逻辑
    async def send_message_click(e):
        if not user_input.value.strip(): return

        msg = user_input.value
        user_input.value = ""  # 清空输入框

        # 将用户消息上屏
        chat_list.controls.append(ChatMessage(msg, is_user=True))
        user_input.disabled = True  # 防止连续疯狂点击
        page.update()

        # 定义回调函数：当 Agent 有回复时，动态推送到界面
        async def bot_reply(text: str):
            is_system = text.startswith("[系统播报]")
            chat_list.controls.append(ChatMessage(text, is_user=False, is_system=is_system))
            page.update()

        # 🚀 呼叫后端处理
        try:
            await orchestrator.process_user_input(msg, yield_callback=bot_reply)
        except Exception as ex:
            await bot_reply(f"**[Error]** 系统出现异常: {str(ex)}")
        finally:
            update_sidebar()  # 每次对话完，刷新左侧监控面板
            user_input.disabled = False
            user_input.focus()
            page.update()

    def update_sidebar():
        """刷新左侧实时状态"""
        stage_text.value = f"当前阶段: {orchestrator.current_stage}"
        # 格式化打印当前 Agent 的记忆(State)
        formatted_state = json.dumps(orchestrator.session_state, indent=2, ensure_ascii=False)
        state_display.value = formatted_state
        page.update()

    send_btn = ft.IconButton(
        icon=ft.icons.SEND_ROUNDED,
        icon_color=ft.colors.BLUE_400,
        tooltip="发送",
        on_click=lambda e: asyncio.create_task(send_message_click(e))
    )

    # 4. 页面布局搭建
    # 左侧面板：状态监控
    sidebar = ft.Container(
        width=350,
        bgcolor=ft.colors.SURFACE,
        border=ft.border.only(right=ft.border.BorderSide(1, ft.colors.OUTLINE)),
        padding=20,
        content=ft.Column(
            controls=[
                ft.Row([ft.Icon(ft.icons.MONITOR_HEART, color=ft.colors.BLUE_400),
                        ft.Text("Agent 状态监控舱", size=18, weight="bold")]),
                ft.Divider(),
                stage_text,
                ft.Divider(),
                ft.Text("实时图谱记忆 (State):", size=14, color=ft.colors.GREY_400),
                ft.Container(
                    content=ft.Column([state_display], scroll=ft.ScrollMode.AUTO),
                    expand=True,
                    bgcolor=ft.colors.BLACK87,
                    padding=10,
                    border_radius=10,
                )
            ]
        )
    )

    # 右侧面板：聊天主界面
    chat_panel = ft.Container(
        expand=True,
        padding=20,
        content=ft.Column(
            controls=[
                chat_list,
                ft.Row(
                    controls=[user_input, send_btn],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                )
            ]
        )
    )

    # 将左右两块拼入主页面
    page.add(
        ft.Row(
            controls=[sidebar, chat_panel],
            expand=True,
            spacing=0
        )
    )

    # 系统欢迎语
    chat_list.controls.append(
        ChatMessage("你好！我是知识图谱构建流水线架构师。请问您今天想构建什么类型的图谱？（例如：物流网络、社交网络等）",
                    is_user=False))
    page.update()


# ==========================================
# 启动框架 (注意使用异步模式)
# ==========================================
if __name__ == "__main__":
    ft.app(target=main)