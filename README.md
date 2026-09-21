# KG Builder

基于 Google ADK 的多 Agent 知识图谱构建系统。
通过对话式工作流，将结构化 CSV 数据和非结构化 Markdown 文本整合为统一的知识图谱。

## 项目简介

本系统将知识图谱构建拆解为 8 个可交互阶段，每个阶段由专用的 Agent 或工具处理，
用户只需用自然语言描述意图，系统自动完成文件推荐、模式设计、实体识别、关系抽取、
图谱导入和查询验证。

支持两类数据源：

- 结构化数据（CSV / JSON）：构建领域图（Domain Graph），提供权威的业务数据
- 非结构化数据（Markdown / TXT）：构建主题图（Subject Graph），从文本中抽取实体和关系

通过实体解析（Entity Resolution），两类图谱在 Neo4j 中建立 CORRESPONDS_TO 关系，
实现跨图溯源，例如从客户评论中的质量问题追溯到具体零件和供应商。

## 核心特性

- 多 Agent 协作：8 个独立阶段，每个阶段职责单一
- 人在回路：关键步骤需用户明确批准
- 混合图谱：结构化 + 非结构化数据统一建模
- 对话式交互：所有操作通过自然语言完成
- 桌面应用：基于 CustomTkinter 的跨平台界面
- 流式输出：Agent 回复逐字显示
- 长文本支持：可处理十万字以上的输出

## 工作流程

| 阶段 | 名称 | 类型 | 说明 |
|------|------|------|------|
| 01 | 定义目标 | Agent | 理解用户想构建什么类型的图谱 |
| 02 | 选择结构化文件 | Agent | 从 CSV/JSON 中推荐领域图数据源 |
| 03 | 图谱结构设计 | Agent 循环 | 提议 Schema 并由 Critic 审查 |
| 04 | 选择非结构化文件 | Agent | 从 Markdown/TXT 中推荐主题图数据源 |
| 05 | 实体识别 | Agent | 提议可从文本中抽取的实体类型 |
| 06 | 事实类型 | Agent | 提议实体之间的关系类型 |
| 07 | 构建 | 工具 | 执行 CSV 导入、Markdown 抽取、实体解析 |
| 08 | 查询 | 工具 | 直接运行 Cypher 语句验证结果 |

## 环境要求

- Python 3.10 或更高
- Neo4j 5.x（Desktop 或 Server）
- DeepSeek API Key
- 阿里云百炼 API Key（用于 Embedding）

## 安装步骤

### 1. 克隆项目

```bash
git clone <repository-url>
cd kg_builder
```

### 2. 创建虚拟环境

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
pip install -e .
```

### 4. 配置环境变量

复制 `.env.example` 为 `.env`，填写以下内容：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_MODEL=deepseek/deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com

NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j
NEO4J_IMPORT_DIR=./data/import

DASHSCOPE_API_KEY=sk-xxxxxxxx
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=qwen3.7-text-embedding
```

### 5. 准备数据

将 CSV 和 Markdown 文件放入 `data/import/` 目录：

```
data/import/
├── products.csv
├── assemblies.csv
├── components.csv
├── parts.csv
├── suppliers.csv
├── part_supplier_mapping.csv
└── product_reviews/
    ├── product_a_reviews.md
    ├── product_b_reviews.md
    └── ...
```

### 6. 启动 Neo4j

确保 Neo4j 已启动，浏览器访问 http://localhost:7474 可正常打开。

### 7. 运行应用

```bash
python run.py
```

## 项目结构

```
kg_builder/
├── run.py                                启动入口
├── pyproject.toml                        项目配置
├── requirements.txt                      依赖清单
├── .env                                  环境变量
│
├── src/kg_builder/
│   ├── config.py                         配置加载
│   ├── state.py                          状态键常量
│   │
│   ├── core/                             核心封装
│   │   ├── llm.py                        LLM 工厂
│   │   ├── neo4j_client.py               Neo4j 客户端
│   │   ├── neo4j_graphrag.py             GraphRAG 组件
│   │   └── agent_runner.py               Agent 执行器
│   │
│   ├── tools/                            工具层
│   │   ├── file_tools.py                 文件探查
│   │   ├── file_selection.py             文件选择
│   │   ├── goal_tools.py                 用户目标
│   │   ├── schema_tools.py               Schema 提议
│   │   ├── entity_tools.py               实体提议
│   │   ├── fact_tools.py                 事实提议
│   │   ├── kg_build_tools.py             结构化导入
│   │   ├── kg_build_tools_unstructured.py 非结构化抽取
│   │   └── entity_resolution.py          实体解析
│   │
│   ├── agents/                           Agent 层
│   │   ├── user_intent.py                用户意图
│   │   ├── structured_file_agent.py      结构化文件推荐
│   │   ├── unstructured_file_agent.py    非结构化文件推荐
│   │   ├── schema_proposal.py            Schema 提议
│   │   ├── schema_critic.py              Schema 审查
│   │   ├── ner_agent.py                  实体识别
│   │   ├── fact_agent.py                 事实类型
│   │   └── pipeline.py                   工作流编排
│   │
│   └── ui/                               桌面 UI
│       ├── app.py                        主窗口
│       ├── theme.py                      主题配置
│       ├── async_bridge.py               异步桥接
│       └── panels/                       面板
│           ├── base_panel.py             基类
│           ├── goal_panel.py             定义目标
│           ├── structured_files_panel.py 结构化文件
│           ├── schema_panel.py           图谱结构
│           ├── unstructured_files_panel.py 非结构化文件
│           ├── ner_panel.py              实体识别
│           ├── fact_panel.py             事实类型
│           ├── build_panel.py            构建
│           └── query_panel.py            查询
│
└── data/
    └── import/                           数据文件目录
```

## 使用说明

### 启动

```bash
python run.py
```

### 完整流程

1. 定义目标：描述你想构建的知识图谱
2. 选择结构化文件：批准用于构建领域图的 CSV
3. 图谱结构设计：审查 Agent 提议的节点和关系，输入"批准"确认
4. 选择非结构化文件：批准用于构建主题图的 Markdown
5. 实体识别：批准从文本中抽取的实体类型
6. 事实类型：批准实体之间的关系类型
7. 构建：依次执行以下命令
   - `build`：导入 CSV
   - `build-unstr`：从 Markdown 抽取实体关系
   - `resolve`：连接主题图与领域图
   - `all`：一键执行以上三步
8. 查询：输入 Cypher 语句验证

### 构建面板命令

| 命令 | 说明 |
|------|------|
| `build` | 导入 CSV 到 Neo4j（结构化） |
| `build-unstr` | 从 Markdown 抽取（非结构化） |
| `resolve` | 实体解析（连接两图） |
| `clear` | 清空数据库 |
| `all` | 依次执行 build、build-unstr、resolve |

## 架构说明

### 状态管理

各阶段通过 Session State 传递数据。关键状态键定义在 `state.py`：

| 键 | 说明 |
|------|------|
| `approved_user_goal` | 用户目标 |
| `approved_structured_files` | 已批准的结构化文件 |
| `approved_unstructured_files` | 已批准的非结构化文件 |
| `approved_construction_plan` | 已批准的 Schema |
| `approved_entity_types` | 已批准的实体类型 |
| `approved_fact_types` | 已批准的事实类型 |

### Agent 与工具

- Agent 通过 `instruction` 定义行为，通过 `tools` 定义能力
- 工具函数返回 `{"status": "success" | "error", ...}` 字典
- 关键状态写入由工具函数完成，Agent 只负责决策和调用

### 异步架构

ADK 使用 asyncio，Tkinter 使用事件循环。`AsyncBridge` 在后台线程运行 asyncio，
主线程通过 `submit(coro)` 提交任务并获取结果。

## 常见问题

### Neo4j 连接失败

检查 `.env` 中的 `NEO4J_URI` 是否为 `bolt://localhost:7687`，
以及 Neo4j 服务是否已启动。

### Embedding API 报错 401

检查 `DASHSCOPE_API_KEY` 是否有效，以及是否在阿里云百炼控制台开通了
`qwen3.7-text-embedding` 模型。

### build-unstr 报错

检查是否已完成 04、05、06 三个阶段的批准。
在 07 面板输入 `build-unstr` 前，确保：

- 04 已批准非结构化文件
- 05 已批准实体类型
- 06 已批准事实类型

### 输出过长显示不全

面板会自动截断超过 5000 字的输出，并显示"查看完整内容"链接。
点击链接可弹出新窗口查看全文。

## 技术栈

- Google ADK：多 Agent 框架
- LiteLLM：LLM 统一接口
- Neo4j：图数据库
- neo4j-graphrag：知识图谱构建
- CustomTkinter：桌面 UI
- DeepSeek：LLM 服务
- 阿里云百炼：Embedding 服务

## 开发说明

### 添加新的 Agent

1. 在 `agents/` 下创建新文件
2. 定义 `INSTRUCTION` 常量和 `build_xxx_agent()` 工厂函数
3. 在 `pipeline.py` 的 `KGBuilderPipeline` 中添加 `start_xxx()` 方法
4. 在 `ui/panels/` 下创建对应面板
5. 在 `ui/app.py` 的 `STEPS` 中注册

### 添加新的工具

1. 在 `tools/` 下创建或修改文件
2. 工具函数签名为 `def fn(arg: type, tool_context: ToolContext) -> dict`
3. 返回 `tool_success(key, value)` 或 `tool_error(message)`
4. 在对应 Agent 的 `tools` 列表中注册

## 许可证

MIT