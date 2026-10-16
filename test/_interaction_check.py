"""阶段一交互总线单测：resolve 唤醒 await_choice、超时降级、args 命中同一 Future。

运行：D:\\LRWork\\...\\.venv\\Scripts\\python.exe test/_interaction_check.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import interaction  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


async def test_resolve_wakes():
    """event_gen_ai 侧 begin_choice 注册，工具侧 await_choice 命中同一 Future，resolve 唤醒。"""
    q, opts = "请选择贷款类型", "商贷,公积金,组合贷"
    iid, fut = interaction.begin_choice(q, opts)
    check("begin_choice 返回 id 且 Future 未完成", fut is not None and not fut.done())

    # 模拟工具侧 await_choice：应命中 event_gen_ai 注册的同一 Future（靠 args_hash）
    task = asyncio.create_task(interaction.await_choice(q, opts, timeout=5))
    await asyncio.sleep(0.01)  # 让 await_choice 进入等待
    ok = interaction.resolve(iid, "组合贷")
    check("resolve 命中未完成交互返回 True", ok is True)

    result = await task
    check("await_choice 返回用户所选值", result == "组合贷")
    check("交互完成后登记表已清空", iid not in interaction._pending)


async def test_timeout_degrade():
    """无人点选 → 超时返回引导降级串，不无限挂起。"""
    # 先以同一 args 注册，再让 await_choice 命中它并在超时时清理
    iid, fut = interaction.begin_choice("超时问题", "A,B")
    result = await interaction.await_choice("超时问题", "A,B", timeout=0.1)
    check("超时返回引导假设语", "时限" in result or "假设" in result)
    check("超时后登记表清空", iid not in interaction._pending)


async def test_resolve_miss():
    """resolve 未知/已完成 id 返回 False（历史重复回传等）。"""
    check("未知 id resolve 返回 False", interaction.resolve("nonexistent", "x") is False)
    iid, fut = interaction.begin_choice("完成态", "A")
    interaction.resolve(iid, "A")
    check("重复 resolve 返回 False", interaction.resolve(iid, "B") is False)
    interaction._pending.pop(iid, None)


async def test_parse_options():
    check("英文逗号解析", interaction.parse_options("商贷,公积金,组合贷") == ["商贷", "公积金", "组合贷"])
    check("中文逗号/顿号兼容", interaction.parse_options("商贷，公积金、组合贷") == ["商贷", "公积金", "组合贷"])
    check("空白项过滤", interaction.parse_options(" A , ,B, ") == ["A", "B"])


async def main():
    await test_resolve_wakes()
    await test_timeout_degrade()
    await test_resolve_miss()
    await test_parse_options()
    print(f"\n结果：PASS={PASS} FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
