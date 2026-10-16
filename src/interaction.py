"""进程内交互总线：让流式回答"中途暂停 → 等用户点选 → 恢复同一条 SSE"。

机制（阶段一·澄清选择）：
1. event_gen_ai 发现模型调用 ask_user 工具时，begin_choice(question, options) 注册一个
   Future，并下发 data-interaction part（含 interaction_id / 问题 / 选项）给前端；
2. ask_user 工具体 await_choice(question, options) 命中同一 Future 并阻塞等待——此时
   整条 SSE 停在"工具执行中"，前端已拿到选项可渲染；
3. 用户点选 → 前端 POST /api/interact → resolve(interaction_id, value) 唤醒 Future；
4. 工具返回用户所选调作为工具输出喂回模型，Agent 据此继续推理，SSE 不断流地续跑。

⚠️ 单进程假设：/api/interact 与 event_gen_ai 必须在同一进程（uvicorn 单 worker）。
   多 worker 部署需改为按 worker 粘连或外置信号通道（本学习项目不处理，文档标注）。
"""
import asyncio
import uuid

# interaction_id -> Future（result 为用户点选的字符串）
_pending: dict[str, asyncio.Future] = {}
# args_hash -> interaction_id：供 ask_user 工具命中 event_gen_ai 注册的同一 Future
_by_args: dict[str, str] = {}


def _args_hash(question: str, options: str) -> str:
    return f"{(question or '').strip()}|{(options or '').strip()}"


def parse_options(options: str) -> list[str]:
    """把逗号（兼容中英文逗号、顿号）分隔的选项串解析为列表。"""
    normalized = (options or "").replace("，", ",").replace("、", ",")
    return [o.strip() for o in normalized.split(",") if o.strip()]


def begin_choice(question: str, options: str) -> tuple[str, asyncio.Future]:
    """服务端登记一次待点选交互，返回 (interaction_id, future)。须在运行中的事件循环里调用。"""
    iid = uuid.uuid4().hex
    fut = asyncio.get_running_loop().create_future()
    _pending[iid] = fut
    _by_args[_args_hash(question, options)] = iid
    return iid, fut


async def await_choice(question: str, options: str, timeout: float = 600) -> str:
    """ask_user 工具侧：阻塞等待用户点选，返回其选择文本。

    命中 event_gen_ai 预注册的 Future；命中不到（异常路径）则自注册再等待。
    超时/取消时返回引导语，让 Agent 基于常见情形合理假设并说明，不无限挂起。
    """
    key = _args_hash(question, options)
    iid = _by_args.get(key)
    fut = _pending.get(iid) if iid is not None else None
    if fut is None:
        iid, fut = begin_choice(question, options)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return "（用户未在时限内作答，请基于最常见情形做合理假设，并在回答里说明这一假设）"
    finally:
        _pending.pop(iid, None)
        _by_args.pop(key, None)


def resolve(interaction_id: str, value: str) -> bool:
    """前端点选后由 /api/interact 调用：唤醒对应 Future。返回是否命中未完成交互。"""
    fut = _pending.get(interaction_id)
    if fut is None or fut.done():
        return False
    fut.set_result(value)
    return True


# ---- 阶段二·工具审批（confirm）复用同一总线，但不走 args_hash ----
# confirm 的登记与等待都发生在 event_gen_ai 内部（工具尚未执行），
# 因此只需一个纯 interaction_id 索引的 Future，无需 ask_user 那种跨注册命中。


def register() -> tuple[str, asyncio.Future]:
    """登记一次待审批交互，返回 (interaction_id, future)。须在运行中的事件循环里调用。"""
    iid = uuid.uuid4().hex
    fut = asyncio.get_running_loop().create_future()
    _pending[iid] = fut
    return iid, fut


async def wait_result(iid: str, fut: asyncio.Future, timeout: float = 600) -> str | None:
    """等待用户审批决策。返回 'approve' / 'deny'；超时（无人响应）返回 None。

    调用方（event_gen_ai）据 None 走安全默认：拒绝执行副作用工具。
    """
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        _pending.pop(iid, None)
