# 城市生活计算管家（Agent + RAG）

一个结合 **RAG 政策检索** 与 **ReAct 工具调用** 的 Agent 项目：先检索目标城市的政策资料，
再调用计算工具（到手工资测算）给出可溯源的答案。支持按城市切换。

## 为什么这样设计（学习重点）
- **RAG**：把政策文档切片入向量库，回答前检索最相关的片段 → 答案有出处、可溯源
- **工具调用（ReAct）**：`search_knowledge` 检索工具 + `compute_salary` 计算工具，
  由模型自主决定何时检索、何时计算
- **城市可配置**：换城市 = 改 `.env` 的 `CITY` + 在 `data/docs/{CITY}/` 放一份语料，
  不改代码 —— 这正是 RAG「资料即插即用」的体现

## 目录结构
```
city-life-agent/
├── data/
│   └── docs/
│       └── 上海/           # 城市语料（每城市一个目录）
│           └── 社保与公积金.md
├── docs/
│   └── 项目设计文档.md      # 设计蓝图：提示词体系 + 个税改进路线
├── scripts/
│   └── main.py            # 入口：建库 → 检索演示 → Agent 问答（支持 --mode/--ask）
├── src/
│   ├── config.py          # 读取 .env（含 CITY、REPLY_MODE）
│   ├── prompts.py         # 提示词体系：系统/检索规范/回答模式模板 + build_prompt
│   ├── rag_build.py       # 建库：解析 → 切块 → 嵌入 → 入库（Qdrant 本地）
│   ├── tools.py           # 自定义工具：compute_salary 到手工资计算器
│   └── agent_runner.py    # Agent：RAGMiddleware(agentic) + 工具 + 流式输出
├── api/
│   ├── server.py          # 后端：/chat(自定义SSE) + /chat-ai(AI SDK 5 SSE)
│   └── static/            # 验证版单轮问答页
├── web/                   # 前端工程：Vue3 + Vite + Vercel AI SDK
│   ├── vite.config.js     # /chat-ai 代理到后端 8000
│   ├── src/assets/theme.css # 全局主题变量（深/浅两档）
│   └── src/components/    # ChatView(对话) + SalaryChart(图表) + ThemeToggle(主题切换)
├── .env                   # 密钥配置（勿提交）
├── .env.example           # 配置模板
├── requirements.txt
└── README.md
```

## 快速开始
```powershell
# 1. 创建虚拟环境并安装
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
使用清华镜像源：pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 若 QdrantStore 报缺依赖，补装：pip install qdrant-client

# 2. 配置：复制 .env.example 为 .env，填 DASHSCOPE_API_KEY；CITY 选目标城市

# 3. 在 data/docs/{CITY}/ 放政策语料（.md/.txt）

# 4. 运行（回答模式：brief / standard / report，默认 standard）
python scripts/main.py                          # 标准模式
python scripts/main.py --mode report            # 报告模式
python scripts/main.py --mode brief             # 简洁模式
python scripts/main.py --ask "北京月薪3万到手多少？写份报告"   # 自定义问题 + 自然语言识别模式
```

## 加一个新城市
1. 新建 `data/docs/北京/政策.md`（写该城市社保/公积金/个税要点）
2. 在 `src/tools.py` 的 `CITY_PARAMS` 加该城市社保/公积金比例
3. 改 `.env` 的 `CITY=北京`
不需要改其他代码。

## 项目功能全景（当前完整能力）
- **RAG**：解析 → 切块(overlap) → embedding → Qdrant 本地持久化；`agentic` 模式把检索作为工具
- **ReAct 工具调用**：`compute_salary`（含基数上下限/专项扣除/估算区间）+ `compute_rent`（押金/中介费/首月/月均/年总）+ `search_knowledge`；`BYPASS` 放行安全工具
- **提示词体系**：L1 系统规则 + L2 检索规范（防幻觉）+ L3 三档回答模式（brief/standard/report），支持命令行 / 自然语言 / 配置三种切换
- **个税升级**：月度三档速算、缴费基数上下限、专项附加扣除参数化、估算区间 + 口径假设
- **城市可配置**：改 `.env` 的 CITY + 加语料目录 + 加 CITY_PARAMS，不改代码
- **已验证**：三档回答差异明显、触上限/下限、专项扣除联动、报告模式批判性检查（主动指出知识库与工具口径差异）

## 学习笔记 / 踩坑记录（复盘用）

### ⭐ 重点：AgentScope 2.0 内置工具权限安全机制（RequireUserConfirmEvent）
- **现象**：Agent 调用工具时，流式事件最后停在 `REQUIRE_USER_CONFIRM`，工具没真正执行、没有最终回答文本。
- **原因**：AgentScope 2.0 默认权限模式为 `PermissionMode.DEFAULT`——**每次工具调用都要求人工批准**。权限引擎拦下工具调用，发出 `RequireUserConfirmEvent` 等待确认；`reply_stream` 若不处理该事件，流程就在此中断。
- **处理**：本项目工具都是安全的纯计算/检索，用 `PermissionMode.BYPASS` 跳过确认：
  ```python
  from agentscope.permission import PermissionMode
  agent.state.permission_context.mode = PermissionMode.BYPASS
  ```
- **启示**：权限确认是 Agent 框架的通用安全设计（防止 Agent 擅自执行危险操作）。生产环境应保留确认、或用 allow/deny 规则精细放行；`BYPASS` 只适合**可信的本地/沙箱工具**。

### 其他踩坑（AgentScope 2.0.10 实测）
| 坑 | 正解 |
|---|---|
| base_url 传错位置 | 放 `OpenAICredential(api_key, base_url)`；**不能**放 `client_kwargs`（会和内部 AsyncClient 的 base_url 冲突报 multiple values） |
| RAGMiddleware 知识库参数 | `knowledge_bases=`（官方文档写的 `knowledges=` 是旧版） |
| 自定义工具注册 | 用 `FunctionTool(compute_salary)`；本版**没有 `@tool` 装饰器** |
| 工具调用事件字段 | `ToolCallStartEvent` 用 `tool_call_name`（没有 `.tool_call.input`） |
| 最终文本流式输出 | 遍历 `reply_stream`，用 `EventType.TEXT_BLOCK_DELTA` 逐字打印 `event.delta` |

### 通用知识（RAG / 切块）
- 切块时用重叠（overlap）避免「一句话被切在块边界导致语义断裂」；块大小 256~512 token 是常见起点
- 流式事件是理解 Agent 内部循环的最佳窗口，典型顺序：`THINKING`（思考）→ `TOOL_CALL`（调工具）→ `TOOL_RESULT`（工具结果）→ `TEXT`（最终回答）

### ⭐ 全链路原理复盘（四个体系 = 一条 ReAct 循环上的不同插片）
核心：这个 Agent 本质是一条 **ReAct 推理循环**，RAG / 权限 / 提示词在循环的**不同位置**介入：
- **提示词 = 入口（管"怎么想"）**：L1 系统规则（角色+全局铁律）→ L2 检索规范（防幻觉：只依据资料/标注来源/矛盾说明差异）→ L3 回答模式 → L4 工具 schema。规则写进提示词，模型才会照着做（例：L2 的矛盾条款直接催生了"知识库 vs 工具口径不一致不强行合并"）。
- **RAG = 信息源（管"拿什么"）**：语料→解析→切块(overlap)→embedding→Qdrant→KnowledgeBase→`RAGMiddleware(mode="agentic")`。`agentic` 让检索作为工具、由模型按需触发，所以模型会"多次自主补检"。
- **ReAct = 骨架（循环本身）**：`THINKING`（想）→ `TOOL_CALL`（决定调）→ 工具执行 → `TOOL_RESULT`（看结果）回喂模型，可循环多次，信息够了才出 `TEXT`。**Agent 的核心不在模型而在"循环+工具"骨架**。
- **权限 = 闸门（管"能不能调"）**：框架在工具调用处拦截。`DEFAULT` 每次发 `RequireUserConfirmEvent` 等人工批准（命令行会卡死）；本项目用 `BYPASS` 放行纯计算/只读工具。**生产务必保留确认或 allow/deny 精细放行**，`BYPASS` 只适合可信本地工具。

一次完整请求：注入提示词 → 模型 THINKING → 决定调 `search_knowledge` + `compute_salary` → 权限放行 → 工具返回 → TOOL_RESULT 回喂 → 按 L3 输出 brief/standard/report。四体系缺一不可：缺提示词→乱说，缺 RAG→没出处，缺 ReAct→算不出，缺权限→危险。

## 学习进度
- [x] 项目结构
- [x] RAG 建库（解析/切块/嵌入/入库）
- [x] ReAct 工具调用（compute_salary）
- [x] Agent + RAG 接入（RAGMiddleware agentic）
- [x] 你本机跑通（建库/检索/工具调用/流式回答）
- [x] 提示词体系：分层（系统/检索规范/回答模式）+ 三档切换（Phase 1）
- [x] 回答模式三档验证：brief/standard/report + 自然语言识别（"写份报告"/"简单说"）
- [x] 个税算法修复（月度三档速算）
- [x] Phase 2：检索引用规范（L2 防幻觉：只依据资料/标注来源/矛盾说明差异，已验证生效）
- [x] Phase 3：个税升级（基数上下限/专项扣除/估算区间）
- [x] 前端工程化：Vue3 + Vite + Vercel AI SDK（useChat 流式 + 工具卡片 + Markdown 渲染）
- [x] 生成式 UI：compute_salary 结果以 `data-salary` part 下发，前端 ECharts 画到手构成图
- [x] 工具调用可展开卡片（点击查看输入参数 / 返回结果）
- [x] 三档主题切换（深色/浅色/跟随系统）：theme.css 全局 CSS 变量 + ThemeToggle 独立组件
- [x] Phase 2：租房成本工具 compute_rent（押金/中介费/首月一次性/月均/年总）+ 租房语料 + 生成式 UI 租房构成图（RentChart.vue）

## 能力扩展路线（让「城市生活」名副其实）
首页副标题已放宽为「城市生活的账，帮你算清楚」，贴合产品定位；但后端目前只实现薪资/社保一类工具。
为保证「承诺 ≤ 能力」，能力需分阶段补齐。每个新能力 = **一条工具 + 一份知识库语料**，不改架构：

| 阶段 | 能力方向 | 工具示例 | 知识库语料 |
|---|---|---|---|
| ✅ 已完成 | 薪资 / 社保 / 公积金 | compute_salary | 城市社保与公积金 |
| ✅ Phase 2 | 租房成本 | compute_rent（租金/押金/中介费/物业水电） | 城市租房成本要点 |
| Phase 3 | 通勤开销 | compute_commute（地铁/打车/油费） | 城市交通政策/票价 |
| Phase 4 | 房贷月供 | compute_mortgage（LPR/首付/年限） | 城市限购/贷款政策 |
| Phase 5 | 生活成本 | compute_cost_index（物价/餐饮） | 城市生活成本数据 |
| 持续 | 更多城市 | — | data/docs/{CITY}/ 语料 + CITY_PARAMS 扩展 |

**实现要点**：每个工具在 `src/tools.py` 注册 `FunctionTool`，前端自动出工具卡片；结构化结果可加 `data-*` part 复用生成式 UI（参照 `data-salary`）。

## 后续计划（To-Do，尚未实施）
- [x] **多轮对话记忆**：`/chat-ai` 接收 conversationId，后端从 SQLite 读历史消息转成 Msg list 回喂 Agent（最近 20 条控 token），支持追问上下文
- [x] **会话侧边栏 + 历史持久化**：SQLite（data/app.db，WAL）存 conversations/messages，Sidebar.vue 支持新建/切换/重命名/删除，刷新不丢；user_id 列已预留多用户扩展
- [ ] **Human-in-the-loop 审批弹窗**：后端已有 `RequireUserConfirmEvent` 权限机制，但目前 `BYPASS` 放行；需在 AI SDK 流中接入 `tool-approval-request` part，前端渲染"允许 / 拒绝"弹窗（生产安全关键）
- [ ] **消息操作**：复制、重新生成(regenerate)、编辑重发、删除单条
- [ ] **生成式 UI 深化**：当前仅 `data-salary` 图表；可扩展为让模型返回任意结构化数据驱动自定义组件
- [ ] **流式节流(throttle)**：更平滑的逐字输出
- [x] **主题切换三档**：深色/浅色/跟随系统（theme.css 全局 CSS 变量 + ThemeToggle.vue 独立组件）
- [ ] **移动端响应式适配**
