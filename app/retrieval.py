"""Retrieval boundary shared by agent tools and offline evaluation.

Metadata filtering and vector ranking live here. Future lexical fusion and
reranking can retain this function's arguments and document result shape.
"""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest import embed_texts, normalize_ticker


async def search_documents(
    db: AsyncSession,
    query: str,
    ticker: Optional[str] = None,
    doc_type: Optional[str] = None,
    top_k: int = 6,
) -> list[dict]:
    if not query.strip():
        raise ValueError("Search query must not be blank")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 50:
        raise ValueError("top_k must be an integer between 1 and 50")
    filters = []
    params: dict = {"top_k": top_k}
    if ticker is not None:
        filters.append("UPPER(ticker) = :ticker")
        params["ticker"] = normalize_ticker(ticker)
    if doc_type is not None:
        filters.append("doc_type = :doc_type")
        params["doc_type"] = doc_type.strip()
    vec = (await embed_texts([query]))[0]
    params["query_vec"] = f"[{','.join(map(str, vec))}]"
    where = " AND ".join(filters) if filters else "TRUE"
    result = await db.execute(text(f"""
        SELECT id AS doc_id, ticker, doc_type, filed_at, source_url, content,
               1 - (embedding <=> CAST(:query_vec AS vector)) AS similarity
        FROM market_documents
        WHERE {where}
        ORDER BY similarity DESC, id ASC
        LIMIT :top_k
    """), params)
    return [
        {**dict(row), "filed_at": row["filed_at"].isoformat()}
        for row in result.mappings()
    ]
