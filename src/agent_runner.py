"""Agent 运行：用 RAGMiddleware 把知识库接入 Agent。

mode="agentic"：暴露一个 search_knowledge 工具，模型在回答前自主决定
是否检索、用什么 query——这就是「检索作为工具、ReAct 触发」的官方实现。
"""
from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.event import EventType
from agentscope.message import UserMsg
from agentscope.middleware import RAGMiddleware
from agentscope.model import OpenAIChatModel
from agentscope.rag import KnowledgeBase
from agentscope.permission import PermissionMode
from agentscope.tool import FunctionTool, Toolkit

from src import config
from src.prompts import build_prompt
from src.tools import compute_salary, compute_rent


def make_chat_model() -> OpenAIChatModel:
    """构造对话模型（已确认：base_url 放 OpenAICredential）。"""
    credential = OpenAICredential(api_key=config.API_KEY, base_url=config.BASE_URL)
    return OpenAIChatModel(
        credential=credential,
        model=config.CHAT_MODEL,
        stream=True,
    )


async def build_rag_agent(knowledge: KnowledgeBase, mode: str | None = None) -> Agent:
    """把已建好的知识库通过 RAGMiddleware(agentic) 接入 Agent。

    Args:
        knowledge: 已建好的知识库。
        mode: 回答模式（brief/standard/report），None 时用 config.REPLY_MODE。
    """
    chat_model = make_chat_model()

    rag_mw = RAGMiddleware(
        knowledge_bases=[knowledge],
        parameters=RAGMiddleware.Parameters(mode="agentic", top_k=3),
    )

    # agentic 模式必须手动把 search_knowledge 工具注入 Toolkit
    # 自定义计算工具用 FunctionTool 包装（本版本无 @tool 装饰器）
    rag_tools = await rag_mw.list_tools()
    toolkit = Toolkit(tools=[FunctionTool(compute_salary), FunctionTool(compute_rent), *rag_tools])

    agent = Agent(
        name="rag-agent",
        # 提示词体系：L1 角色规则 + L2 检索规范 + L3[回答模式] 风格模板
        system_prompt=build_prompt(config.CITY, mode or config.REPLY_MODE),
        model=chat_model,
        toolkit=toolkit,
        middlewares=[rag_mw],
    )
    # 本项目的工具都是安全的纯计算/检索，跳过权限确认（BYPASS）。
    # 否则工具调用会发出 RequireUserConfirmEvent 等待人工批准，流程卡住无最终回答。
    agent.state.permission_context.mode = PermissionMode.BYPASS
    return agent


async def run_rag_agent(knowledge: KnowledgeBase, question: str, mode: str | None = None) -> None:
    """建 Agent 并流式回答一个问题。

    Args:
        knowledge: 已建好的知识库。
        question: 用户问题。
        mode: 回答模式，None 时用 config.REPLY_MODE。
    """
    agent = await build_rag_agent(knowledge, mode)
    user_msg = UserMsg(name="user", content=question)

    print("\n[RAG Agent 回答]", end="", flush=True)
    async for event in agent.reply_stream(user_msg):
        if event.type == EventType.TEXT_BLOCK_DELTA:
            print(event.delta, end="", flush=True)
        elif event.type == EventType.TOOL_CALL_START:
            print(f"\n[调用工具] {event.tool_call_name}", flush=True)
    print("\n")


async def demo_search(knowledge: KnowledgeBase) -> None:
    """直接检索演示（不走 Agent，先看原始检索效果）。"""
    print("\n===== 向量检索 =====")
    results = await knowledge.search(queries=["上海 社保 个人 缴费 比例"], top_k=2)
    for r in results:
        content = r.chunk.content
        text = content.text if hasattr(content, "text") else str(content)
        print(f"  score={r.score:.4f} | {text[:60]}")

    print("\n===== 文档管理 =====")
    for s in await knowledge.list_documents():
        print(f"  {s.document_id} | {s.source} | chunks={s.chunk_count}")
