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
    Mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static"),
]
app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
