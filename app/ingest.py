"""SEC and Yahoo adapters, chunking, embeddings, and idempotent persistence."""

import asyncio
import hashlib
import logging
import math
import re
from datetime import date, datetime, timezone
from typing import Any

import edgar
import yfinance as yf
from google import genai
from google.genai import types
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)
edgar.set_identity(settings.EDGAR_IDENTITY)
edgar.use_local_storage(settings.EDGAR_USE_LOCAL_DATA)


def normalize_ticker(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,15}", ticker):
        raise ValueError("Ticker must contain 1 to 16 valid symbol characters")
    return ticker


def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
    """Prefer paragraph, sentence, and word boundaries with character overlap."""
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= overlap < chunk_size")
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", text)]
    cleaned = "\n\n".join(part for part in paragraphs if part)
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        if end < len(cleaned):
            lower = start + max(overlap + 1, chunk_size // 2)
            window = cleaned[lower:end]
            for pattern in (r"\n\n", r"(?<=[.!?])\s+", r"\s+"):
                boundaries = list(re.finditer(pattern, window))
                if boundaries:
                    end = lower + boundaries[-1].end()
                    break
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(cleaned):
            break
        start = max(start + 1, end - overlap)
    return chunks


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for embeddings")
    vectors: list[list[float]] = []
    async with genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=60000),
    ).aio as client:
        for offset in range(0, len(texts), 20):
            batch = texts[offset:offset + 20]
            response = await client.models.embed_content(
                model=settings.EMBEDDING_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(output_dimensionality=768),
            )
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch):
                raise RuntimeError("Embedding provider returned an incorrect batch size")
            for embedding in embeddings:
                vec = embedding.values or []
                if len(vec) != 768 or not all(math.isfinite(v) for v in vec) or not any(vec):
                    raise RuntimeError("Embedding provider returned an invalid 768-dimensional vector")
                vectors.append(vec)
    return vectors


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Source publication time is missing")
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _fetch_filings(ticker: str) -> list[dict]:
    documents: list[dict] = []
    try:
        filings = edgar.Company(ticker).get_filings(form=["10-Q", "8-K"]).latest(2)
        if filings is None:
            return documents
        if hasattr(filings, "form"):
            filings = [filings]
        for filing in filings:
            try:
                content = filing.text()[:30000]
                if content.strip():
                    documents.append({
                        "doc_type": str(filing.form),
                        "filed_at": _as_datetime(filing.filing_date),
                        "source_url": str(filing.url),
                        "content": content,
                    })
            except Exception:
                logger.warning("Unable to read an SEC filing for %s", ticker, exc_info=True)
    except Exception:
        logger.warning("SEC ingestion failed for %s; news will still be processed", ticker, exc_info=True)
    return documents


def _fetch_news(ticker: str) -> list[dict]:
    documents: list[dict] = []
    try:
        articles = yf.Ticker(ticker).news or []
        for item in articles[:10]:
            if not isinstance(item, dict):
                continue
            nested = item.get("content")
            data = {**item, **({key: value for key, value in nested.items() if value} if isinstance(nested, dict) else {})}
            title = data.get("title")
            summary = data.get("summary") or data.get("description")
            content = "\n\n".join(v.strip() for v in (title, summary) if isinstance(v, str) and v.strip())
            link = None
            for key in ("canonicalUrl", "clickThroughUrl", "link"):
                candidate = data.get(key)
                if isinstance(candidate, dict):
                    candidate = candidate.get("url")
                if isinstance(candidate, str) and candidate.startswith(("https://", "http://")):
                    link = candidate
                    break
            if not content or link is None:
                continue
            try:
                filed_at = _as_datetime(data.get("pubDate") or data.get("providerPublishTime"))
            except (ValueError, OverflowError, OSError):
                logger.warning("Skipping news without a valid publication date for %s", ticker)
                continue
            documents.append({
                "doc_type": "news", "filed_at": filed_at,
                "source_url": link, "content": content,
            })
    except Exception:
        logger.warning("News ingestion failed for %s", ticker, exc_info=True)
    return documents


async def ingest_ticker(db: AsyncSession, ticker: str) -> dict:
    ticker = normalize_ticker(ticker)
    filings, news = await asyncio.gather(
        asyncio.to_thread(_fetch_filings, ticker),
        asyncio.to_thread(_fetch_news, ticker),
    )
    candidates: dict[str, dict] = {}
    total_chunks = 0
    for document in filings + news:
        for chunk in chunk_text(document["content"]):
            total_chunks += 1
            content_hash = hashlib.sha256(chunk.encode()).hexdigest()
            candidates.setdefault(content_hash, {
                **document, "ticker": ticker, "content": chunk, "content_hash": content_hash,
            })
    if not candidates:
        return {"ticker": ticker, "chunks_processed": 0, "new_chunks_inserted": 0, "duplicates_skipped": 0}
    existing = set((await db.execute(
        text("SELECT content_hash FROM market_documents WHERE content_hash IN :hashes")
        .bindparams(bindparam("hashes", expanding=True)),
        {"hashes": list(candidates)},
    )).scalars())
    new_chunks = [doc for digest, doc in candidates.items() if digest not in existing]
    vectors = await embed_texts([doc["content"] for doc in new_chunks])
    inserted = 0
    for document, vec in zip(new_chunks, vectors, strict=True):
        result = await db.execute(text("""
            INSERT INTO market_documents
                (ticker, doc_type, filed_at, source_url, content_hash, content, embedding)
            VALUES (:ticker, :doc_type, :filed_at, :source_url, :content_hash, :content,
                    CAST(:embedding AS vector))
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id
        """), {**document, "embedding": f"[{','.join(map(str, vec))}]"})
        inserted += result.scalar_one_or_none() is not None
    return {
        "ticker": ticker, "chunks_processed": total_chunks,
        "new_chunks_inserted": inserted, "duplicates_skipped": total_chunks - inserted,
    }
