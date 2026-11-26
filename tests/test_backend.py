"""Deterministic regression checks without network credentials or a live database."""

import hashlib
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("EDGAR_LOCAL_DATA_DIR", str(Path(__file__).resolve().parent.parent / ".edgar"))

import httpx
from pydantic import ValidationError
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app import agent, database, ingest, retrieval, sessions
from app.main import app
from app.models import ChatRequest, ResearchBrief
from eval import BENCHMARK_QUERIES, relevant_document_ids, retrieval_metrics

DATE = datetime(2026, 1, 2, tzinfo=timezone.utc)
DOCUMENT = {
    "doc_id": 11, "ticker": "AAPL", "doc_type": "10-Q", "filed_at": DATE.isoformat(),
    "source_url": "https://www.sec.gov/Archives/filing.htm", "content": "Revenue grew 10 percent. Margins improved.",
    "similarity": 0.9,
}


def make_brief() -> ResearchBrief:
    return ResearchBrief(
        query_intent="Revenue drivers", executive_summary="Revenue grew 10 percent.",
        bull_catalysts=[{"title": "Growth", "impact_summary": "Revenue increased.", "metric_or_evidence": "10 percent", "source_id": 11}],
        bear_risks=[],
        cited_sources=[{
            **{key: DOCUMENT[key] for key in ("doc_id", "ticker", "doc_type", "filed_at", "source_url")},
            "excerpt": "Revenue grew 10 percent.",
        }], confidence_score=0.8,
    )


def savepoint():
    manager = MagicMock()
    manager.__aenter__ = AsyncMock()
    manager.__aexit__ = AsyncMock(return_value=False)
    return manager


class ChunkAndContractTests(unittest.TestCase):
    def test_normalization_and_empty_text(self):
        self.assertEqual(ingest.chunk_text("  First   sentence.\n\n Second\tparagraph.  "), ["First sentence.\n\nSecond paragraph."])
        self.assertEqual(ingest.chunk_text(" \n \t"), [])

    def test_long_text_coverage_overlap_and_limits(self):
        value = "".join(chr(65 + index % 26) for index in range(5101))
        chunks = ingest.chunk_text(value, 1500, 200)
        self.assertTrue(all(0 < len(chunk) <= 1500 for chunk in chunks))
        rebuilt = chunks[0] + "".join(chunk[200:] for chunk in chunks[1:])
        self.assertEqual(rebuilt, value)
        for previous, current in zip(chunks, chunks[1:]):
            self.assertEqual(previous[-200:], current[:200])

    def test_prefers_sentence_boundary(self):
        chunks = ingest.chunk_text("First sentence. Second sentence. Third sentence.", 36, 0)
        self.assertEqual(chunks[0], "First sentence. Second sentence.")

    def test_invalid_chunk_settings(self):
        for size, overlap in ((0, 0), (10, 10), (10, -1)):
            with self.assertRaises(ValueError):
                ingest.chunk_text("text", size, overlap)

    def test_strict_contracts(self):
        for data in ({"session_id": 1, "message": "hello"}, {"session_id": "x", "message": " "}, {"session_id": "x", "message": "hello", "extra": True}):
            with self.assertRaises(ValidationError):
                ChatRequest.model_validate(data)
        with self.assertRaises(ValidationError):
            ResearchBrief.model_validate({**make_brief().model_dump(), "confidence_score": float("nan")})

    def test_ticker_normalization(self):
        self.assertEqual(ingest.normalize_ticker(" aapl "), "AAPL")
        with self.assertRaises(ValueError):
            ingest.normalize_ticker("AAPL'; DROP TABLE market_documents")

    def test_recall_is_not_precision_or_hit_rate(self):
        metrics = retrieval_metrics([{"doc_id": 8}, {"doc_id": 2}, {"doc_id": 2}], {1, 2, 3, 4})
        self.assertEqual(metrics["recall_at_5"], 0.25)
        self.assertEqual(metrics["reciprocal_rank"], 0.5)
        self.assertIsNone(retrieval_metrics([], set())["recall_at_5"])
        self.assertEqual(retrieval_metrics([], {1})["reciprocal_rank"], 0.0)

    def test_benchmark_cases_and_whole_keyword_labels(self):
        self.assertEqual(len(BENCHMARK_QUERIES), 12)
        for ticker in ("AAPL", "NVDA", "MSFT"):
            self.assertEqual(sum(case["expected_ticker"] == ticker for case in BENCHMARK_QUERIES), 4)
        corpus = [{"doc_id": 1, "ticker": "NVDA", "content": "said"}, {"doc_id": 2, "ticker": "NVDA", "content": "AI demand"}]
        self.assertEqual(relevant_document_ids(corpus, {"expected_ticker": "NVDA", "expected_keywords": ["ai"]}), {2})


class IngestionTests(unittest.IsolatedAsyncioTestCase):
    def test_nested_and_flat_news(self):
        news = [
            {"content": {"title": "Nested", "summary": "News body", "pubDate": "2026-01-02T00:00:00Z", "canonicalUrl": {"url": "https://example.com/nested"}}},
            {"content": None, "title": "Flat", "providerPublishTime": 1767312000, "link": "https://example.com/flat"},
            None, {"content": "malformed"},
        ]
        with patch.object(ingest.yf, "Ticker", return_value=SimpleNamespace(news=news)):
            documents = ingest._fetch_news("AAPL")
        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0]["content"], "Nested\n\nNews body")
        self.assertEqual(documents[1]["source_url"], "https://example.com/flat")

    async def test_filing_failure_does_not_prevent_news_ingestion(self):
        doc = {"doc_type": "news", "filed_at": DATE, "source_url": "https://example.com/news", "content": "Revenue grew."}
        existing = MagicMock()
        existing.scalars.return_value = []
        inserted = MagicMock()
        inserted.scalar_one_or_none.return_value = 1
        db = SimpleNamespace(execute=AsyncMock(side_effect=[existing, inserted]))
        with self.assertLogs(ingest.logger, level="WARNING"), patch.object(ingest.edgar, "Company", side_effect=RuntimeError("SEC unavailable")), patch.object(ingest, "_fetch_news", return_value=[doc, doc]), patch.object(ingest, "embed_texts", new=AsyncMock(return_value=[[0.1] * 768])) as embed:
            metrics = await ingest.ingest_ticker(db, " aapl ")
        self.assertEqual(metrics, {"ticker": "AAPL", "chunks_processed": 2, "new_chunks_inserted": 1, "duplicates_skipped": 1})
        embed.assert_awaited_once_with(["Revenue grew."])
        statement, params = db.execute.call_args.args
        self.assertIn("CAST(:embedding AS vector)", str(statement))
        self.assertEqual(len(json.loads(params["embedding"])), 768)

    async def test_existing_hashes_are_not_embedded(self):
        content = "Existing report."
        doc = {"doc_type": "news", "filed_at": DATE, "source_url": "https://example.com/news", "content": content}
        existing = MagicMock()
        existing.scalars.return_value = [hashlib.sha256(content.encode()).hexdigest()]
        db = SimpleNamespace(execute=AsyncMock(return_value=existing))
        with patch.object(ingest, "_fetch_filings", return_value=[doc]), patch.object(ingest, "_fetch_news", return_value=[]), patch.object(ingest, "embed_texts", new=AsyncMock(return_value=[])) as embed:
            metrics = await ingest.ingest_ticker(db, "AAPL")
        embed.assert_awaited_once_with([])
        self.assertEqual(metrics["new_chunks_inserted"], 0)
        self.assertEqual(metrics["duplicates_skipped"], 1)
        self.assertEqual(db.execute.await_count, 1)

    async def test_embedding_batches_and_dimensions(self):
        async def embed_content(**kwargs):
            self.assertEqual(kwargs["config"].output_dimensionality, 768)
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 768) for _ in kwargs["contents"]])
        client = SimpleNamespace(models=SimpleNamespace(embed_content=AsyncMock(side_effect=embed_content)))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        with patch.object(ingest.settings, "GEMINI_API_KEY", "test-key"), patch.object(ingest.genai, "Client", return_value=SimpleNamespace(aio=context)):
            self.assertEqual(len(await ingest.embed_texts(["sample"] * 41)), 41)
        self.assertEqual([len(call.kwargs["contents"]) for call in client.models.embed_content.call_args_list], [20, 20, 1])


class DatabaseAndRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_is_applied_statement_by_statement(self):
        connection = SimpleNamespace(execute=AsyncMock(), exec_driver_sql=AsyncMock())
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=connection)
        manager.__aexit__ = AsyncMock(return_value=False)
        with patch.object(database, "engine", SimpleNamespace(begin=MagicMock(return_value=manager))):
            await database.init_db()
        self.assertEqual(connection.exec_driver_sql.await_count, 5)
        self.assertIn("pg_advisory_xact_lock", str(connection.execute.call_args.args[0]))

    async def test_retrieval_filters_bound_parameters_and_result_contract(self):
        result = MagicMock()
        result.mappings.return_value = [{**DOCUMENT, "filed_at": DATE}]
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        with patch.object(retrieval, "embed_texts", new=AsyncMock(return_value=[[0.1] * 768])):
            documents = await retrieval.search_documents(db, "revenue", ticker=" aapl ", doc_type="10-Q", top_k=5)
        statement, params = db.execute.call_args.args
        sql = str(statement)
        self.assertIn("CAST(:query_vec AS vector)", sql)
        self.assertIn("UPPER(ticker) = :ticker", sql)
        self.assertEqual(params["ticker"], "AAPL")
        self.assertEqual(params["doc_type"], "10-Q")
        self.assertEqual(documents, [DOCUMENT])
        self.assertIn("query_vec", statement.compile(dialect=postgresql.asyncpg.dialect()).params)

    async def test_invalid_search_does_not_call_provider(self):
        with patch.object(retrieval, "embed_texts", new=AsyncMock()) as embed:
            with self.assertRaises(ValueError):
                await retrieval.search_documents(MagicMock(), "query", top_k=0)
        embed.assert_not_awaited()

    async def test_profile_upsert_uses_json_parameters(self):
        profile = {"watchlist": ["AAPL"], "risk_tolerance": "conservative", "focus_metrics": ["FCF"]}
        result = MagicMock()
        result.mappings.return_value.one.return_value = profile
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        self.assertEqual(await sessions.save_profile(db, "session", **profile), profile)
        statement, params = db.execute.call_args.args
        self.assertIn("ON CONFLICT", str(statement))
        self.assertEqual(json.loads(params["watchlist"]), ["AAPL"])


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_tool_normalizes_and_persists_preferences(self):
        ctx = SimpleNamespace(deps=agent.AgentDeps(db=MagicMock(), session_id="demo"))
        with patch.object(agent, "save_profile", new=AsyncMock(return_value={"watchlist": ["AAPL"]})) as save:
            await agent.update_investor_profile(ctx, [" aapl ", "AAPL"], "Conservative", ["fcf", "P/E"])
        self.assertEqual(save.call_args.args[1:], ("demo", ["AAPL"], "conservative", ["FCF", "P/E"]))

    async def test_live_fundamentals_preserve_missing_values(self):
        ctx = SimpleNamespace(deps=agent.AgentDeps(db=MagicMock(), session_id="demo"))
        ticker = MagicMock()
        ticker.get_info.return_value = {"regularMarketPrice": 12.0, "trailingPE": float("nan"), "marketCap": 1000}
        with patch.object(agent.yf, "Ticker", return_value=ticker):
            output = await agent.fetch_live_fundamentals(ctx, " aapl ")
        self.assertEqual(output["current_price"], 12.0)
        self.assertEqual(output["market_cap"], 1000)
        self.assertIsNone(output["trailing_pe"])
        self.assertIsNone(output["revenue_growth"])
        self.assertEqual(ctx.deps.fundamentals, [output])

    async def test_citations_require_search_and_exact_evidence(self):
        deps = agent.AgentDeps(db=MagicMock(), session_id="test")
        ctx = SimpleNamespace(deps=deps)
        with self.assertRaises(ModelRetry):
            await agent.validate_evidence(ctx, make_brief())
        deps.searched = True
        deps.documents = {11: DOCUMENT}
        self.assertEqual(await agent.validate_evidence(ctx, make_brief()), make_brief())
        for field, value in (("doc_id", 99), ("source_url", "https://fabricated.example"), ("excerpt", "fabricated metric")):
            brief = make_brief()
            setattr(brief.cited_sources[0], field, value)
            with self.assertRaises(ModelRetry):
                await agent.validate_evidence(ctx, brief)

    async def test_ticker_constraint_is_enforced_by_tool(self):
        deps = agent.AgentDeps(db=MagicMock(), session_id="test", ticker_filter="AAPL")
        with patch.object(retrieval, "search_documents", new=AsyncMock(return_value=[DOCUMENT])) as search:
            await agent.hybrid_research_search(SimpleNamespace(deps=deps), "query", ticker="MSFT")
        self.assertEqual(search.call_args.args[2], "AAPL")
        self.assertTrue(deps.searched)

    async def test_real_agent_tool_cycle_and_history(self):
        profile = {"watchlist": ["AAPL"], "risk_tolerance": "moderate", "focus_metrics": ["margins"]}
        session = {**profile, "message_history": [{"role": "user", "content": str(i)} for i in range(20)]}
        db = SimpleNamespace(info={}, begin_nested=MagicMock(side_effect=savepoint))
        invocations = 0

        async def respond(messages, info):
            nonlocal invocations
            invocations += 1
            if invocations == 1:
                prompt = messages[-1].parts[-1].content
                context_text = prompt.split("\n", 1)[1].split("\nCurrent user message:", 1)[0]
                stored = json.loads(context_text)
                self.assertEqual(len(stored["recent_conversation"]), 12)
                self.assertEqual(stored["recent_conversation"][0]["content"], "8")
                self.assertEqual(stored["investor_profile"], profile)
                return ModelResponse(parts=[ToolCallPart("hybrid_research_search", {"query": "revenue", "ticker": "AAPL"}, tool_call_id="search-1")])
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, make_brief().model_dump(), tool_call_id="output-1")])

        with patch.object(agent, "ensure_session", new=AsyncMock(return_value=session)), patch.object(agent, "get_session", new=AsyncMock(return_value=session)), patch.object(agent, "append_turn", new=AsyncMock()) as append, patch.object(retrieval, "search_documents", new=AsyncMock(return_value=[DOCUMENT])), agent.research_agent.override(model=FunctionModel(respond)):
            response = await agent.run_research_turn(db, "demo", "Analyze revenue", "AAPL")
        self.assertEqual(response.brief, make_brief())
        self.assertEqual(response.user_profile, profile)
        append.assert_awaited_once_with(db, "demo", "Analyze revenue", make_brief().executive_summary)
        self.assertEqual(db.info["last_research_evidence"]["documents"], [DOCUMENT])
        self.assertEqual(invocations, 2)

    async def test_transient_provider_failure_retries_without_duplicate_history(self):
        profile = {"watchlist": [], "risk_tolerance": "moderate", "focus_metrics": [], "message_history": []}
        db = SimpleNamespace(info={}, begin_nested=MagicMock(side_effect=savepoint))
        failed = ModelHTTPError(status_code=503, model_name="test", body={"error": "capacity"})
        with self.assertLogs(agent.logger, level="WARNING"), patch.object(agent, "ensure_session", new=AsyncMock(return_value=profile)), patch.object(agent, "get_session", new=AsyncMock(return_value=profile)), patch.object(agent, "append_turn", new=AsyncMock()) as append, patch.object(agent.research_agent, "run", new=AsyncMock(side_effect=[failed, SimpleNamespace(output=make_brief())])) as run, patch.object(agent.asyncio, "sleep", new=AsyncMock()):
            response = await agent.run_research_turn(db, "retry", "Revenue?")
        self.assertEqual(run.await_count, 2)
        self.assertEqual(db.begin_nested.call_count, 2)
        self.assertEqual(append.await_count, 1)
        self.assertEqual(response.brief, make_brief())


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = MagicMock()
        self.db.execute = AsyncMock()

        async def override_db():
            yield self.db

        app.dependency_overrides[database.get_db] = override_db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()

    async def test_health_reports_pgvector(self):
        result = MagicMock()
        result.scalar_one_or_none.return_value = "0.8.0"
        self.db.execute.return_value = result
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pgvector_version"], "0.8.0")
        result.scalar_one_or_none.return_value = None
        self.assertEqual((await self.client.get("/health")).status_code, 503)

    async def test_missing_session_and_invalid_chat(self):
        with patch("app.main.get_session", new=AsyncMock(return_value=None)):
            self.assertEqual((await self.client.get("/sessions/missing")).status_code, 404)
        self.assertEqual((await self.client.post("/research/chat", json={"session_id": "x", "message": " "})).status_code, 422)

    async def test_connection_refusal_is_unhealthy(self):
        self.db.execute.side_effect = ConnectionRefusedError("Database stopped")
        self.assertEqual((await self.client.get("/health")).status_code, 503)

    async def test_transaction_commit_failure_cannot_return_success(self):
        async def failing_transaction():
            yield self.db
            raise SQLAlchemyError("Commit failed")

        app.dependency_overrides[database.get_db] = failing_transaction
        with self.assertLogs("app.main", level="ERROR"), patch("app.main.ingest_ticker", new=AsyncMock(return_value={"ticker": "AAPL"})):
            response = await self.client.post("/ingest/AAPL")
        self.assertEqual(response.status_code, 503)

    async def test_chat_endpoint_response_contract(self):
        output = agent.ChatResponse(session_id="demo", brief=make_brief(), user_profile={"watchlist": []})
        with patch("app.main.run_research_turn", new=AsyncMock(return_value=output)) as run:
            response = await self.client.post("/research/chat", json={"session_id": "demo", "message": "Revenue?", "ticker_filter": "AAPL"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["brief"]["cited_sources"][0]["doc_id"], 11)
        self.assertEqual(run.call_args.args[1:], ("demo", "Revenue?", "AAPL"))

    async def test_stats_counts_and_cors(self):
        result = MagicMock()
        result.mappings.return_value.all.return_value = [{"ticker": "AAPL", "doc_type": "10-Q", "chunks": 3}, {"ticker": "MSFT", "doc_type": "news", "chunks": 2}]
        self.db.execute.return_value = result
        response = await self.client.get("/documents/stats", headers={"Origin": "https://frontend.example"})
        self.assertEqual(response.json()["total_chunks"], 5)
        self.assertEqual(response.headers["access-control-allow-origin"], "*")


if __name__ == "__main__":
    unittest.main()
