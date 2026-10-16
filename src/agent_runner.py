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
from agentscope.permission import PermissionMode, PermissionRule, PermissionBehavior
from agentscope.tool import FunctionTool, Toolkit

from src import config
from src.prompts import build_prompt
from src.tools import compute_salary, compute_rent, compute_commute, compute_mortgage, compute_cost_index, ask_user, export_report


def make_chat_model() -> OpenAIChatModel:
    """构造对话模型（已确认：base_url 放 OpenAICredential）。"""
    credential = OpenAICredential(api_key=config.API_KEY, base_url=config.BASE_URL)
    return OpenAIChatModel(
        credential=credential,
        model=config.CHAT_MODEL,
        stream=True,
    )


async def build_rag_agent(knowledge: KnowledgeBase, mode: str | None = None,
                          require_approval: bool = False) -> Agent:
    """把已建好的知识库通过 RAGMiddleware(agentic) 接入 Agent。

    Args:
        knowledge: 已建好的知识库。
        mode: 回答模式（brief/standard/report），None 时用 config.REPLY_MODE。
        require_approval: 为 True 时启用工具审批 HITL（副作用类工具执行前需用户确认）；
            为 False 时保持 BYPASS（工具自动放行，即现状）。
    """
    chat_model = make_chat_model()

    rag_mw = RAGMiddleware(
        knowledge_bases=[knowledge],
        parameters=RAGMiddleware.Parameters(mode="agentic", top_k=3),
    )

    # agentic 模式必须手动把 search_knowledge 工具注入 Toolkit
    # 自定义计算工具用 FunctionTool 包装（本版本无 @tool 装饰器）
    rag_tools = await rag_mw.list_tools()
    toolkit = Toolkit(
        tools=[
            FunctionTool(compute_salary),
            FunctionTool(compute_rent),
            FunctionTool(compute_commute),
            FunctionTool(compute_mortgage),
            FunctionTool(compute_cost_index),
            FunctionTool(ask_user),
            FunctionTool(export_report),
            *rag_tools,
        ]
    )

    agent = Agent(
        name="rag-agent",
        # 提示词体系：L1 角色规则 + L2 检索规范 + L3[回答模式] 风格模板
        system_prompt=build_prompt(config.CITY, mode or config.REPLY_MODE),
        model=chat_model,
        toolkit=toolkit,
        middlewares=[rag_mw],
    )
    # 权限链路：默认全部工具自动放行（BYPASS），因为本项目工具多为安全纯计/检索。
    # 否则工具调用会发出 RequireUserConfirmEvent 等待人工批准，流程卡住无最终回答。
    ctx = agent.state.permission_context
    if require_approval:
        # 审阅模式：对“行动类”工具（真正产出测算/未来的写文件导出）要求确认。
        # ask_rules 在 DEFAULT 引擎里优先于只读快路（Step2），能稳定触发确认卡片；
        # search_knowledge / ask_user 则加 allow_rules 自动放行，避免无谓弹窗。
        ctx.mode = PermissionMode.DEFAULT
        action_tools = [
            "compute_salary", "compute_rent", "compute_commute",
            "compute_mortgage", "compute_cost_index", "export_report",
        ]
        pass_tools = ["search_knowledge", "ask_user"]
        ctx.ask_rules = {
            t: [PermissionRule(tool_name=t, rule_content=None,
                               behavior=PermissionBehavior.ASK, source="session")]
            for t in action_tools
        }
        ctx.allow_rules = {
            t: [PermissionRule(tool_name=t, rule_content=None,
                               behavior=PermissionBehavior.ALLOW, source="session")]
            for t in pass_tools
        }
    else:
        ctx.mode = PermissionMode.BYPASS
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
