"""可观测性：结构化日志 + 请求级上下文（trace_id / conv_id）+ token 成本折算。

设计目标（务实、不引重型组件）：
- 每条日志是**一行 JSON**，落到 data/logs/app.log（带轮转），便于事后 grep / jq 过滤；
  同时保留一份人类可读行到控制台（CLI 与本地起服务时都能看到）。
- 一次问答绑定一个 trace_id，贯穿该请求所有日志行；会话 id 也自动带上，
  于是「按 trace_id 过滤」≈ 穷人版链路追踪，能定位一次回答卡在哪个环节。
- token 用量来自 Agent 的 MODEL_CALL_END 事件（input/output tokens）；成本按 .env 单价折算，
  未配置单价则成本记 None（不凭空编造金额）。

不引入 Prometheus/Grafana/OTel——个人产品用「结构化日志 + 用量入库」即可满足可观测性起步需求。
"""
import json
import logging
import os
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler

from src import config

# 请求级上下文：在 event_gen_ai 开头 bind，之后该请求内每条日志自动带上这两个字段。
# 用 contextvar 而非显式传参，避免污染每个函数签名；单事件循环内并发请求互不串台。
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_conv_id: ContextVar[str] = ContextVar("conv_id", default="-")

LOG = logging.getLogger("city-life-agent")

_configured = False


def bind_context(trace_id: str | None = None, conv_id: str | None = None) -> None:
    """绑定当前请求的 trace_id / conv_id（None 表示不改动该项）。"""
    if trace_id is not None:
        _trace_id.set(trace_id)
    if conv_id is not None:
        _conv_id.set(conv_id)


def get_trace_id() -> str:
    return _trace_id.get()


class _JsonFormatter(logging.Formatter):
    """把 LogRecord 渲染成一行 JSON；trace_id/conv_id 缺省取当前上下文，自定义字段放进 fields。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "trace_id": getattr(record, "trace_id", None) or _trace_id.get(),
            "conv_id": getattr(record, "conv_id", None) or _conv_id.get(),
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str | None = None) -> logging.Logger:
    """初始化日志（幂等）。文件写 JSON 行 + 轮转；控制台写人类可读行。"""
    global _configured
    if _configured:
        return LOG
    LOG.setLevel(getattr(logging, (level or config.LOG_LEVEL).upper(), logging.INFO))
    LOG.propagate = False

    # 文件：JSON 行，2MB × 5 份轮转
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(config.LOG_DIR, "app.log"),
            maxBytes=2_000_000, backupCount=5, encoding="utf-8",
        )
        fh.setFormatter(_JsonFormatter())
        LOG.addHandler(fh)
    except OSError:
        # 目录不可写时不阻断启动，仅保留控制台
        pass

    # 控制台：简短可读
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    LOG.addHandler(ch)

    _configured = True
    return LOG


def log_event(event: str, level: str = "info", msg: str | None = None, **fields) -> None:
    """记录一条结构化事件日志（info/warning/error 等）。fields 会并入同一行 JSON。

    event 是机器可查的事件名；msg 是供控制台人类可读的行（缺省用 event）。
    惰性初始化：未 setup 时自动 setup（幂等、开销极小），保证任意入口（服务/CLI）都能落日志。
    """
    setup_logging()
    LOG.log(
        getattr(logging, level.upper(), logging.INFO),
        msg or event,
        extra={"event": event, "fields": fields},
    )


def log_exception(event: str, exc: BaseException, **fields) -> None:
    """记录一条带堆栈的错误日志（原始异常只进日志，不外泄给前端）。"""
    setup_logging()
    LOG.error(event, exc_info=exc, extra={"event": event, "fields": fields})


def estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    """按 .env 单价折算本轮成本；单价未配置（两项都为 0）时返回 None，不编造金额。"""
    if not config.PRICE_IN_PER_1K and not config.PRICE_OUT_PER_1K:
        return None
    cost = (input_tokens / 1000.0) * config.PRICE_IN_PER_1K + (output_tokens / 1000.0) * config.PRICE_OUT_PER_1K
    return round(cost, 6)
