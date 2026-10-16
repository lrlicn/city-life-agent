"""后端服务：把现有 Agent 封装成 SSE 流式接口（单轮问答页）。

核心思路：`src/agent_runner.run_rag_agent` 是"边跑边 print 流式事件"，
这里只把 print 换成 yield 到 SSE 推给前端——**Agent 核心逻辑原封不动**。

用 starlette（venv 已装）而非 fastapi，避免额外依赖。

启动：
    .venv\\Scripts\\python.exe -m api.server
  （浏览器打开 http://127.0.0.1:8000）
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.applications import Starlette
from starlette.responses import StreamingResponse, JSONResponse, FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel

from agentscope.event import EventType, UserConfirmResultEvent, ConfirmResult
from agentscope.message import UserMsg, AssistantMsg

from src.rag_build import build_knowledge_base
from src.agent_runner import build_rag_agent
from src import db, config, interaction
from openai import OpenAI

# 启动即建表（幂等）
db.init_db()

# 轻量客户端：用于异步生成会话标题
_title_client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

async def generate_title_async(conv_id: str, question: str):
    """后台异步生成总结性标题，不阻塞主响应"""
    import asyncio
    def _gen():
        try:
            r = _title_client.chat.completions.create(
                model=config.CHAT_MODEL,
                messages=[
                    {"role": "system", "content": "请把用户的问题总结成一个简短的会话标题，要求：一句话概括核心主题，不超过 20 字，不要标点符号，不要引号。"},
                    {"role": "user", "content": question},
                ],
                max_tokens=30,
                temperature=0.3,
            )
            title = r.choices[0].message.content.strip().strip('"').strip("'")
            if title:
                # 覆盖占位标题（原始问题截断）；expect_current 防止覆盖用户手动改名
                db.set_conversation_summary_title(conv_id, title[:30], question[:30])
        except Exception as e:
            print(f"[title-gen] 失败: {e}")
    await asyncio.to_thread(_gen)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 知识库单例：进程内只建一次，避免每次请求重复入库、累积重复 doc_id。
_kb_cache = None


async def get_kb():
    """懒加载并复用知识库（store 连接保持打开，进程退出自动释放）。"""
    global _kb_cache
    if _kb_cache is None:
        kb, _store = await build_knowledge_base()
        _kb_cache = kb
    return _kb_cache


class ChatRequest(BaseModel):
    """问答请求体。mode 缺省用 .env 的 REPLY_MODE；conversation_id 用于多轮记忆与落库。"""
    question: str
    mode: str | None = None
    conversation_id: str | None = None
    require_approval: bool = False   # 阶段二：需审批（工具执行前弹确认）/ 免审批（BYPASS）


async def event_gen(req: ChatRequest):
    """SSE 事件流：工具调用事件 + 文本 delta，逐条推给前端。"""
    try:
        kb = await get_kb()
        agent = await build_rag_agent(kb, req.mode)
        user_msg = UserMsg(name="user", content=req.question)
        async for event in agent.reply_stream(user_msg):
            if event.type == EventType.TOOL_CALL_START:
                yield f"data: {json.dumps({'type': 'tool', 'name': event.tool_call_name}, ensure_ascii=False)}\n\n"
            elif event.type == EventType.TEXT_BLOCK_DELTA:
                yield f"data: {json.dumps({'type': 'text', 'delta': event.delta}, ensure_ascii=False)}\n\n"
    except Exception as e:  # noqa: BLE001 —— 流式中断时把错误推给前端
        yield f"data: {json.dumps({'type': 'error', 'msg': str(e)}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


def _parse_tool_input(raw: str) -> dict:
    """把工具参数 JSON 增量字符串解析成 dict，失败返回空（增量未凑齐/含非 JSON）。"""
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _parse_salary_output(text: str) -> dict | None:
    """从 compute_salary 输出文本提取结构化数字，供前端生成式 UI 画图。

    compute_salary 输出格式固定（见 src/tools.py），用正则抓关键数值；
    若拿不到「到手」则视为解析失败返回 None。
    """
    def grab(pattern: str) -> int | None:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    data = {
        "base": grab(r"缴费基数 ≈ (\d+)"),
        "social": grab(r"社保\(个人\) ≈ (\d+)"),
        "fund": grab(r"公积金\(个人\) ≈ (\d+)"),
        "tax": grab(r"个税 ≈ (\d+)"),
        "net": grab(r"到手 ≈ (\d+)"),
    }
    m = re.search(r"估算区间：约 (\d+) ~ (\d+)", text)
    if m:
        data["range"] = [int(m.group(1)), int(m.group(2))]
    return data if data["net"] is not None else None


def _parse_rent_output(text: str) -> dict | None:
    """从 compute_rent 输出文本提取结构化数字，供前端生成式 UI 画租房构成图。"""
    def grab(pattern: str) -> int | None:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    data = {
        "deposit": grab(r"押金 ≈ (\d+)"),
        "agency": grab(r"中介费 ≈ (\d+)"),
        "first_month": grab(r"首月一次性支出 ≈ (\d+)"),
        "monthly": grab(r"月均生活成本 ≈ (\d+)"),
        "year": grab(r"年总成本 ≈ (\d+)"),
    }
    return data if data["first_month"] is not None else None


def _parse_commute_output(text: str) -> dict | None:
    """从 compute_commute 输出文本提取各方式月成本，供前端画通勤对比图。"""
    def grab(pattern: str) -> int | None:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    data = {
        "subway": grab(r"地铁/公交 ≈ (\d+)"),
        "ebike": grab(r"电动车 ≈ (\d+)"),
        "drive": grab(r"自驾 ≈ (\d+)"),
        "taxi": grab(r"打车 ≈ (\d+)"),
    }
    m = re.search(r"最省 ≈ (\S+) 约 (\d+)", text)
    if m:
        data["cheapest"] = m.group(1)
    return data if data["subway"] is not None else None


def _parse_mortgage_output(text: str) -> dict | None:
    """从 compute_mortgage 输出文本提取还款方式关键数值与月供构成，供前端画对比折线与构成环图。

    单段（纯商贷/纯公积金）行式如「商贷等额本息月供 ≈ N」；组合贷带「合计」前缀，
    另有「- 类型 贷款 X 元 @ R%，月供 ≈ N」拆分行 → structure（多段才下发）。
    """
    def grab(pattern: str) -> int | None:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None

    data = {
        "annuity_pay": grab(r"等额本息月供 ≈ (\d+)"),
        "annuity_interest": grab(r"等额本息总利息 ≈ (\d+)"),
        "ep_first": grab(r"等额本金首月 ≈ (\d+)"),
        "ep_last": grab(r"等额本金末月 ≈ (\d+)"),
        "ep_interest": grab(r"等额本金总利息 ≈ (\d+)"),
    }
    m = re.search(r"利息更省 ≈ (\S+) 约省 (\d+)", text)
    if m:
        data["cheaper"] = m.group(1)
        data["save"] = int(m.group(2))
    # 月供构成拆分（等额本息口径）：商贷/公积金/组合均提取，仅多段时前端画环图
    segs = [{"type": m.group(1), "amount": int(m.group(2)), "rate": float(m.group(3)),
             "annuity_pay": int(m.group(4))}
            for m in re.finditer(r"- (\S+) 贷款 (\d+) 元 @ ([\d.]+)%，月供 ≈ (\d+)", text)]
    if len(segs) > 1:
        data["structure"] = segs
    mt = re.search(r"组合贷：(.+?)，(\d+) 年", text)
    if mt:
        data["loan_type"] = "组合"
        data["rates_label"] = mt.group(1)
        data["years"] = int(mt.group(2))
    else:
        m1 = re.search(r"贷款 \d+ 元，(商贷|公积金)，年利率 ([\d.]+)%，(\d+) 年", text)
        if m1:
            data["loan_type"] = m1.group(1)
            data["rates_label"] = f"{m1.group(1)} {m1.group(2)}%"
            data["years"] = int(m1.group(3))
    return data if data["annuity_pay"] is not None else None


def _parse_cost_index_output(text: str) -> dict | None:
    """从 compute_cost_index 输出文本提取各城市分类指数，供前端画分组柱状对比图。

    行式契约（见 src/tools.py）：每城市一行  {city}：综合 {n}（租房 a / 餐饮 b / 交通 c / 日用 d）。
    """
    mb = re.search(r"基准：(\S+) = 100", text)
    base_city = mb.group(1) if mb else ""
    cities = []
    for m in re.finditer(
        r"(\S+)：综合 (\d+)（租房 (\d+) / 餐饮 (\d+) / 交通 (\d+) / 日用 (\d+)）", text
    ):
        cities.append({
            "city": m.group(1),
            "composite": int(m.group(2)),
            "index": [int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6))],
        })
    mc = re.search(r"最省 ≈ (\S+) 综合 (\d+)", text)
    data = {
        "base_city": base_city,
        "categories": ["租房", "餐饮", "交通", "日用"],
        "cities": cities,
    }
    if mc:
        data["cheapest"] = mc.group(1)
        data["cheapest_composite"] = int(mc.group(2))
    return data if cities else None


def _parse_export_output(text: str) -> dict | None:
    """从 export_report 输出文本提取报告标题/下载链接/文件名，供前端渲染下载卡片。

    行式契约（见 src/tools.py）：仅当报告真正落盘（含「报告已导出」且「下载：」行）才返回。
    """
    if not text or "报告已导出" not in text:
        return None

    def grab(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

    url = grab(r"下载：(\S+)")
    if not url:
        return None
    data = {
        "title": grab(r"标题：(.+)") or "报告",
        "url": url,
        "filename": grab(r"文件：(\S+)") or url.rsplit("/", 1)[-1],
        "format": grab(r"格式：(\S+)") or "Markdown",
    }
    wc = re.search(r"字数：(\d+)", text)
    if wc:
        data["chars"] = int(wc.group(1))
    return data


async def event_gen_ai(req: ChatRequest):
    """AI SDK 5 Data Stream 协议（SSE）：供前端 @ai-sdk/vue 的 useChat 消费。

    完整翻译 Agent 事件：
      TOOL_CALL_START/DELTA/END → tool-input-start / -delta / -available（含真实参数）
      TOOL_RESULT_TEXT_DELTA/END → tool-output-available（含真实结果）
      额外：compute_salary 执行完后发 data-salary part，前端据此画生成式 UI 图表。
    """
    try:
        _t0 = time.monotonic()   # 回答生成耗时起点（含 RAG 检索 + Agent 全链路）
        kb = await get_kb()
        agent = await build_rag_agent(kb, req.mode, require_approval=req.require_approval)
        # 多轮记忆：把该会话历史文本消息转成 Msg list 一并回喂（只取最近 20 条，控 token）
        history_msgs: list = []
        conv_id = req.conversation_id
        is_first_turn = not conv_id      # 新建会话首轮才做 AI 标题总结（避免每轮重写）
        # 新建会话首次发消息：立刻建会话+设标题，不等流式结束
        if not conv_id:
            cv = db.create_conversation()
            conv_id = cv["id"]
            db.set_conversation_title(conv_id, req.question[:30])
            # 标题只依赖问题：立刻后台并发生成，与回答流式同时进行。
            # 通常几秒内完成，远早于回答结束 → 前端可在生成期间就轮询到总结标题
            import asyncio
            asyncio.create_task(generate_title_async(conv_id, req.question))
        if conv_id:
            for m in db.list_messages(conv_id)[-20:]:
                t = "".join(p.get("text", "") for p in m["parts"] if p.get("type") == "text")
                if not t.strip():
                    continue
                if m["role"] == "user":
                    history_msgs.append(UserMsg(name="user", content=t))
                else:
                    history_msgs.append(AssistantMsg(name="rag-agent", content=t))
        new_msg = UserMsg(name="user", content=req.question)
        inputs = history_msgs + [new_msg] if history_msgs else new_msg
        # 用户消息立刻写入数据库，保证下一轮对话能读到历史
        db.add_message(conv_id, "user",
                       [{"type": "text", "text": req.question}], mode=req.mode)
        msg_id = f"msg_{conv_id}_{int(__import__('time').time() * 1000)}"
        yield f'data: {json.dumps({"type":"start","messageId":msg_id})}\n\n'
        # 新会话：把后端真实会话 id 权威透传给前端，供其在生成期间提前对账（临时 id → 真实 id），
        # 不落入 stream_parts（仅本次流式用于 UI 对账，不污染历史）
        if is_first_turn:
            yield f"data: {json.dumps({'type': 'data-conversation', 'data': {'id': conv_id}})}\n\n"
        text_id = f"text_{msg_id}"
        text_started = False
        final_text = ""          # 累积最终回答文本（落库用）
        reasoning_text = ""      # 累积思考过程文本（落库用）
        tool_names: dict[str, str] = {}   # tool_call_id -> 工具名
        tool_args: dict[str, str] = {}    # tool_call_id -> 累积的参数 JSON 片段
        tool_outputs: dict[str, str] = {}  # tool_call_id -> 累积的结果文本
        # 按原始流式顺序记录 parts（落库用）
        stream_parts: list = []
        current_reasoning = None  # 当前正在累积的 reasoning part
        current_text = None       # 当前正在累积的 text part
        while True:
            parked = None
            async for event in agent.reply_stream(inputs):
                if event.type == EventType.TOOL_CALL_START:
                    tool_names[event.tool_call_id] = event.tool_call_name
                    tool_args[event.tool_call_id] = ""
                    tool_outputs[event.tool_call_id] = ""
                    yield f"data: {json.dumps({'type': 'tool-input-start', 'toolCallId': event.tool_call_id, 'toolName': event.tool_call_name}, ensure_ascii=False)}\n\n"
                elif event.type == EventType.TOOL_CALL_DELTA:
                    if event.tool_call_id in tool_args:
                        tool_args[event.tool_call_id] += event.delta
                    yield f"data: {json.dumps({'type': 'tool-input-delta', 'toolCallId': event.tool_call_id, 'inputTextDelta': event.delta}, ensure_ascii=False)}\n\n"
                elif event.type == EventType.TOOL_CALL_END:
                    inp = _parse_tool_input(tool_args.get(event.tool_call_id, ""))
                    yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': event.tool_call_id, 'toolName': tool_names.get(event.tool_call_id, ''), 'input': inp}, ensure_ascii=False)}\n\n"
                    # 澄清选择：模型调 ask_user → 先注册 Future + 下发 data-interaction（选项），
                    # 随后 ask_user 工具体阻塞在 await_choice，整条 SSE 停在“工具执行中”直到用户点选。
                    if tool_names.get(event.tool_call_id, "") == "ask_user":
                        q = inp.get("question", "")
                        opts_raw = inp.get("options", "")
                        iid, _fut = interaction.begin_choice(q, opts_raw)
                        inter = {"kind": "choice", "id": iid, "question": q,
                                 "options": interaction.parse_options(opts_raw)}
                        yield f"data: {json.dumps({'type': 'data-interaction', 'data': inter}, ensure_ascii=False)}\n\n"
                        stream_parts.append({"type": "data-interaction", "data": inter})
                elif event.type == EventType.TOOL_RESULT_TEXT_DELTA:
                    if event.tool_call_id in tool_outputs:
                        tool_outputs[event.tool_call_id] += event.delta
                elif event.type == EventType.TOOL_RESULT_END:
                    tcid = event.tool_call_id
                    name = tool_names.get(tcid, "")
                    output = tool_outputs.get(tcid, "")
                    yield f"data: {json.dumps({'type': 'tool-output-available', 'toolCallId': tcid, 'toolName': name, 'output': output}, ensure_ascii=False)}\n\n"
                    # 先把正在累积的文本和思考存起来，保持原始顺序
                    if current_reasoning is not None and current_reasoning["text"].strip():
                        stream_parts.append(current_reasoning)
                        current_reasoning = None
                    if current_text is not None and current_text["text"].strip():
                        stream_parts.append(current_text)
                        current_text = None
                    # 把工具调用 part 按顺序加入 stream_parts
                    inp = _parse_tool_input(tool_args.get(tcid, ""))
                    stream_parts.append({
                        "type": "tool",
                        "toolCallId": tcid,
                        "name": name,
                        "input": inp,
                        "output": output,
                    })
                    # 生成式 UI：compute_salary → data-salary part（前端据此画图）
                    if name == "compute_salary" and output:
                        parsed = _parse_salary_output(output)
                        if parsed:
                            if inp.get("city"):
                                parsed["city"] = inp.get("city")
                            if inp.get("monthly_salary") is not None:
                                parsed["monthly_salary"] = inp.get("monthly_salary")
                            yield f"data: {json.dumps({'type': 'data-salary', 'data': parsed}, ensure_ascii=False)}\n\n"
                            stream_parts.append({"type": "data-salary", "data": parsed})
                    # 生成式 UI：compute_rent → data-rent part（前端据此画租房构成图）
                    if name == "compute_rent" and output:
                        parsed = _parse_rent_output(output)
                        if parsed:
                            if inp.get("city"):
                                parsed["city"] = inp.get("city")
                            if inp.get("monthly_rent") is not None:
                                parsed["monthly_rent"] = inp.get("monthly_rent")
                            yield f"data: {json.dumps({'type': 'data-rent', 'data': parsed}, ensure_ascii=False)}\n\n"
                            stream_parts.append({"type": "data-rent", "data": parsed})
                    # 生成式 UI：compute_commute → data-commute part（前端据此画通勤对比图）
                    if name == "compute_commute" and output:
                        parsed = _parse_commute_output(output)
                        if parsed:
                            if inp.get("city"):
                                parsed["city"] = inp.get("city")
                            if inp.get("one_way_km") is not None:
                                parsed["one_way_km"] = inp.get("one_way_km")
                            if inp.get("days_per_month") is not None:
                                parsed["days_per_month"] = inp.get("days_per_month")
                            yield f"data: {json.dumps({'type': 'data-commute', 'data': parsed}, ensure_ascii=False)}\n\n"
                            stream_parts.append({"type": "data-commute", "data": parsed})
                    # 生成式 UI：compute_mortgage → data-mortgage part（前端据此画还款计划对比图）
                    if name == "compute_mortgage" and output:
                        parsed = _parse_mortgage_output(output)
                        if parsed:
                            if inp.get("loan_amount") is not None:
                                parsed["loan_amount"] = inp.get("loan_amount")
                            if inp.get("annual_rate") is not None:
                                parsed["annual_rate"] = inp.get("annual_rate")
                            if inp.get("years") is not None:
                                parsed["years"] = inp.get("years")
                            if inp.get("city"):
                                parsed["city"] = inp.get("city")
                            if inp.get("loan_type"):
                                parsed["loan_type"] = inp.get("loan_type")
                            yield f"data: {json.dumps({'type': 'data-mortgage', 'data': parsed}, ensure_ascii=False)}\n\n"
                            stream_parts.append({"type": "data-mortgage", "data": parsed})
                    # 生成式 UI：compute_cost_index → data-cost-index part（前端据此画多城市成本指数对比图）
                    if name == "compute_cost_index" and output:
                        parsed = _parse_cost_index_output(output)
                        if parsed:
                            if inp.get("base_city"):
                                parsed["base_city"] = inp.get("base_city")
                            yield f"data: {json.dumps({'type': 'data-cost-index', 'data': parsed}, ensure_ascii=False)}\n\n"
                            stream_parts.append({"type": "data-cost-index", "data": parsed})
                    # 生成式 UI：export_report → data-export part（前端据此渲染报告下载卡片）
                    if name == "export_report" and output:
                        parsed = _parse_export_output(output)
                        if parsed:
                            yield f"data: {json.dumps({'type': 'data-export', 'data': parsed}, ensure_ascii=False)}\n\n"
                            stream_parts.append({"type": "data-export", "data": parsed})
                elif event.type == EventType.THINKING_BLOCK_START:
                    # 先把正在累积的文本存起来，保持原始顺序
                    if current_text is not None and current_text["text"].strip():
                        stream_parts.append(current_text)
                        current_text = None
                    yield f"data: {json.dumps({'type': 'reasoning-start', 'id': 'reason_1'}, ensure_ascii=False)}\n\n"
                    current_reasoning = {"type": "reasoning", "text": ""}
                elif event.type == EventType.THINKING_BLOCK_DELTA:
                    reasoning_text += event.delta
                    if current_reasoning is not None:
                        current_reasoning["text"] += event.delta
                    yield f"data: {json.dumps({'type': 'reasoning-delta', 'id': 'reason_1', 'delta': event.delta}, ensure_ascii=False)}\n\n"
                elif event.type == EventType.THINKING_BLOCK_END:
                    yield f"data: {json.dumps({'type': 'reasoning-end', 'id': 'reason_1'}, ensure_ascii=False)}\n\n"
                    if current_reasoning is not None and current_reasoning["text"].strip():
                        stream_parts.append(current_reasoning)
                    current_reasoning = None
                elif event.type == EventType.TEXT_BLOCK_DELTA:
                    if not text_started:
                        yield f"data: {json.dumps({'type': 'text-start', 'id': text_id}, ensure_ascii=False)}\n\n"
                        text_started = True
                    # 工具/思考会把 current_text 落库并置 None；其后若再来文本（如最终回答），
                    # 必须重开一个 text part，否则这段正文不会被累积 → 切回历史时丢失
                    if current_text is None:
                        current_text = {"type": "text", "text": ""}
                    yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': event.delta}, ensure_ascii=False)}\n\n"
                    final_text += event.delta
                    current_text["text"] += event.delta
                elif event.type == EventType.REQUIRE_USER_CONFIRM:
                    # 阶段二·工具审批：Agent 在本趟流末尾 park，等待外部确认。
                    # 记下待确认事件（reply_id + 待批 tool_calls），交本 while 收尾下发确认卡片。
                    parked = event
            if parked is None:
                break
            # 需审批：构造确认卡片下发，阻塞等待用户点“批准/拒绝”（或超时）
            reply_id = parked.reply_id
            tcs = list(parked.tool_calls or [])
            tools_payload = [
                {"tool_call_id": tc.id, "name": tc.name, "input": _parse_tool_input(tc.input)}
                for tc in tcs
            ]
            iid, fut = interaction.register()
            inter = {"kind": "confirm", "id": iid, "reply_id": reply_id, "tools": tools_payload}
            yield f"data: {json.dumps({'type': 'data-interaction', 'data': inter}, ensure_ascii=False)}\n\n"
            stream_parts.append({"type": "data-interaction", "data": inter})
            decision = await interaction.wait_result(iid, fut, timeout=600)
            approved = decision == "approve"
            inter["answered"] = decision or "timeout"
            # 用确认结果在同一 agent 上续跑：批准→执行工具；拒绝/超时→该工具被 DENY，模型据此收尾
            inputs = UserConfirmResultEvent(
                reply_id=reply_id,
                confirm_results=[ConfirmResult(confirmed=approved, tool_call=tc) for tc in tcs],
            )
        if text_started:
            yield f"data: {json.dumps({'type': 'text-end', 'id': text_id}, ensure_ascii=False)}\n\n"
        # 把最后累积的 text part 加入 stream_parts
        if current_text is not None and current_text["text"].strip():
            stream_parts.append(current_text)
        # 按原始顺序落库：assistant 消息（user 消息已在流式开始前写入）
        if stream_parts:
            elapsed_ms = int((time.monotonic() - _t0) * 1000)
            db.add_message(conv_id, "assistant", stream_parts, mode=req.mode, duration_ms=elapsed_ms)
        db.touch_conversation(conv_id)
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'type': 'error', 'errorText': str(e)}, ensure_ascii=False)}\n\n"
    yield 'data: {"type":"finish"}\n\n'
    yield "data: [DONE]\n\n"


async def chat_ai(request):
    """AI SDK useChat 入口：请求体为 {messages:[{role, content|parts}], mode?}。

    从最后一条 user 消息提取 question；mode 可选，缺省用 .env 的 REPLY_MODE。
    """
    body = await request.json()
    req = ChatRequest(
        question="",
        mode=body.get("mode"),
        conversation_id=body.get("conversationId") or body.get("conversation_id"),
        require_approval=bool(body.get("require_approval")),
    )
    for m in reversed(body.get("messages") or []):
        if m.get("role") != "user":
            continue
        text = m.get("content") or ""
        if not text:
            for p in m.get("parts") or []:
                if p.get("type") == "text":
                    text += p.get("text", "")
        if text.strip():
            req.question = text
            break
    if not req.question.strip():
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'errorText': 'question 不能为空'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
            headers={"x-vercel-ai-ui-message-stream": "v1"},
        )
    return StreamingResponse(
        event_gen_ai(req),
        media_type="text/event-stream",
        headers={"x-vercel-ai-ui-message-stream": "v1"},
    )


async def chat(request):
    body = await request.json()
    req = ChatRequest(question=str(body.get("question", "")), mode=body.get("mode"))
    if not req.question.strip():
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'msg': 'question 不能为空'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )
    return StreamingResponse(event_gen(req), media_type="text/event-stream")


# ---- 会话 CRUD（SQLite 持久化）----

async def api_list_conversations(request):
    rows = db.list_conversations()
    return JSONResponse(rows)


async def api_create_conversation(request):
    body = await request.json()
    cv = db.create_conversation(city=body.get("city"))
    return JSONResponse(cv)


async def api_rename_conversation(request):
    body = await request.json()
    title = str(body.get("title", "")).strip()[:40]
    if not title:
        return JSONResponse({"ok": False, "msg": "title 为空"}, status_code=400)
    ok = db.rename_conversation(request.path_params["conv_id"], title)
    return JSONResponse({"ok": ok})


async def api_delete_conversation(request):
    ok = db.delete_conversation(request.path_params["conv_id"])
    return JSONResponse({"ok": ok})


async def api_list_messages(request):
    msgs = db.list_messages(request.path_params["conv_id"])
    return JSONResponse(msgs)


async def api_truncate_conversation(request):
    """分支重生成：从第 turn 轮 user 消息起截断旧链（含该条），前端随后重发该轮问题。"""
    body = await request.json()
    try:
        turn = int(body.get("turn", 0))
    except (TypeError, ValueError):
        turn = 0
    if turn < 1:
        return JSONResponse({"ok": False, "msg": "turn 需为 >= 1 的整数"}, status_code=400)
    deleted = db.truncate_from_turn(request.path_params["conv_id"], turn)
    return JSONResponse({"ok": True, "deleted": deleted})


# ---- 收藏笔记本 CRUD ----

async def api_list_bookmarks(request):
    return JSONResponse(db.list_bookmarks())


async def api_add_bookmark(request):
    body = await request.json()
    conv_id = str(body.get("conversation_id") or "")
    try:
        turn = int(body.get("turn", 0))
    except (TypeError, ValueError):
        turn = 0
    content = str(body.get("content") or "").strip()
    if not conv_id or turn < 1 or not content:
        return JSONResponse({"ok": False, "msg": "conversation_id / turn / content 无效"}, status_code=400)
    bm = db.add_bookmark(conv_id, turn, str(body.get("title", ""))[:60], content)
    return JSONResponse({"ok": True, "bookmark": bm})


async def api_update_bookmark(request):
    body = await request.json()
    ok = db.update_bookmark(
        request.path_params["bm_id"],
        note=body.get("note"),
        tags=body.get("tags"),
        title=body.get("title"),
    )
    return JSONResponse({"ok": ok})


async def api_delete_bookmark(request):
    ok = db.delete_bookmark(request.path_params["bm_id"])
    return JSONResponse({"ok": ok})


async def api_interact(request):
    """前端点选澄清选项后回传：唤醒 event_gen_ai 里阻塞的同一 SSE。"""
    body = await request.json()
    ok = interaction.resolve(str(body.get("interaction_id", "")), str(body.get("value", "")))
    return JSONResponse({"ok": ok})


async def api_download_export(request):
    """下载 export_report 落盘的报告文件（仅限 data/exports 直属文件名，防目录穿越）。"""
    from urllib.parse import unquote
    from src.tools import EXPORT_DIR
    safe = os.path.basename(unquote(request.path_params["filename"]))
    fp = EXPORT_DIR / safe
    if not safe or not fp.is_file():
        return JSONResponse({"ok": False, "msg": "文件不存在"}, status_code=404)
    return FileResponse(fp, filename=safe, media_type="text/markdown; charset=utf-8")


# 路由在前、静态 mount 在后，避免 /chat 被静态拦截
routes = [
    Route("/chat", chat, methods=["POST"]),
    Route("/chat-ai", chat_ai, methods=["POST"]),
    Route("/api/conversations", api_list_conversations, methods=["GET"]),
    Route("/api/conversations", api_create_conversation, methods=["POST"]),
    Route("/api/conversations/{conv_id}", api_rename_conversation, methods=["PATCH"]),
    Route("/api/conversations/{conv_id}", api_delete_conversation, methods=["DELETE"]),
    Route("/api/conversations/{conv_id}/messages", api_list_messages, methods=["GET"]),
    Route("/api/conversations/{conv_id}/truncate", api_truncate_conversation, methods=["POST"]),
    Route("/api/bookmarks", api_list_bookmarks, methods=["GET"]),
    Route("/api/bookmarks", api_add_bookmark, methods=["POST"]),
    Route("/api/bookmarks/{bm_id}", api_update_bookmark, methods=["PATCH"]),
    Route("/api/bookmarks/{bm_id}", api_delete_bookmark, methods=["DELETE"]),
    Route("/api/interact", api_interact, methods=["POST"]),
    Route("/api/exports/{filename}", api_download_export, methods=["GET"]),
    Mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static"),
]
app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
