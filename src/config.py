"""读取 .env 配置（统一从这里拿，避免散落各处）。"""
import os

from dotenv import load_dotenv

load_dotenv()

# API Key（阿里云百炼 MaaS）
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# OpenAI 兼容端点 base_url
BASE_URL = os.getenv("BASE_URL", "")

# 对话模型名
CHAT_MODEL = os.getenv("MODEL", "qwen3.8-max")

# Embedding 模型名与维度
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-v3")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))

# 目标城市（决定读取 data/docs/{CITY}/ 下的语料）
CITY = os.getenv("CITY", "上海")

# 回答模式：brief / standard / report（见 src/prompts.py，可被 --mode 覆盖）
REPLY_MODE = os.getenv("REPLY_MODE", "standard")

# ---- 可观测性配置（见 src/observability.py）----
# 项目根目录（src/ 的上一级），用于拼日志默认路径
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 日志级别（DEBUG/INFO/WARNING/ERROR）与落盘目录（默认 data/logs，随 .gitignore 的 data/ 不入库）
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", os.path.join(_ROOT, "data", "logs"))

# token 单价（每 1K token，用于把 MODEL_CALL_END 的用量折算成本）。默认 0 表示「未配置单价」，
# 此时成本记为 None（不凭空编造金额）；需要成本统计时在 .env 填这两项。
PRICE_IN_PER_1K = float(os.getenv("PRICE_IN_PER_1K", "0") or 0)
PRICE_OUT_PER_1K = float(os.getenv("PRICE_OUT_PER_1K", "0") or 0)

# ---- 安全与防护配置（P1）----
# 单次问题长度上限（字符）：防止误贴/故意塞超长文本烧 token（配合成本计量）。<=0 表示不限。
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "2000") or 0)

# 模型调用重试（AgentScope 内建，默认 3 次重试 + 固定间隔退避；此处做成可配）
MODEL_MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "3") or 3)
MODEL_RETRY_DELAY = float(os.getenv("MODEL_RETRY_DELAY", "1.0") or 1.0)

# ---- 身份与访问控制（P1·每人一个访问令牌）----
# AGENT_TOKENS=user_id:token,user_id:token （逗号分隔；user_id 用于数据隔离，token 是访问凭证）。
# 留空则鉴权关闭（本地自用零摩擦，所有人归为 default）。配置后所有 /api 与推理端点需携令牌。
def _parse_agent_tokens(raw: str) -> dict:
    """把 'uid:token,uid:token' 解析为 {token: user_id}。非法片段静默丢弃。"""
    m: dict[str, str] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        uid, tok = pair.split(":", 1)
        uid, tok = uid.strip(), tok.strip()
        if uid and tok:
            m[tok] = uid
    return m


AGENT_TOKEN_MAP = _parse_agent_tokens(os.getenv("AGENT_TOKENS", ""))
AUTH_ENABLED = bool(AGENT_TOKEN_MAP)
