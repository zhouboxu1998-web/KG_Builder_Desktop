# 🧠 ADK 知识图谱构建器

基于 **Google ADK (Agent Development Kit)** 的多 Agent 知识图谱构建系统，
通过自然语言对话完成：**意图理解 → 文件选择 → Schema 设计 → 图谱构建 → 查询验证**。

## ✨ 特性

- 🤖 **多 Agent 协作**：用户意图 Agent、文件推荐 Agent、Schema 提议 Agent、审查 Agent、NER Agent、事实抽取 Agent
- 💬 **对话式交互**：通过自然语言完成所有配置，无需手写 Cypher
- 🔄 **人在回路（Human-in-the-Loop）**：关键步骤需要用户确认
- 🗂️ **结构化 + 非结构化**：支持 CSV 结构化导入，也支持从 Markdown 评论中抽取实体关系
- 🖥️ **桌面版**：基于 CustomTkinter，跨平台

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
```

必填项：
- `DEEPSEEK_API_KEY` — DeepSeek API Key
- `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` — Neo4j 连接信息
- `NEO4J_IMPORT_DIR` — CSV 文件所在目录（会被挂载到 Neo4j 的 import 目录）

### 3. 准备数据

把你的 CSV 文件放到 `data/import/` 下：

```
data/import/
├── products.csv
├── assemblies.csv
├── components.csv
├── parts.csv
├── suppliers.csv
└── part_supplier_mapping.csv
```

### 4. 启动桌面版

```bash
python run.py
```

## 📁 项目结构

```
src/kg_builder/
├── config.py              # 环境变量配置
├── state.py               # 状态键常量
├── core/                  # 核心：LLM / Neo4j / Runner 封装
├── tools/                 # 工具：文件、目标、Schema、实体、事实、构建
├── agents/                # 各类 Agent 定义
└── ui/                    # 桌面 UI
    ├── app.py             # 主窗口
    ├── async_bridge.py    # asyncio ↔ tkinter 桥
    └── panels/            # 各阶段面板
```

## 🎯 使用流程

1. **定义目标** — 告诉系统你想构建什么图谱（如"供应链分析"）
2. **选择文件** — Agent 列出文件并推荐相关文件，你确认
3. **图谱结构** — Agent 提议节点/关系构建规则，你审查
4. **构建** — 输入 `build` 开始导入 Neo4j
5. **查询** — 运行 Cypher 验证结果

## 🔧 架构说明

### 状态管理

Agent 之间通过 **Session State** 传递数据，关键键在 `state.py` 中定义：

| 键 | 说明 |
|---|---|
| `approved_user_goal` | 已批准的用户目标 |
| `approved_files` | 已批准的文件列表 |
| `proposed_construction_plan` | 提议的构建计划 |
| `approved_entity_types` | 已批准的实体类型 |
| `approved_fact_types` | 已批准的事实类型 |

### Agent 与工具

每个 Agent 的"能力"由 `tools` 参数决定。工具函数必须：
- 接收 `ToolContext` 参数（可选）
- 返回 `{"status": "success"|"error", ...}` 字典

### 异步桥接

ADK 使用 asyncio，Tkinter 使用事件循环。`AsyncBridge` 在后台线程运行
asyncio 事件循环，主线程通过 `submit(coro)` 提交任务并获取结果。

## 🧪 开发

```bash
# 直接运行某个 Agent（脚本化）
python -c "
import asyncio
from kg_builder.agents.user_intent import build_user_intent_agent
from kg_builder.core.agent_runner import make_agent_caller

async def main():
    agent = build_user_intent_agent()
    caller = await make_agent_caller(agent)
    print(await caller.chat('我想要一个供应链图谱'))

asyncio.run(main())
"
```

## ⚠️ 注意事项

- **CSV 路径**：Neo4j 的 `LOAD CSV` 只能访问 Neo4j 服务器配置的 import 目录。
  请确保 `.env` 中的 `NEO4J_IMPORT_DIR` 指向 Neo4j 服务器能访问到的目录。
- **首次运行**：确保 Neo4j 已启动，且启用了 APOC 插件（用于实体解析）。
- **非结构化图谱**：需要配置 `DASHSCOPE_API_KEY` 用于 Embedding。

## 📄 License

MIT