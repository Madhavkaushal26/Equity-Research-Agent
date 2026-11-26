"""Verify the running API against real PostgreSQL and research providers."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from app.models import ChatResponse


async def verify(stage: str, base_url: str) -> None:
    results: dict = {}
    async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:
        health = await client.get("/health")
        health.raise_for_status()
        assert health.json().get("pgvector_version"), "pgvector is missing"
        results["health"] = {"status_code": health.status_code, "body": health.json()}
        print(f"GET /health: {health.status_code}, pgvector {health.json()['pgvector_version']}", flush=True)
        if stage in {"ingest", "all"}:
            response = await client.post("/ingest/NVDA")
            response.raise_for_status()
            metrics = response.json()
            assert metrics["chunks_processed"] > 0, "Ingestion returned no source text"
            stats = (await client.get("/documents/stats")).json()
            count = sum(row["chunks"] for row in stats["breakdown"] if row["ticker"] == "NVDA")
            assert count > 0, "No NVDA chunks persisted"
            results["ingest"] = {"status_code": response.status_code, "body": metrics, "persisted_nvda_chunks": count}
            print(f"POST /ingest/NVDA: {response.status_code}, {json.dumps(metrics)}, persisted={count}", flush=True)
        if stage in {"chat", "all"}:
            response = await client.post("/research/chat", json={
                "session_id": "smoke-test",
                "message": "Summarize Nvidia's recent revenue drivers and key risks.",
                "ticker_filter": "NVDA",
            })
            if response.status_code != 200:
                print(f"Chat error: {response.status_code}, {response.text}", flush=True)
            response.raise_for_status()
            chat = ChatResponse.model_validate(response.json())
            assert chat.brief.cited_sources, "Research brief has no citations"
            assert all(source.ticker == "NVDA" for source in chat.brief.cited_sources)
            results["chat"] = {"status_code": response.status_code, "body": chat.model_dump()}
            print(f"POST /research/chat: {response.status_code}, citations={len(chat.brief.cited_sources)}, confidence={chat.brief.confidence_score}", flush=True)
    output = Path(".runtime") / f"smoke-{stage}.json"
    output.parent.mkdir(exist_ok=True)
    await asyncio.to_thread(output.write_text, json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["health", "ingest", "chat", "all"], default="all")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    asyncio.run(verify(args.stage, args.base_url))
