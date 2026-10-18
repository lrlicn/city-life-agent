"""RAG 建库：① 解析 → ② 切块 → ③ 嵌入 + 入库。

走 AgentScope 官方全链路：
  TextParser          把文档读成 Section（自然边界）
  ApproxTokenChunker  按近似 token 切块 + 重叠（避免语义在边界被切断）
  OpenAIEmbeddingModel 把 Chunk 文本嵌入成向量
  QdrantStore         向量库（本地 path= 持久化，无需部署服务）
  KnowledgeBase       句柄：insert_document / search / list_documents / delete_document

注意：store 连接在这里打开后不关闭，由入口脚本（scripts/main.py）统一 __aexit__。
"""
import os
import hashlib
import time

from agentscope.credential import OpenAICredential
from agentscope.embedding import OpenAIEmbeddingModel
from agentscope.rag import ApproxTokenChunker, KnowledgeBase, QdrantStore, TextParser

from src import config, observability

# 知识文档目录（按城市分目录：data/docs/{CITY}/，把待检索的 .md/.txt 放这里）
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "docs", config.CITY,
)
# 向量库本地持久化目录
QDRANT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "qdrant_data",
)


def make_embedding_model() -> OpenAIEmbeddingModel:
    """构造 Embedding 模型（已确认：base_url 放 OpenAICredential）。"""
    credential = OpenAICredential(api_key=config.API_KEY, base_url=config.BASE_URL)
    return OpenAIEmbeddingModel(
        credential=credential,
        model=config.EMBED_MODEL,
        dimensions=config.EMBED_DIM,
    )


def _file_hash(path: str) -> str:
    """文件内容 sha256（取前 16 位）。用于变更检测：内容改了 hash 就变，与旧副本不一致。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()[:16]


async def build_knowledge_base(rebuild: bool = False) -> tuple[KnowledgeBase, QdrantStore]:
    """读取 data/docs/{CITY}/ 下所有文档，解析切块后入库，返回 (knowledge, store)。

    幂等（内容感知）：以向量库为单一事实源，每个文档的 document_metadata 里存了内容 content_hash。
      - 文件名存在且 hash 一致且无重复副本 → 真·未变更，跳过；
      - 文件名存在但 hash 变了，或存在历史重复副本 → 删旧再重灌（修复「改了 .md 却仍用旧向量」）；
      - 文件名不存在 → 新入库。
    rebuild=True：先删除集合中全部历史文档再全量重灌。

    store 的连接已打开，调用方需在 finally 中 await store.__aexit__(...)。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(QDRANT_DIR, exist_ok=True)

    # ① 解析 + ② 切块
    parser = TextParser()
    chunker = ApproxTokenChunker(
        # 按近似 token 切，块 256 token、相邻块重叠 32 token
        parameters=ApproxTokenChunker.Parameters(chunk_size=256, overlap=32)
    )

    # ③ 嵌入 + 向量库 + 知识库句柄
    embedding_model = make_embedding_model()
    # Qdrant 本地持久化到磁盘；想用纯内存(不落盘)改 QdrantStore(location=":memory:")
    store = QdrantStore(path=QDRANT_DIR)

    await store.__aenter__()  # 建立连接（不在此关闭，由入口 finally 关闭）

    knowledge = KnowledgeBase(
        name="agent-rag-kb",
        description="城市生活政策知识库",
        embedding_model=embedding_model,
        vector_store=store,
        collection="agent-rag-kb",
    )

    # 已入库文档：按文件名归组其 DocumentSummary（含 metadata，供内容 hash 比对）
    # 向量库是「哪些文档存在」的唯一事实源；DocumentSummary.metadata 可回读当初写入的 content_hash。
    existing: dict[str, list] = {}
    for s in await knowledge.list_documents():
        name = os.path.basename(getattr(s, "source", "") or "") or (s.metadata or {}).get("filename") or ""
        if name:
            existing.setdefault(name, []).append(s)

    if rebuild and existing:
        removed = 0
        for summaries in existing.values():
            for s in summaries:
                await knowledge.delete_document(s.document_id)
                removed += 1
        observability.log_event("rag.rebuild", msg=f"  ↻ 重建：已清空 {removed} 个历史文档（含重复副本）", removed=removed)
        existing.clear()

    # 遍历 data/docs/{CITY}/ 下的文档，逐篇内容感知入库（每篇一个 document_id）
    total = 0
    for filename in os.listdir(DATA_DIR):
        if not filename.lower().endswith((".md", ".txt", ".csv", ".html")):
            continue
        path = os.path.join(DATA_DIR, filename)
        h = _file_hash(path)
        summaries = existing.get(filename)
        if summaries:
            stored = {(s.metadata or {}).get("content_hash") for s in summaries}
            # 恰好一份且内容未变 → 真·未变更，跳过（避免重复 embedding、省 token）
            if len(summaries) == 1 and stored == {h}:
                observability.log_event("rag.skip", msg=f"  ↳ 跳过未变更 {filename}", filename=filename)
                continue
            # 内容变更，或存在历史重复副本 → 删旧再重灌
            for s in summaries:
                await knowledge.delete_document(s.document_id)
            observability.log_event(
                "rag.update",
                msg=f"  ↻ 更新 {filename}（内容变更/副本清理，删 {len(summaries)} 旧档）",
                filename=filename, old_copies=len(summaries), changed=(stored != {h}),
            )
        sections = await parser.parse(file=path, filename=filename)
        chunks = await chunker.chunk(sections)
        doc_id = await knowledge.insert_document(
            chunks,
            document_metadata={"filename": filename, "content_hash": h, "indexed_at": int(time.time())},
        )
        total += len(chunks)
        observability.log_event("rag.insert", msg=f"  ↳ 已入库 {filename} → {doc_id}（{len(chunks)} chunk）", filename=filename, doc_id=doc_id, chunks=len(chunks))
    observability.log_event("rag.build_done", msg=f"解析+切块完成，本次新入库 {total} 个 Chunk", new_chunks=total)

    return knowledge, store
