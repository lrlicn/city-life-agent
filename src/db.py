"""会话与消息持久化（SQLite，单文件，随项目目录备份）。

设计要点（产品级、为多用户预留）：
- conversations / messages 均带 user_id 列，默认 'default'；未来多用户加鉴权后
  只需把 'default' 换成真实 user_id，表结构零迁移。
- messages.parts_json 原样存 AI SDK 的 parts 数组（text/reasoning/tool/data-*），
  切回旧会话时能完整还原工具卡片与图表，而不是只剩纯文本。
- DB 文件放 data/app.db（已在 .gitignore），WAL 模式支持并发读。
"""
import os
import sqlite3
import time
import uuid

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "app.db",
)

DEFAULT_USER = "default"


def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db() -> None:
    """建表（幂等）。进程启动时调用一次。"""
    c = _conn()
    try:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT '新会话',
                user_id     TEXT NOT NULL DEFAULT 'default',
                city        TEXT,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id         TEXT NOT NULL DEFAULT 'default',
                role            TEXT NOT NULL,           -- user / assistant
                parts_json      TEXT NOT NULL,           -- AI SDK parts 数组 JSON
                mode            TEXT,                    -- 当时的 brief/standard/report
                created_at      INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);
            """
        )
        c.commit()
    finally:
        c.close()


# ---- conversations ----

def create_conversation(city: str | None = None, user_id: str = DEFAULT_USER) -> dict:
    now = _now()
    cid = _new_id()
    c = _conn()
    try:
        c.execute(
            "INSERT INTO conversations (id, title, user_id, city, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, "新会话", user_id, city, now, now),
        )
        c.commit()
        return get_conversation(cid, user_id)
    finally:
        c.close()


def get_conversation(conv_id: str, user_id: str = DEFAULT_USER) -> dict | None:
    c = _conn()
    try:
        row = c.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?", (conv_id, user_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        c.close()


def list_conversations(user_id: str = DEFAULT_USER) -> list[dict]:
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def rename_conversation(conv_id: str, title: str, user_id: str = DEFAULT_USER) -> bool:
    c = _conn()
    try:
        cur = c.execute(
            "UPDATE conversations SET title=? WHERE id=? AND user_id=?",
            (title, conv_id, user_id),
        )
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def delete_conversation(conv_id: str, user_id: str = DEFAULT_USER) -> bool:
    c = _conn()
    try:
        cur = c.execute(
            "DELETE FROM conversations WHERE id=? AND user_id=?", (conv_id, user_id)
        )
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def touch_conversation(conv_id: str) -> None:
    """更新会话最近活跃时间（发消息时调用）。"""
    c = _conn()
    try:
        c.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conv_id)
        )
        c.commit()
    finally:
        c.close()


def set_conversation_title(conv_id: str, title: str) -> None:
    """首条消息后自动把会话标题设为问题截断。"""
    c = _conn()
    try:
        c.execute(
            "UPDATE conversations SET title=? WHERE id=? AND title='新会话'",
            (title, conv_id),
        )
        c.commit()
    finally:
        c.close()


# ---- messages ----

def add_message(
    conv_id: str,
    role: str,
    parts: list,
    mode: str | None = None,
    user_id: str = DEFAULT_USER,
) -> dict:
    """落一条消息。parts 是 AI SDK parts 数组（list[dict]）。"""
    import json

    now = _now()
    mid = _new_id()
    c = _conn()
    try:
        c.execute(
            "INSERT INTO messages (id, conversation_id, user_id, role, parts_json, mode, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, conv_id, user_id, role, json.dumps(parts, ensure_ascii=False), mode, now),
        )
        c.commit()
        return {"id": mid, "conversation_id": conv_id, "role": role, "created_at": now}
    finally:
        c.close()


def list_messages(conv_id: str, user_id: str = DEFAULT_USER) -> list[dict]:
    """拉某会话全部历史消息（按时间正序）。"""
    import json

    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM messages WHERE conversation_id=? AND user_id=? ORDER BY created_at ASC",
            (conv_id, user_id),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["parts"] = json.loads(d.pop("parts_json"))
            out.append(d)
        return out
    finally:
        c.close()
