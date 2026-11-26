# Setup and database: a workshop and its filing cabinets

Imagine a workshop with its own toolbox, a machine that stores files, and a private settings card. The toolbox is `.venv`, the storage machine is Docker PostgreSQL, and the settings card is `.env`.

**Follow the code:** [requirements.txt](<C:/Users/madha/Desktop/ELIP/requirements.txt>) lists the tools; [docker-compose.yml](<C:/Users/madha/Desktop/ELIP/docker-compose.yml>) defines the `db` and `api` services; [app/config.py](<C:/Users/madha/Desktop/ELIP/app/config.py>), `Settings`, reads settings.

## 1. The Python toolbox: .venv

A separate pencil case keeps this course's supplies away from another course's supplies. A **virtual environment** similarly isolates Python packages. It does not isolate the operating system like a container does.

**In this repo:** `.venv\Scripts\python.exe` runs the Python interpreter with this project's installed dependencies. `requirements.txt` includes FastAPI, SQLAlchemy, asyncpg, Google GenAI, PydanticAI, edgartools, and yfinance. The setup found an existing environment, installed its missing `pip` with `ensurepip`, and then installed the requirements. The environment itself is ignored by Git.

## 2. A ready-made database machine: Docker and pgvector

A shipping container arrives with the equipment already arranged inside. A **Docker image** is the recipe for that arrangement; a running **container** is an instance of it.

**In this repo:** the `db` service in `docker-compose.yml` runs `pgvector/pgvector:pg16`. It is ordinary PostgreSQL 16 with the **pgvector extension**, which adds a vector type and vector-distance operations. The `pgdata` volume keeps database files outside the disposable container filesystem. Removing the volume would remove that stored database.

The `api` service can run the application in a container too. Our recorded live verification instead ran Python/Uvicorn on Windows and PostgreSQL in Docker. Its path was:

```text
Windows Python -> localhost:5432 -> Docker PostgreSQL

Alternative all-Docker setup:
api container  -> db:5432        -> db container
```

`localhost` inside an API container would refer to that container itself. That is why Compose supplies the database hostname `db` for its API service.

**Container entry point:** [Dockerfile](<C:/Users/madha/Desktop/ELIP/Dockerfile>) installs requirements, switches to a non-root user, and starts Uvicorn with `${PORT:-8000}`.

## 3. The private settings card: .env

A restaurant's private card might contain its delivery address and account credentials. `.env` supplies configuration without hard-coding secrets into source files.

**In this repo:** `Settings` in `app/config.py` reads `.env` from the working directory. Process environment variables can override file values. The module-level `settings` object is created at import time, so changing `.env` requires restarting a running server.

| Setting | Purpose | Consumer |
|---|---|---|
| `DATABASE_URL` | PostgreSQL address and driver, using `postgresql+asyncpg` | `engine` in [app/database.py](<C:/Users/madha/Desktop/ELIP/app/database.py>) |
| `GEMINI_API_KEY` | Authenticates embedding and generation requests | `embed_texts()` in [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>) |
| `GOOGLE_API_KEY` | Matching authentication value for the agent provider | Module initialization in [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>) |
| `GEMINI_MODEL` | Text/tool-calling model; saved live fallback was `gemini-3.5-flash-lite` | `research_agent` in `app/agent.py` |
| `EMBEDDING_MODEL` | Text-to-vector model, `gemini-embedding-001` in the measured run | `embed_texts()` in `app/ingest.py` |
| `EDGAR_IDENTITY` | Name and email identifying SEC requests | `edgar.set_identity(...)` in `app/ingest.py` |
| `EDGAR_USE_LOCAL_DATA` | Controls edgartools local-storage mode; configured `False` | `edgar.use_local_storage(...)` in `app/ingest.py` |

> [!NOTE]
> The key was preserved and mirrored between the two key variables. This vault intentionally contains no key values. The current workspace already has `.env`; its earlier `.env.example` file is absent from the working tree. Do not overwrite `.env` to recreate a template. The default model in `Settings` is also different from the saved live fallback: defaults apply only when no overriding value is supplied.

## 4. The filing-cabinet blueprint: schema.sql

A cabinet blueprint defines drawers and the labels each card must have. [schema.sql](<C:/Users/madha/Desktop/ELIP/schema.sql>) defines two tables and their indexes.

**`market_documents` is a drawer of passage cards, not whole filings.** Each row stores one chunk, its ticker, document type, publication/filing time, URL, SHA-256 hash, and embedding. `embedding vector(768)` requires exactly 768 numeric coordinates.

**`user_sessions` is a drawer of conversation notebooks.** A session ID identifies a row with watchlist, risk tolerance, focus metrics, and message history. JSONB stores JSON in a PostgreSQL representation that supports JSON operations. See `save_profile()` and `append_turn()` in [app/sessions.py](<C:/Users/madha/Desktop/ELIP/app/sessions.py>).

**HNSW is like a map with express routes between nearby neighborhoods.** Hierarchical Navigable Small World indexing builds a graph for approximate nearest-neighbor search. `idx_market_docs_embedding` in `schema.sql` uses HNSW with cosine-distance operators. Approximate search can trade exhaustive search for speed. An index existing does not prove a particular query uses it: inspect `EXPLAIN ANALYZE` before making performance claims. See [[03_Hybrid_Search]].

**The metadata index is like an index organized by company, form, and date.** `idx_market_docs_meta` covers `(ticker, doc_type, filed_at DESC)`. Actual index use depends on the SQL expression and query plan; the current ticker filter applies `UPPER(ticker)`.

## 5. Opening the workshop safely

A manager checks the cabinets at opening time and signs off work before handing it to the customer. `lifespan()` in [app/main.py](<C:/Users/madha/Desktop/ELIP/app/main.py>) calls `init_db()` in `app/database.py` at startup and disposes of the engine at shutdown.

`init_db()` reads `schema.sql` in a worker thread, then executes its five DDL statements inside a transaction. `IF NOT EXISTS` makes repeating this setup safe for the current schema. A PostgreSQL advisory transaction lock serializes competing initializers. This is startup initialization, not a migration system for arbitrary schema changes.

An engine is a connection manager. `pool_pre_ping=True` checks a pooled connection before reuse. `AsyncSessionLocal` creates async database sessions, and `get_db()` supplies a transaction for each request. `Depends(get_db, scope="function")` in `app/main.py` completes that transaction before sending success to the client.

## Practical Windows workflow

Use these commands from the repository root. The server may already be running; do not start a second copy on port 8000.

```powershell
Set-Location 'C:\Users\madha\Desktop\ELIP'
.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d db
docker compose ps
```

For a stopped API, [scripts/start_server.ps1](<C:/Users/madha/Desktop/ELIP/scripts/start_server.ps1>) is a top-level PowerShell script that launches a hidden background process and checks `/health`. Add `-Restart` only when you want to restart its managed process.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start_server.ps1
```

> [!TIP]
> A port is like a numbered doorway. During setup, the existing Windows service `postgresql-x64-16` occupied doorway 5432. It was stopped with approval so Docker could use the requested port. Its data files were preserved. Avoid restarting that service while Docker still owns 5432. Runtime logs and the managed server PID are in `.runtime`.

Next: [[02_Ingestion_and_Embeddings]]. Return to [[00_START_HERE]].
