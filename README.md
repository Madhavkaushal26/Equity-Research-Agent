# Autonomous Equity & Earnings Research Agent

An async FastAPI backend for SEC filings, financial news, grounded research briefs, and persistent investor preferences. PostgreSQL stores 768-dimensional embeddings and conversation state. Gemini supplies embeddings, tool calling, and structured research output.

## Architecture

`SEC / Yahoo -> ingestion -> SHA-256 deduplication -> PostgreSQL + pgvector -> retrieval -> research agent -> FastAPI`

- `app/database.py`: async engine, transactions, and idempotent startup DDL.
- `app/models.py`: strict Pydantic v2 public contracts.
- `app/ingest.py`: SEC/news adapters, boundary-aware chunks, embedding batches of 20, conflict-safe inserts.
- `app/retrieval.py`: shared search boundary used by agent tools and evaluation.
- `app/sessions.py`: profile and conversation persistence.
- `app/agent.py`: research tools, citation validation, and six-turn context.
- `app/main.py`: lifespan, HTTP endpoints, CORS, and error handling.
- `eval.py`: retrieval comparison and five-brief faithfulness evaluation.

Hybrid currently means SQL metadata filtering plus cosine vector ranking. BM25 fusion and reranking can be implemented behind `search_documents` without changing its arguments, returned document fields, database tables, or chat contracts. A future streaming route can wrap the agent while keeping the existing JSON endpoint stable.

Blocking edgartools and yfinance calls run in worker threads. PostgreSQL and Gemini operations use async clients. Each HTTP request commits before sending its success response or rolls back on failure. Research turns lock their session row until completion to prevent lost history and profile updates; tool access to the shared AsyncSession is serialized. Transient model HTTP failures retry at most three times within the turn timeout, using database savepoints to roll back failed-attempt tool writes.

## Setup

Use Python 3.11 or newer and a PostgreSQL instance with pgvector. For the local database, install Docker and Docker Compose.

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On PowerShell, use `Copy-Item .env.example .env` and `.venv\Scripts\Activate.ps1` instead of the Unix copy and activation commands.

Edit `.env` with your Gemini API key and your own SEC EDGAR identity in `Full Name email@example.com` format. `GEMINI_MODEL` selects a tool-capable Gemini model available to your account. The default embedding model is `gemini-embedding-001`, requested at 768 dimensions. Do not mix embedding models in one corpus; re-embed the corpus before changing this setting on an existing deployment.

### Run everything with Docker

```bash
docker compose up --build -d
docker compose logs -f api
```

The API waits for PostgreSQL health and initializes `schema.sql` on startup. The Docker image runs as a non-root user. `PORT` defaults to `8000` and controls both the API listener and Compose port mapping.

### Run Python locally with the Docker database

```bash
docker compose up -d db
uvicorn app.main:app --reload
```

Compose reads `.env` for interpolation, including when starting only `db`. Keep the configured variables in that file. Local Python reads `DATABASE_URL` from `.env`; the API container uses the Compose database hostname `db`.

### Supabase or external PostgreSQL

Set `DATABASE_URL` to the SQLAlchemy asyncpg URL for your database, using `postgresql+asyncpg://` as the scheme. Use a direct connection or a session-mode pooler compatible with asyncpg prepared statements. Percent-encode special characters in credentials. For TLS, use asyncpg's `?ssl=require` query option. The startup role needs permission to create the vector extension, tables, and indexes. An administrator can pre-apply `schema.sql` if extension creation is restricted. Idempotent DDL initializes fresh instances; it is not a migration system for incompatible existing tables.

Run the same `uvicorn` command without the local database container. The root URL is [http://localhost:8000](http://localhost:8000), and OpenAPI documentation is at [http://localhost:8000/docs](http://localhost:8000/docs).

## API examples

These examples use a POSIX shell. On Windows, use `curl.exe` and your shell's JSON quoting rules, or call the API through `/docs`.

```bash
curl -fsS http://localhost:8000/health

curl -fsS -X POST http://localhost:8000/ingest/AAPL

curl -fsS -X POST http://localhost:8000/research/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"Add AAPL to my watchlist. I am conservative and focus on margins and FCF. Analyze its revenue drivers, catalysts, and risks.","ticker_filter":"AAPL"}'

curl -fsS -X POST http://localhost:8000/research/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"How do its current price and P/E affect that assessment?","ticker_filter":"AAPL"}'

curl -fsS http://localhost:8000/sessions/demo
curl -fsS http://localhost:8000/documents/stats
```

| Method | Route | Result |
|---|---|---|
| GET | `/health` | PostgreSQL connectivity and installed vector extension version; 503 if unavailable |
| POST | `/ingest/{ticker}` | Ticker, chunks processed, new rows inserted, duplicates skipped |
| POST | `/research/chat` | Session ID, validated ResearchBrief, current investor profile |
| GET | `/sessions/{session_id}` | Profile, full message history, update timestamp; 404 for an unknown session |
| GET | `/documents/stats` | Total chunks and breakdown by ticker and document type |

Ingest a ticker before asking research questions about it. Ingestion reads the latest two 10-Q/8-K filings, truncates each to 30,000 characters, and collects up to ten Yahoo news titles and available summaries. These are partial source texts, not complete filing or news archives. News entries lacking a usable URL or publication date are skipped. SEC failures are logged and do not prevent news ingestion. Zero processed chunks means no usable source data was returned; inspect logs and retry. Global SHA-256 uniqueness follows the existing schema, including identical text shared across tickers. Concurrent insert conflicts count as duplicates.

Research responses validate citation IDs, exact source metadata, verbatim excerpts, and catalyst/risk references against documents actually retrieved during that turn. This does not prove semantic entailment of every generated claim. Missing live metrics remain null. Live Yahoo metrics are attributed in the summary and are not assigned fabricated document IDs. A ticker filter is enforced in retrieval and live fundamentals tools. Search without evidence produces zero confidence. Provider errors return 502, research timeouts return 504, and invalid request bodies return 422.

The requested CORS policy allows any origin and disables credentialed cross-origin requests. Session IDs are identifiers, not authentication credentials. Deploy behind an authenticated gateway with rate limits and TLS before allowing untrusted network access. SEC and Yahoo providers can rate-limit requests; retry failed ingestion and avoid concurrent bulk ticker ingestion.

## Evaluation Benchmarks

```bash
python eval.py
```

The script initializes the schema, ingests AAPL, NVDA, and MSFT if absent, and evaluates twelve fixed queries: revenue drivers, operating margins, risk factors, and product catalysts for each ticker. It compares unfiltered vector retrieval with ticker-filtered retrieval at five results. It then generates five briefs spanning all three tickers and requests structured Gemini judgments grounded in the exact tool evidence used for generation.

Relevance labels require the expected ticker and at least one whole expected keyword phrase in a corpus chunk. Recall@5 is the number of unique relevant retrieved chunks divided by all relevant corpus chunks. MRR@5 averages the reciprocal rank of the first relevant result, with zero for a miss. Queries with no relevant corpus chunks have null metrics and are excluded from macro averages. Keyword labels are heuristic, and overlapping chunks can inflate the recall denominator. The generated table includes scored query counts so corpus gaps are visible. Faithfulness averages successful judge scores in [0, 1]; the same model performs generation and judging, so scores are not independent human validation.

Measured live on 2026-11-26 using `gemini-3.5-flash-lite` and `gemini-embedding-001`. All 24 searches and all five generation/judgment pairs completed without errors. Six queries had no keyword-labeled relevant corpus chunks, so recall and MRR average the remaining six. N/A marks metrics that do not apply to a benchmark row. The requested `gemini-3.8-flash` repeatedly returned capacity/time-out errors; the saved fallback passed generation, embeddings, and the full evaluation.

| Benchmark | Queries scored | Recall@5 | MRR@5 | Faithfulness |
|---|---:|---:|---:|---:|
| Baseline Vector-Only Search | 6/12 | 0.4333 | 0.3056 | N/A |
| Hybrid SQL + Vector Search | 6/12 | 0.4333 | 0.3333 | N/A |
| LLM-as-a-Judge | 5/5 | N/A | N/A | 0.8200 |

`eval_results.json` contains the corpus snapshot, query labels, relevant IDs, retrieved passages, generated responses, exact tool evidence, judgments, errors, timestamps, and model names. Failed calls are reported and never replaced with invented scores. Partial or failed evaluations exit nonzero. The script uses live providers and consumes Gemini quota; results vary with ingestion time. Evaluation sessions use unique IDs and remain in the database for inspection.

## Verification

```bash
python -m unittest discover -s tests -v
python -m py_compile app/__init__.py app/config.py app/database.py app/models.py app/ingest.py app/retrieval.py app/sessions.py app/agent.py app/main.py eval.py tests/test_backend.py
```

Tests use controlled provider and database doubles to verify chunk boundaries, deduplication, query filters, profile persistence, citation rejection, HTTP contracts, and retrieval metric math. Real PostgreSQL, SEC, Yahoo, and Gemini connectivity require the configured services and the live benchmark.

### Repeat the live checks on Windows

```powershell
.venv\Scripts\python.exe -m scripts.check_models
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start_server.ps1
.venv\Scripts\python.exe -m scripts.smoke_test --stage all
.venv\Scripts\python.exe eval.py
```

The startup script leaves Uvicorn running on `0.0.0.0:8000`, records its PID, and writes logs under `.runtime`. Pass `-Restart` to restart the process managed by this workspace. The smoke checker verifies health, persisted NVDA chunks, a validated research brief, and nonempty citations. Model discovery is available with `python -m scripts.check_models --list-only`; `--model MODEL_ID` verifies a selected Flash model before saving it in `.env`. API keys are not printed.
