"""程序入口：建库 → 检索演示 → Agent 问答。

运行（在项目根目录，venv 已激活）：
    python scripts/main.py                          # 默认 standard 模式
    python scripts/main.py --mode report            # 强制报告模式
    python scripts/main.py --mode brief             # 简洁模式
    python scripts/main.py --ask "北京月薪 3 万到手多少？写份报告"   # 自定义问题 + 自然语言识别
"""
import argparse
import asyncio
import os
import sys

# 让 import src.* 生效（脚本从 scripts/ 运行时 cwd 是项目根）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.agent_runner import demo_search, run_rag_agent
from src.prompts import REPLY_MODES, detect_mode_from_question
from src.rag_build import build_knowledge_base


async def main(question: str, mode: str, rebuild: bool = False) -> None:
    # 1. 建库（解析 → 切块 → 入库；默认幂等跳过已入库，rebuild=True 先清空重建）
    print("===== 建库 =====")
    knowledge, store = await build_knowledge_base(rebuild=rebuild)

    try:
        if rebuild:
            # 仅重建：打印当前文档清单后退出，不跑 Agent
            print("\n===== 重建完成，当前集合文档 =====")
            for s in await knowledge.list_documents():
                print(f"  {s.source} | chunks={s.chunk_count}")
            return

        # 2. 原始检索演示
        await demo_search(knowledge)

        # 3. Agent 增强问答（ReAct 触发检索）
        await run_rag_agent(knowledge, question, mode)
    finally:
        # 4. 关闭向量库连接
        await store.__aexit__(None, None, None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="城事小灵通智能体（RAG + ReAct Agent）")
    parser.add_argument(
        "--mode",
        choices=REPLY_MODES,
        help="回答模式 brief/standard/report（覆盖 .env 的 REPLY_MODE）",
    )
    parser.add_argument(
        "--ask",
        default=f"我在{config.CITY}月薪 2 万，到手能拿多少？",
        help="自定义问题（可含「写份报告/简单说」等自然语言触发）",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="清空并重建知识库（清除历史重复副本 / 源文档变更后强制刷新）",
    )
    args = parser.parse_args()

    # 回答模式优先级：命令行 --mode > 问题自然语言识别 > .env 默认
    detected = detect_mode_from_question(args.ask)
    mode = args.mode or detected or config.REPLY_MODE
    if detected and not args.mode:
        print(f"[模式] 从问题识别为「{detected}」")

    asyncio.run(main(args.ask, mode, rebuild=args.rebuild))
