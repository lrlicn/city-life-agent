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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel

from agentscope.event import EventType
from agentscope.message import UserMsg

from src.rag_build import build_knowledge_base
from src.agent_runner import build_rag_agent

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
    """单轮问答请求体。mode 缺省用 .env 的 REPLY_MODE。"""
    question: str
    mode: str | None = None


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


async def event_gen_ai(req: ChatRequest):
    """AI SDK 5 Data Stream 协议（SSE）：供前端 @ai-sdk/vue 的 useChat 消费。

    完整翻译 Agent 事件：
      TOOL_CALL_START/DELTA/END → tool-input-start / -delta / -available（含真实参数）
      TOOL_RESULT_TEXT_DELTA/END → tool-output-available（含真实结果）
      额外：compute_salary 执行完后发 data-salary part，前端据此画生成式 UI 图表。
    """
    try:
        kb = await get_kb()
        agent = await build_rag_agent(kb, req.mode)
        user_msg = UserMsg(name="user", content=req.question)
        yield 'data: {"type":"start","messageId":"msg_1"}\n\n'
        text_id = "text_1"
        text_started = False
        tool_names: dict[str, str] = {}   # tool_call_id -> 工具名
        tool_args: dict[str, str] = {}    # tool_call_id -> 累积的参数 JSON 片段
        tool_outputs: dict[str, str] = {}  # tool_call_id -> 累积的结果文本
        async for event in agent.reply_stream(user_msg):
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
            elif event.type == EventType.TOOL_RESULT_TEXT_DELTA:
                if event.tool_call_id in tool_outputs:
                    tool_outputs[event.tool_call_id] += event.delta
            elif event.type == EventType.TOOL_RESULT_END:
                tcid = event.tool_call_id
                name = tool_names.get(tcid, "")
                output = tool_outputs.get(tcid, "")
                yield f"data: {json.dumps({'type': 'tool-output-available', 'toolCallId': tcid, 'toolName': name, 'output': output}, ensure_ascii=False)}\n\n"
                # 生成式 UI：compute_salary → data-salary part（前端据此画图）
                if name == "compute_salary" and output:
                    parsed = _parse_salary_output(output)
                    if parsed:
                        inp = _parse_tool_input(tool_args.get(tcid, ""))
                        if inp.get("city"):
                            parsed["city"] = inp.get("city")
                        if inp.get("monthly_salary") is not None:
                            parsed["monthly_salary"] = inp.get("monthly_salary")
                        yield f"data: {json.dumps({'type': 'data-salary', 'data': parsed}, ensure_ascii=False)}\n\n"
            elif event.type == EventType.TEXT_BLOCK_DELTA:
                if not text_started:
                    yield f"data: {json.dumps({'type': 'text-start', 'id': text_id}, ensure_ascii=False)}\n\n"
                    text_started = True
                yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': event.delta}, ensure_ascii=False)}\n\n"
        if text_started:
            yield f"data: {json.dumps({'type': 'text-end', 'id': text_id}, ensure_ascii=False)}\n\n"
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'type': 'error', 'errorText': str(e)}, ensure_ascii=False)}\n\n"
    yield 'data: {"type":"finish"}\n\n'
    yield "data: [DONE]\n\n"


async def chat_ai(request):
    """AI SDK useChat 入口：请求体为 {messages:[{role, content|parts}], mode?}。

    从最后一条 user 消息提取 question；mode 可选，缺省用 .env 的 REPLY_MODE。
    """
    body = await request.json()
    req = ChatRequest(question="", mode=body.get("mode"))
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


# 路由在前、静态 mount 在后，避免 /chat 被静态拦截
routes = [
    Route("/chat", chat, methods=["POST"]),
    Route("/chat-ai", chat_ai, methods=["POST"]),
    Mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static"),
]
app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
