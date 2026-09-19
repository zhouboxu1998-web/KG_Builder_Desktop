from core.helper import make_agent_caller
from core.agents.intent_agent import user_intent_agent, APPROVED_USER_GOAL
from core.agents.file_agent import file_suggestion_agent, APPROVED_FILES
from core.agents.schema_struc import schema_refinement_loop, PROPOSED_CONSTRUCTION_PLAN
from core.agents.schema_unstruc import ner_schema_agent, relevant_fact_agent, APPROVED_ENTITIES, APPROVED_FACTS
from core.kg_builder import construct_domain_graph, build_unstructured_graph, run_entity_resolution

class KGOrchestrator:
    def __init__(self):
        # 定义流水线阶段：INTENT -> FILE -> SCHEMA_STRUC -> NER -> FACT -> DONE
        self.current_stage = "INTENT"
        self.caller = None
        self.session_state = {}

    async def initialize(self):
        """初始化首个阶段的 Agent"""
        print("[Orchestrator] 初始化系统，进入意图收集阶段...")
        self.caller = await make_agent_caller(user_intent_agent)

    async def process_user_input(self, user_input: str, yield_callback=None):
        """
        处理前端用户的输入，并将 Agent 的回复流式推送给界面。
        """
        if not self.caller:
            await self.initialize()

        # Agent 处理当前用户的消息
        async for event in self.caller.runner.run_async(
                user_id=self.caller.user_id,
                session_id=self.caller.session_id,
                new_message=user_input
        ):
            # 将模型的思考/回复，传递给前端 UI 回调函数
            if event.is_final_response():
                if getattr(event, "content", None) and event.content.parts:
                    response_text = event.content.parts[0].text
                    if yield_callback:
                        await yield_callback(response_text)

        # 每次对话完成后，检查是否达到了阶段性目标，是否需要切换接班人
        await self.check_stage_transition(yield_callback)

    async def check_stage_transition(self, yield_callback):
        """状态机：自动感知记忆(State)，动态切换背后的 Agent"""
        session = await self.caller.get_session()
        state = session.state
        self.session_state = state  # 更新全局状态备份

        # 阶段 1 -> 阶段 2
        if self.current_stage == "INTENT" and APPROVED_USER_GOAL in state:
            msg = "\n[系统播报] 🎯 意图已确认！切换至文件筛选专员..."
            self.current_stage = "FILE"
            self.caller = await make_agent_caller(file_suggestion_agent, initial_state=state)
            if yield_callback: await yield_callback(msg)

        # 阶段 2 -> 阶段 3
        elif self.current_stage == "FILE" and APPROVED_FILES in state:
            msg = "\n[系统播报] 📁 文件已确认！启动架构师与质检员联合评估 Loop..."
            self.current_stage = "SCHEMA_STRUC"
            self.caller = await make_agent_caller(schema_refinement_loop, initial_state=state)
            if yield_callback: await yield_callback(msg)

        # 阶段 3 -> 阶段 4
        elif self.current_stage == "SCHEMA_STRUC" and PROPOSED_CONSTRUCTION_PLAN in state:
            # 判断是否有 Markdown 文本需要 NER。如果包含 md 文件则进入，否则可以跳过
            md_files = [f for f in state.get(APPROVED_FILES, []) if f.endswith(".md")]
            if md_files:
                msg = "\n[系统播报] 🏗️ 结构化构建图纸已完成！正在唤醒 NLP 文本实体识别专家..."
                self.current_stage = "NER"
                self.caller = await make_agent_caller(ner_schema_agent, initial_state=state)
                if yield_callback: await yield_callback(msg)
            else:
                self.current_stage = "DONE"
                if yield_callback: await yield_callback(
                    "\n[系统播报] 纯结构化数据，所有 Schema 准备就绪，可以开始构建 KG 了！")

        # 阶段 4 -> 阶段 5
        elif self.current_stage == "NER" and APPROVED_ENTITIES in state:
            msg = "\n[系统播报] 🔍 文本实体类型已确认！切换至关系(事实)提取专家..."
            self.current_stage = "FACT"
            self.caller = await make_agent_caller(relevant_fact_agent, initial_state=state)
            if yield_callback: await yield_callback(msg)

        # 阶段 5 -> 结束
        elif self.current_stage == "FACT" and APPROVED_FACTS in state:
            msg = "\n[系统播报] 🎉 所有流水线节点已通过！KG Schema 已完整就绪，准备入库构建！"
            self.current_stage = "DONE"
            if yield_callback: await yield_callback(msg)

            # --- 开始调用施工队 ---
            try:
                # 1. 结构化构建
                if yield_callback: await yield_callback("\n[图谱施工队] 正在导入结构化数据 (CSV)...")
                construct_domain_graph(state["proposed_construction_plan"])

                # 2. 非结构化构建
                if yield_callback: await yield_callback(
                    "\n[图谱施工队] 正在处理非结构化数据 (Markdown + GraphRAG)，这可能需要一些时间...")
                await build_unstructured_graph(state["approved_files"], state["approved_entity_types"],
                                               state["approved_fact_types"])

                # 3. 实体融合消歧
                if yield_callback: await yield_callback(
                    "\n[图谱施工队] 正在执行实体消歧融合算法 (Entity Resolution)...")
                run_entity_resolution()

                self.current_stage = "DONE"
                if yield_callback: await yield_callback(
                    "\n✅ [大功告成] 知识图谱已全部构建并入库 Neo4j！您可以打开 Neo4j Browser 查看了！")

            except Exception as e:
                self.current_stage = "ERROR"
                if yield_callback: await yield_callback(f"\n❌ [施工失败] 构建图谱时发生错误: {str(e)}")