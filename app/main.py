"""FastAPI entry point and HTTP error boundaries."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.genai.errors import APIError
from pydantic_ai.exceptions import AgentRunError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import run_research_turn
from app.database import engine, get_db, init_db
from app.ingest import ingest_ticker, normalize_ticker
from app.models import ChatRequest, ChatResponse
from app.sessions import get_session, investor_profile

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Autonomous Equity & Earnings Research Agent", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.error("Database failure on %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(APIError)
@app.exception_handler(AgentRunError)
async def provider_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Research provider failure on %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=502, content={"detail": "Research provider could not complete the request"})


@app.exception_handler(TimeoutError)
async def timeout_error(request: Request, exc: TimeoutError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": "Research request timed out"})


@app.get("/")
async def root() -> dict:
    return {"service": app.title, "status": "running", "version": app.version}


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    try:
        version = (await db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))).scalar_one_or_none()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if version is None:
        raise HTTPException(status_code=503, detail="pgvector extension is not installed")
    return {"status": "ok", "database": "connected", "pgvector_version": version}


@app.post("/ingest/{ticker}")
async def ingest(ticker: str, db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    try:
        ticker = normalize_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await ingest_ticker(db, ticker)


@app.post("/research/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db, scope="function")) -> ChatResponse:
    if request.ticker_filter is not None:
        try:
            normalize_ticker(request.ticker_filter)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await run_research_turn(db, request.session_id, request.message, request.ticker_filter)


@app.get("/sessions/{session_id}")
async def session_details(session_id: str, db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id, "user_profile": investor_profile(session),
        "message_history": session["message_history"] or [], "updated_at": session["updated_at"],
    }


@app.get("/documents/stats")
async def document_stats(db: AsyncSession = Depends(get_db, scope="function")) -> dict:
    rows = (await db.execute(text("""
        SELECT ticker, doc_type, COUNT(*) AS chunks
        FROM market_documents GROUP BY ticker, doc_type ORDER BY ticker, doc_type
    """))).mappings().all()
    breakdown = [dict(row) for row in rows]
    return {"total_chunks": sum(row["chunks"] for row in breakdown), "breakdown": breakdown}
