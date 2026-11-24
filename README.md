# Autonomous Equity & Earnings Research Agent

Autonomous Equity & Earnings Research Agent is an intelligent financial analysis system designed for automated equity research, SEC EDGAR filing processing, earnings disclosures, and structured investment briefs powered by Gemini and PydanticAI.

## Architecture

```text
+---------------------------------------------------------------+
|                    SEC EDGAR / Market News                    |
+-------------------------------+-------------------------------+
                                |
                                v
+-------------------------------+-------------------------------+
|               SHA-256 Deduplication & Chunking               |
+-------------------------------+-------------------------------+
                                |
                                v
+-------------------------------+-------------------------------+
|              PostgreSQL + pgvector (HNSW Index)               |
+-------------------------------+-------------------------------+
                                |
                                v
+-------------------------------+-------------------------------+
| Hybrid SQL + Vector Retrieval & PydanticAI Tool-Calling Agent |
+-------------------------------+-------------------------------+
                                |
                                v
+-------------------------------+-------------------------------+
|          Schema-Validated ResearchBrief & Eval Suite          |
+---------------------------------------------------------------+
```

Pipeline flow:
SEC EDGAR / Market News -> SHA-256 Deduplication & Chunking -> PostgreSQL + pgvector (HNSW Index) -> Hybrid SQL + Vector Retrieval & PydanticAI Tool-Calling Agent -> Schema-Validated ResearchBrief & Eval Suite

## Tech Stack

- Application Framework: FastAPI, Uvicorn
- Data Validation & Settings: Pydantic v2, Pydantic-Settings
- Agent Orchestration: PydanticAI, Google GenAI SDK (Gemini)
- Database & Vector Search: PostgreSQL 16, pgvector (HNSW indexing), SQLAlchemy (AsyncIO), asyncpg
- Financial Data Ingestion: edgartools, yfinance, httpx

## Project Structure

```text
.
|-- .env.example
|-- .gitignore
|-- README.md
|-- docker-compose.yml
|-- requirements.txt
|-- schema.sql
`-- app/
    |-- __init__.py
    |-- config.py
    `-- main.py
```

## Local Setup

### 1. Prerequisites

- Python 3.10+
- Docker and Docker Compose

### 2. Environment Configuration

Copy the example environment file and configure your API keys:

```bash
cp .env.example .env
```

Set your `GEMINI_API_KEY` and confirm the database connection details.

### 3. Start Database (PostgreSQL + pgvector)

Start the database container using Docker Compose. The container automatically executes `schema.sql` on initial boot:

```bash
docker compose up -d
```

Verify that the database container is healthy:

```bash
docker compose ps
```

### 4. Install Dependencies

Create and activate a virtual environment, then install required dependencies:

```bash
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

### 5. Run the FastAPI Application

Start the development server with live reload:

```bash
uvicorn app.main:app --reload
```

The service will be accessible at:
- Service Info: `http://localhost:8000/`
- Health Check: `http://localhost:8000/health`
- Interactive API Docs: `http://localhost:8000/docs`

## Planned API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/ingest/{ticker}` | Ingest and chunk SEC filings and market news for a ticker |
| POST | `/research/chat` | Multi-turn conversational research with agent tool calling |
| GET | `/sessions/{session_id}` | Retrieve research session history, watchlist, and preferences |
| GET | `/documents/stats` | Retrieve document counts, filing metadata, and vector storage stats |

## Evaluation Benchmarks

The planned evaluation suite benchmarks both retrieval accuracy and response faithfulness:

| Metric | Target | Description |
|---|---|---|
| Recall@5 | >= 0.85 | Top-5 retrieval recall across SEC filing sections and disclosures |
| MRR (Mean Reciprocal Rank) | >= 0.75 | Reciprocal rank of the most relevant document chunk |
| Faithfulness | >= 0.90 | Claim verification score evaluating absence of financial hallucination |
