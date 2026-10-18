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
import uuid
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.applications import Starlette
from starlette.responses import StreamingResponse, JSONResponse, FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.datastructures import Headers
from pydantic import BaseModel

from agentscope.event import EventType, UserConfirmResultEvent, ConfirmResult
from agentscope.message import UserMsg, AssistantMsg

from src.rag_build import build_knowledge_base
from src.agent_runner import build_rag_agent
from src import db, config, interaction, observability
from openai import OpenAI

# 启动即建表（幂等）+ 初始化结构化日志


db.init_db()
observability.setup_logging()

# 轻量客户端：用于异步生成会话标题
_title_client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)

async def generate_title_async(conv_id: str, question: str, user_id: str = "default"):
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
                db.set_conversation_summary_title(conv_id, title[:30], question[:30], user_id=user_id)
        except Exception as e:
            observability.log_exception("title.gen_failed", e, conv_id=conv_id)
    await asyncio.to_thread(_gen)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ---- 身份与访问控制（P1·每人一个访问令牌）----
# 受保护前缀：数据端点 /api/*（含 /api/exports 下载）与推理端点 /chat、/chat-ai。
# 静态首页/资源不拦（由 index.html 加载后，前端凭令牌调 /api，无令牌→401 弹门）。
_PROTECTED_PREFIXES = ("/api/", "/chat", "/chat-ai")


def _extract_token(headers: Headers, query_string: str) -> str:
    """依次从 Authorization: Bearer、x-agent-token 头、?t= 查询参数取令牌（导出链接用查询）。"""
    auth = (headers.get("authorization", "") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    tok = (headers.get("x-agent-token", "") or "").strip()
    if tok:
        return tok
    return (parse_qs(query_string).get("t") or [""])[0]


class AuthMiddleware:
    """纯 ASGI 中间件：对受保护路径校验访问令牌→解析 user_id 注入 scope.state。

    不用 BaseHTTPMiddleware，避免包裹响应体破坏 SSE 流式。config.AUTH_ENABLED=False 时全放行。
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not config.AUTH_ENABLED or not path.startswith(_PROTECTED_PREFIXES):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        token = _extract_token(headers, scope.get("query_string", "").decode())
        user_id = config.AGENT_TOKEN_MAP.get(token)
        if not user_id:
            resp = JSONResponse({"ok": False, "msg": "未授权：访问令牌缺失或无效"}, status_code=401)
            await resp(scope, receive, send)
            return
        scope.setdefault("state", {})["user_id"] = user_id
        await self.app(scope, receive, send)


def _uid(request) -> str:
    """当前请求的 user_id：鉴权开启时取中间件注入值，否则 default（本地自用）。"""
    return getattr(request.state, "user_id", None) or db.DEFAULT_USER

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
    user_id: str = db.DEFAULT_USER   # 鉴权中间件解析后由 chat_ai 注入；会话/消息/导出按此隔离


async def event_gen(req: ChatRequest):
    """SSE 事件流：工具调用事件 + 文本 delta，逐条推给前端（简易端点，非主聊天链路）。"""
    try:
        observability.bind_context(trace_id=uuid.uuid4().hex[:12])
        kb = await get_kb()
        agent = await build_rag_agent(kb, req.mode)
        user_msg = UserMsg(name="user", content=req.question)
        async for event in agent.reply_stream(user_msg):
            if event.type == EventType.TOOL_CALL_START:
                yield f"data: {json.dumps({'type': 'tool', 'name': event.tool_call_name}, ensure_ascii=False)}\n\n"
            elif event.type == EventType.TEXT_BLOCK_DELTA:
                yield f"data: {json.dumps({'type': 'text', 'delta': event.delta}, ensure_ascii=False)}\n\n"
    except Exception as e:  # noqa: BLE001 —— 堆栈只进日志，前端只拿脱敏文案
        observability.log_exception("chat.error", e)
        yield f"data: {json.dumps({'type': 'error', 'msg': '服务暂时不可用，请稍后重试。'}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


def _parse_tool_input(raw: str) -> dict:
    """把工具参数 JSON 增量字符串解析成 dict，失败返回空（增量未凑齐/含非 JSON）。"""
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# 思考块里易泄漏的「元指令复读」行特征：命中即整行丢弃（提示词已约束，此为兼底）
_META_MARKERS = ("排版规范", "系统提示", "提示词", "全局规则", "按规则",
                 "元指令", "逐条检查", "格式要求", "回答风格", "知识库使用规范")

# 中文句末切分（保留标点），用于按句过滤元指令分句
_SENT_SPLIT = re.compile(r"(?<=[。！？；\n])")

# 内部工具函数名 → 中文（避免把 API 名录直接印到用户可见的思考里）
_REASON_TOOL_NAMES = {
    "compute_salary": "薪资测算",
    "compute_rent": "租房测算",
    "compute_commute": "通勤测算",
    "compute_mortgage": "房贷测算",
    "compute_cost_index": "生活成本测算",
    "search_knowledge": "检索知识库",
    "ask_user": "向用户澄清",
    "export_report": "导出报告",
}


def _clean_reasoning(text: str) -> str:
    """过滤思考文本：按句删除明显在复述系统规则/排版元指令的分句（不误伤同句实质内容），
    并把内部函数名换成中文。"""
    if not text:
        return ""
    out_lines = []
    for line in text.splitlines():
        if not line.strip():
            out_lines.append(line)
            continue
        # 按中文句末标点切句（保留标点），只丢弃命中元指令特征的分句
        parts = _SENT_SPLIT.split(line)
        kept = [p for p in parts if not any(mk in p for mk in _META_MARKERS)]
        out_lines.append("".join(kept))
    out = "\n".join(out_lines)
    # 函数名 → 中文（长名先替换，避免 compute_salary 被 compute_ 前缀干扰）
    for name in sorted(_REASON_TOOL_NAMES, key=len, reverse=True):
        out = out.replace(name, _REASON_TOOL_NAMES[name])
    # 压缩多余空行
    return re.sub(r"\n{3,}", "\n\n", out).strip()


async def event_gen_ai(req: ChatRequest):
    """AI SDK 5 Data Stream 协议（SSE）：供前端 @ai-sdk/vue 的 useChat 消费。

    完整翻译 Agent 事件：
      TOOL_CALL_START/DELTA/END → tool-input-start / -delta / -available（含真实参数）
      TOOL_RESULT_TEXT_DELTA/END → tool-output-available（含真实结果）
      额外：compute_salary 执行完后发 data-salary part，前端据此画生成式 UI 图表。
    """
    try:
        _t0 = time.monotonic()   # 回答生成耗时起点（含 RAG 检索 + Agent 全链路）
        trace_id = uuid.uuid4().hex[:12]   # 一次问答一个 trace_id，贯穿该请求所有日志行
        observability.bind_context(trace_id=trace_id)
        kb = await get_kb()
        agent = await build_rag_agent(kb, req.mode, require_approval=req.require_approval)
        # 多轮记忆：把该会话历史文本消息转成 Msg list 一并回喂（只取最近 20 条，控 token）
        history_msgs: list = []
        conv_id = req.conversation_id
        is_first_turn = not conv_id      # 新建会话首轮才做 AI 标题总结（避免每轮重写）
        # 新建会话首次发消息：立刻建会话+设标题，不等流式结束
        if not conv_id:
            cv = db.create_conversation(user_id=req.user_id)
            conv_id = cv["id"]
            db.set_conversation_title(conv_id, req.question[:30])
            # 标题只依赖问题：立刻后台并发生成，与回答流式同时进行。
            # 通常几秒内完成，远早于回答结束 → 前端可在生成期间就轮询到总结标题
            import asyncio
            asyncio.create_task(generate_title_async(conv_id, req.question, user_id=req.user_id))
        observability.bind_context(conv_id=conv_id)
        observability.log_event("chat.request", mode=req.mode, require_approval=req.require_approval,
                                q_len=len(req.question), first_turn=is_first_turn)
        if conv_id:
            for m in db.list_messages(conv_id, user_id=req.user_id)[-20:]:
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
                       [{"type": "text", "text": req.question}], mode=req.mode, user_id=req.user_id)
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
        tool_t0: dict[str, float] = {}   # tool_call_id -> 起始时间（分步耗时）
        reason_seq = 0                    # 思考块序号（每块独立 id，多块不合并）
        current_reason_id = ""            # 当前思考块的 reasoning part id
        reason_t0 = 0.0                   # 当前思考块起始时间
        tok_in = 0                        # 本轮累计输入 token（由 MODEL_CALL_END 汇总）
        tok_out = 0                       # 本轮累计输出 token
        while True:
            parked = None
            async for event in agent.reply_stream(inputs):
                if event.type == EventType.TOOL_CALL_START:
                    tool_names[event.tool_call_id] = event.tool_call_name
                    tool_args[event.tool_call_id] = ""
                    tool_outputs[event.tool_call_id] = ""
                    tool_t0[event.tool_call_id] = time.monotonic()
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
                        "ms": int((time.monotonic() - tool_t0.get(tcid, _t0)) * 1000),
                    })
                    # 生成式 UI：工具已把结构化数据放进 result.metadata.ui（见 src/tools.py），
                    # 后端直接读取并下发 data-{kind} part，不再对输出文本做正则解析（消除文案耦合）。
                    ui = (getattr(event, "metadata", None) or {}).get("ui")
                    if isinstance(ui, dict) and ui.get("kind") and ui.get("data") is not None:
                        part = {"type": f"data-{ui['kind']}", "data": ui["data"]}
                        yield f"data: {json.dumps(part, ensure_ascii=False)}\n\n"
                        stream_parts.append(part)
                        # 导出成功：记录文件归属（供 /api/exports 下载时校验属主）
                        if ui["kind"] == "export":
                            _fn = (ui["data"] or {}).get("filename")
                            if _fn:
                                db.record_export(_fn, user_id=req.user_id, conv_id=conv_id)
                    observability.log_event(
                        "tool.result", tool=name,
                        ms=int((time.monotonic() - tool_t0.get(tcid, _t0)) * 1000),
                        out_len=len(output), has_ui=isinstance(ui, dict) and bool(ui.get("kind")),
                    )
                elif event.type == EventType.THINKING_BLOCK_START:
                    # 先把正在累积的文本存起来，保持原始顺序
                    if current_text is not None and current_text["text"].strip():
                        stream_parts.append(current_text)
                        current_text = None
                    # 思考不再逐字实时下发（避免元指令泄漏）：块结束时清洗后整块呈现
                    reason_seq += 1
                    current_reason_id = f"reason_{reason_seq}"
                    reason_t0 = time.monotonic()
                    current_reasoning = {"type": "reasoning", "text": ""}
                elif event.type == EventType.THINKING_BLOCK_DELTA:
                    reasoning_text += event.delta
                    if current_reasoning is not None:
                        current_reasoning["text"] += event.delta
                elif event.type == EventType.THINKING_BLOCK_END:
                    cleaned = _clean_reasoning(current_reasoning["text"]) if current_reasoning else ""
                    dur_ms = int((time.monotonic() - reason_t0) * 1000) if reason_t0 else 0
                    if cleaned:
                        rid = current_reason_id or "reason_1"
                        yield f"data: {json.dumps({'type': 'reasoning-start', 'id': rid}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'reasoning-delta', 'id': rid, 'delta': cleaned}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'reasoning-end', 'id': rid}, ensure_ascii=False)}\n\n"
                        stream_parts.append({"type": "reasoning", "text": cleaned, "ms": dur_ms})
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
                elif event.type == EventType.MODEL_CALL_END:
                    # 模型每次调用结束携带 token 用量（input/output），累加为本轮总用量
                    tok_in += event.input_tokens or 0
                    tok_out += event.output_tokens or 0
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
            observability.log_event("tool.approval", decision=decision or "timeout",
                                    tools=[tc.name for tc in tcs])
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
            cost = observability.estimate_cost(tok_in, tok_out)
            db.add_message(conv_id, "assistant", stream_parts, mode=req.mode, duration_ms=elapsed_ms,
                           input_tokens=tok_in, output_tokens=tok_out, cost=cost, user_id=req.user_id)
            observability.log_event("chat.done", ms=elapsed_ms, input_tokens=tok_in,
                                    output_tokens=tok_out, cost=cost)
        db.touch_conversation(conv_id)
    except Exception as e:  # noqa: BLE001
        # 原始堆栈只进日志（带 trace_id/conv_id）；前端只收到脱敏语义标记，
        # 其 friendlyError 会把 internal 映射为「服务暂时不可用，请稍后重试。」
        observability.log_exception("chat.error", e)
        yield f"data: {json.dumps({'type': 'error', 'errorText': 'internal_error'}, ensure_ascii=False)}\n\n"
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
        user_id=_uid(request),
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
    # 输入长度硬护栏：防误贴/故意超长烧 token（前端 submit 会先拦，此为服务端子兵兼带防御）
    if config.MAX_INPUT_CHARS and len(req.question) > config.MAX_INPUT_CHARS:
        observability.log_event("chat.reject", reason="input_too_long", q_len=len(req.question))
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'errorText': 'input_too_long'}, ensure_ascii=False)}\n\n"]),
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
    rows = db.list_conversations(_uid(request))
    return JSONResponse(rows)


async def api_create_conversation(request):
    body = await request.json()
    cv = db.create_conversation(city=body.get("city"), user_id=_uid(request))
    return JSONResponse(cv)


async def api_rename_conversation(request):
    body = await request.json()
    title = str(body.get("title", "")).strip()[:40]
    if not title:
        return JSONResponse({"ok": False, "msg": "title 为空"}, status_code=400)
    ok = db.rename_conversation(request.path_params["conv_id"], title, user_id=_uid(request))
    return JSONResponse({"ok": ok})


async def api_delete_conversation(request):
    ok = db.delete_conversation(request.path_params["conv_id"], user_id=_uid(request))
    return JSONResponse({"ok": ok})


async def api_list_messages(request):
    msgs = db.list_messages(request.path_params["conv_id"], user_id=_uid(request))
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
    deleted = db.truncate_from_turn(request.path_params["conv_id"], turn, user_id=_uid(request))
    return JSONResponse({"ok": True, "deleted": deleted})


# ---- 收藏笔记本 CRUD ----

async def api_list_bookmarks(request):
    return JSONResponse(db.list_bookmarks(_uid(request)))


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
    bm = db.add_bookmark(conv_id, turn, str(body.get("title", ""))[:60], content, user_id=_uid(request))
    return JSONResponse({"ok": True, "bookmark": bm})


async def api_update_bookmark(request):
    body = await request.json()
    ok = db.update_bookmark(
        request.path_params["bm_id"],
        note=body.get("note"),
        tags=body.get("tags"),
        title=body.get("title"),
        user_id=_uid(request),
    )
    return JSONResponse({"ok": ok})


async def api_delete_bookmark(request):
    ok = db.delete_bookmark(request.path_params["bm_id"], user_id=_uid(request))
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
    # 归属校验：鉴权开启时仅属主可下载（未记录归属/非本人一律 404，不泄露存在性）
    if config.AUTH_ENABLED and db.get_export_owner(safe) != _uid(request):
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
app = AuthMiddleware(Starlette(routes=routes))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
