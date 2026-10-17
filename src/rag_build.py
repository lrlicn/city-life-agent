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

from agentscope.credential import OpenAICredential
from agentscope.embedding import OpenAIEmbeddingModel
from agentscope.rag import ApproxTokenChunker, KnowledgeBase, QdrantStore, TextParser

from src import config

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


async def build_knowledge_base(rebuild: bool = False) -> tuple[KnowledgeBase, QdrantStore]:
    """读取 data/docs/{CITY}/ 下所有文档，解析切块后入库，返回 (knowledge, store)。

    幂等：默认按文件名跳过集合中已存在的文档，避免每次启动/运行重复入库、累积重复副本。
    rebuild=True：先删除集合中全部历史文档（含旧版遗留的重复副本）再重新入库，
                  也用于源文档内容变更后强制刷新。

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

    # 已入库文档：按文件名归组其 document_id（用于幂等跳过 / 重建清空）
    existing: dict[str, list[str]] = {}
    for s in await knowledge.list_documents():
        name = os.path.basename(getattr(s, "source", "") or "")
        if name:
            existing.setdefault(name, []).append(s.document_id)

    if rebuild and existing:
        removed = 0
        for doc_ids in existing.values():
            for doc_id in doc_ids:
                await knowledge.delete_document(doc_id)
                removed += 1
        print(f"  ↻ 重建：已清空 {removed} 个历史文档（含重复副本）")
        existing.clear()

    # 遍历 data/docs/{CITY}/ 下的 .md/.txt 文件，逐篇入库（每篇一个 document_id）
    total = 0
    for filename in os.listdir(DATA_DIR):
        if not filename.lower().endswith((".md", ".txt", ".csv", ".html")):
            continue
        if filename in existing:
            print(f"  ↳ 跳过已入库 {filename}（集合内 {len(existing[filename])} 份）")
            continue
        path = os.path.join(DATA_DIR, filename)
        sections = await parser.parse(file=path, filename=filename)
        chunks = await chunker.chunk(sections)
        doc_id = await knowledge.insert_document(
            chunks,
            document_metadata={"filename": filename},
        )
        total += len(chunks)
        print(f"  ↳ 已入库 {filename} → {doc_id}（{len(chunks)} chunk）")
    print(f"解析+切块完成，本次新入库 {total} 个 Chunk")

    return knowledge, store
