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
