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
            CREATE TABLE IF NOT EXISTS bookmarks (
                id              TEXT PRIMARY KEY,
                user_id         TEXT NOT NULL DEFAULT 'default',
                conversation_id TEXT NOT NULL,
                turn            INTEGER NOT NULL,          -- 会话内第几轮 user 消息（与轮次导航条同一口径）
                title           TEXT NOT NULL DEFAULT '',  -- 收藏时的问题（自动摘要）
                content         TEXT NOT NULL DEFAULT '',  -- 被收藏的回答全文
                note            TEXT NOT NULL DEFAULT '',  -- 用户备注
                tags            TEXT NOT NULL DEFAULT '',  -- 逗号分隔标签
                created_at      INTEGER NOT NULL,
                updated_at      INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bm_user ON bookmarks(user_id, updated_at DESC);
            """
        )
        # 迁移：为旧库补 duration_ms 列（assistant 消息的回答生成耗时，落库供历史回看）
        cols = {r["name"] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
        if "duration_ms" not in cols:
            c.execute("ALTER TABLE messages ADD COLUMN duration_ms INTEGER")
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
    """首条消息后自动把会话标题设为问题截断（仅当仍为默认「新会话」时）。"""
    c = _conn()
    try:
        c.execute(
            "UPDATE conversations SET title=? WHERE id=? AND title='新会话'",
            (title, conv_id),
        )
        c.commit()
    finally:
        c.close()


def set_conversation_summary_title(
    conv_id: str, title: str, expect_current: str, user_id: str = DEFAULT_USER
) -> bool:
    """写入 AI 总结标题：覆盖占位标题（原始问题截断）。

    仅当当前标题仍是默认「新会话」或等于占位问题（expect_current）时才更新，
    从而不会覆盖用户在后台生成期间的手动改名。"""
    c = _conn()
    try:
        cur = c.execute(
            "UPDATE conversations SET title=? WHERE id=? AND user_id=? AND title IN ('新会话', ?)",
            (title, conv_id, user_id, expect_current),
        )
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


# ---- messages ----

def add_message(
    conv_id: str,
    role: str,
    parts: list,
    mode: str | None = None,
    user_id: str = DEFAULT_USER,
    duration_ms: int | None = None,
) -> dict:
    """落一条消息。parts 是 AI SDK parts 数组（list[dict]）。

    duration_ms：assistant 消息的回答生成耗时（毫秒），user 消息留空。
    """
    import json

    now = _now()
    mid = _new_id()
    c = _conn()
    try:
        c.execute(
            "INSERT INTO messages (id, conversation_id, user_id, role, parts_json, mode, created_at, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, conv_id, user_id, role, json.dumps(parts, ensure_ascii=False), mode, now, duration_ms),
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
            "SELECT * FROM messages WHERE conversation_id=? AND user_id=? ORDER BY created_at ASC, rowid ASC",
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


def truncate_from_turn(conv_id: str, turn: int, user_id: str = DEFAULT_USER) -> int:
    """丢弃第 turn 条 user 消息及其后的全部消息（分支重生成：截断旧链）。

    轮次按插入顺序（rowid）数，与前端展示顺序一致。返回删除条数。
    """
    c = _conn()
    try:
        rows = c.execute(
            "SELECT id, role FROM messages WHERE conversation_id=? AND user_id=? ORDER BY rowid ASC",
            (conv_id, user_id),
        ).fetchall()
        n, target = 0, None
        for r in rows:
            if r["role"] == "user":
                n += 1
                if n == turn:
                    target = r["id"]
                    break
        if target is None:
            return 0
        cur = c.execute(
            "DELETE FROM messages WHERE conversation_id=? AND rowid >= "
            "(SELECT rowid FROM messages WHERE id=?)",
            (conv_id, target),
        )
        c.commit()
        return cur.rowcount
    finally:
        c.close()


# ---- bookmarks（收藏笔记本）----

def add_bookmark(
    conv_id: str,
    turn: int,
    title: str,
    content: str,
    user_id: str = DEFAULT_USER,
) -> dict:
    """收藏一条回答；同一会话同一轮已存在则更新内容（幂等）。"""
    now = _now()
    c = _conn()
    try:
        row = c.execute(
            "SELECT id FROM bookmarks WHERE user_id=? AND conversation_id=? AND turn=?",
            (user_id, conv_id, turn),
        ).fetchone()
        if row:
            c.execute(
                "UPDATE bookmarks SET title=?, content=?, updated_at=? WHERE id=?",
                (title, content, now, row["id"]),
            )
            c.commit()
            return get_bookmark(row["id"], user_id)
        bid = _new_id()
        c.execute(
            "INSERT INTO bookmarks (id, user_id, conversation_id, turn, title, content, note, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, '', '', ?, ?)",
            (bid, user_id, conv_id, turn, title, content, now, now),
        )
        c.commit()
        return get_bookmark(bid, user_id)
    finally:
        c.close()


def get_bookmark(bid: str, user_id: str = DEFAULT_USER) -> dict | None:
    c = _conn()
    try:
        row = c.execute(
            "SELECT * FROM bookmarks WHERE id=? AND user_id=?", (bid, user_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        c.close()


def list_bookmarks(user_id: str = DEFAULT_USER) -> list[dict]:
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM bookmarks WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def update_bookmark(
    bid: str,
    note: str | None = None,
    tags: str | None = None,
    title: str | None = None,
    user_id: str = DEFAULT_USER,
) -> bool:
    """只更新传入的字段（备注/标签/标题）。"""
    sets, vals = [], []
    for col, v in (("note", note), ("tags", tags), ("title", title)):
        if v is not None:
            sets.append(f"{col}=?")
            vals.append(v)
    if not sets:
        return False
    sets.append("updated_at=?")
    vals.append(_now())
    c = _conn()
    try:
        cur = c.execute(
            f"UPDATE bookmarks SET {', '.join(sets)} WHERE id=? AND user_id=?",
            vals + [bid, user_id],
        )
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def delete_bookmark(bid: str, user_id: str = DEFAULT_USER) -> bool:
    c = _conn()
    try:
        cur = c.execute("DELETE FROM bookmarks WHERE id=? AND user_id=?", (bid, user_id))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()
