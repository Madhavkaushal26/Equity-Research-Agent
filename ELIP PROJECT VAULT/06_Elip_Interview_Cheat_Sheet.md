# Interview cheat sheet: eight questions a founder might ask

Use each analogy to introduce the idea, then name the implementation and its limits. These answers describe the saved 2026-11-26 implementation and benchmark, not an imagined future system.

## 1. "What did you build, and why use RAG?"

**Analogy:** It is an open-book research assistant that must consult supplied pages before writing its answer.

**Answer:** I built an async equity-research backend that ingests SEC filings and Yahoo news, stores passage embeddings in PostgreSQL, retrieves evidence for a question, and uses a tool-calling Gemini agent to produce a typed research brief. RAG means retrieval-augmented generation: the retrieved evidence is added to the model's context. I did not train a custom model.

**Point to:** [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>), `ingest_ticker()`; [app/retrieval.py](<C:/Users/madha/Desktop/ELIP/app/retrieval.py>), `search_documents()`; [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>), `run_research_turn()`.

**Limit:** Evidence access reduces reliance on remembered information, but a model can still misinterpret a passage. See [[00_START_HERE]].

## 2. "Why 768-dimensional embeddings and pgvector?"

**Analogy:** Each passage receives coordinates on a meaning map, and PostgreSQL stores the map coordinates next to the passage card.

**Answer:** `embed_texts()` requests 768 coordinates from `gemini-embedding-001`, matching the existing `vector(768)` database column. pgvector supplies vector storage and cosine-distance operators within PostgreSQL, so metadata filters and semantic ranking can share a query. The dimensions are model-generated features, not 768 named financial indicators.

**Point to:** [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>), `embed_texts()`; [schema.sql](<C:/Users/madha/Desktop/ELIP/schema.sql>), `market_documents` and `idx_market_docs_embedding`.

**Limit:** We did not benchmark other dimensions or prove that 768 is optimal. An HNSW index exists, but we did not measure its query-plan utilization or latency advantage. Changing embedding models requires re-embedding, even if dimensions stay equal. See [[01_Setup_and_Database]].

## 3. "What exactly is hybrid about your search?"

**Analogy:** We select a company's shelf, then rank the passages by similarity to the question.

**Answer:** The current hybrid strategy combines SQL metadata constraints with vector ranking. `search_documents()` applies optional ticker/type filters and orders by `1 - cosine_distance`, returning up to `top_k` rows. There is no BM25 lexical fusion or reranker yet. Both the agent and evaluation script use this dedicated retrieval layer.

**Point to:** [app/retrieval.py](<C:/Users/madha/Desktop/ELIP/app/retrieval.py>), `search_documents()`; [eval.py](<C:/Users/madha/Desktop/ELIP/eval.py>), `evaluate()`.

**Limit:** Similarity is not a truth probability. Future fusion/reranking can preserve the function's result contract, but the supporting search indexes and performance still need engineering. See [[03_Hybrid_Search]].

## 4. "How do you prevent duplicate work and keep the API responsive?"

**Analogy:** Fingerprint each incoming card, and let the waiter take another order while a remote kitchen is working.

**Answer:** Ingestion removes repeated chunk hashes within the batch, queries existing SHA-256 hashes, embeds only new chunks in batches of 20, and uses a unique constraint plus `ON CONFLICT DO NOTHING` for race-safe insertion. SQLAlchemy/asyncpg and Gemini use async I/O. Blocking edgartools and yfinance calls run through `asyncio.to_thread()`.

**Point to:** [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>), `ingest_ticker()` and `embed_texts()`; [app/database.py](<C:/Users/madha/Desktop/ELIP/app/database.py>), `get_db()`.

**Limit:** Hashes deduplicate exact text, not similar passages. Hash uniqueness is global across tickers. Two concurrent ingestions can still pay for the same new embedding before one insert loses the uniqueness race. Async I/O does not remove provider quotas. See [[02_Ingestion_and_Embeddings]].

## 5. "What stops the agent from inventing citations or losing session state?"

**Analogy:** The assistant has a notebook and a teacher who checks its page references before accepting the report.

**Answer:** `AgentDeps` records this turn's retrieved evidence. `validate_evidence()` checks search use, citation IDs, exact source metadata, verbatim excerpts, and matching catalyst/risk source IDs. `ResearchBrief` validates the output shape. Session profiles and history live in PostgreSQL; the prompt includes up to six recent user/assistant pairs. Row locks serialize turns for a session, and an asyncio lock protects the shared database session from concurrent tool access.

**Point to:** [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>), `AgentDeps`, `validate_evidence()`, `run_research_turn()`; [app/models.py](<C:/Users/madha/Desktop/ELIP/app/models.py>), `ResearchBrief`; [app/sessions.py](<C:/Users/madha/Desktop/ELIP/app/sessions.py>), `ensure_session()` and `append_turn()`.

**Limit:** Correct references and valid JSON do not prove every claim follows from its evidence. Session memory is stored context, not model training. The stored assistant history contains the executive summary, not the full brief. See [[04_Agent_and_Structured_Outputs]].

## 6. "What do the benchmark results actually prove?"

**Analogy:** We measured whether the librarian found useful pages and whether a second examiner thought the answer stayed faithful to those pages.

**Answer:** On a 59-chunk corpus, both retrieval strategies had mean Recall@5 of 0.4333. MRR@5 rose from 0.3056 to 0.3333 with ticker filtering. Five generated briefs had mean judge faithfulness 0.8200. All 24 searches and five brief/judge pairs completed, but only six of the twelve queries had relevant chunks under the keyword-label rule and contributed to retrieval means.

**Point to:** [eval.py](<C:/Users/madha/Desktop/ELIP/eval.py>), `relevant_document_ids()`, `retrieval_metrics()`, `average_metric()`, and `evaluate()`; [eval_results.json](<C:/Users/madha/Desktop/ELIP/eval_results.json>).

**Limit:** This is a small, weakly labeled benchmark with incomplete evidence coverage. The generator and judge were the same model. Do not call 0.8200 "82% financial accuracy" or describe the MRR difference as statistically proven. See the worked examples in [[05_API_and_Evals]].

## 7. "What failed in the live setup, and how did you fix it?"

**Analogy:** A real test drive found a blocked parking space, a busy service counter, and an incompatible form.

**Answer:** A separate Windows PostgreSQL service held port 5432; it was stopped with approval before starting Docker PostgreSQL. The requested `gemini-3.8-flash` repeatedly returned capacity/timeout errors, so live model discovery and probes selected `gemini-3.5-flash-lite`. The judge's `response_schema` path sent an unsupported `additional_properties` field; switching to `response_json_schema` fixed the request. Research turns gained bounded transient-HTTP retries with savepoints and more precise citation-correction feedback.

**Point to:** [scripts/check_models.py](<C:/Users/madha/Desktop/ELIP/scripts/check_models.py>), `verify()`; [scripts/start_server.ps1](<C:/Users/madha/Desktop/ELIP/scripts/start_server.ps1>), its managed startup/restart logic; [eval.py](<C:/Users/madha/Desktop/ELIP/eval.py>), `evaluate()`; [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>), `run_research_turn()` and `validate_evidence()`.

**Proof:** The final smoke checks returned 200 for health, ingestion, and chat; the last chat had three citations. There were 28 passing regression tests and 13 successfully compiled Python files. These are recorded results, not a claim of uninterrupted future uptime. See [[01_Setup_and_Database]] and [[05_API_and_Evals]].

## 8. "What would you prioritize before scaling this into a public product?"

**Analogy:** Before hiring more librarians, stock the missing books, verify the answer key, and put controlled access on the library door.

**Answer:** First improve source coverage and hand-label a larger representative evaluation set. Then compare section-aware chunking, lexical/vector fusion, and reranking on a frozen corpus. For operation, add authentication, rate limits, observability, and managed ingestion jobs. Measure query plans and latency before claiming an index or new search method improved performance.

**Point to:** `_fetch_filings()` and `chunk_text()` in [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>); `search_documents()` in [app/retrieval.py](<C:/Users/madha/Desktop/ELIP/app/retrieval.py>); `BENCHMARK_QUERIES` in [eval.py](<C:/Users/madha/Desktop/ELIP/eval.py>); CORS configuration and route handlers in [app/main.py](<C:/Users/madha/Desktop/ELIP/app/main.py>).

**Limit:** These are future priorities. The current app has permissive CORS and no authentication, no lexical fusion, no reranker, and no streaming route. Serving more candidates changes the recall cutoff unless we still score the final five. Increasing corpus coverage can initially lower recall by increasing the relevance denominator, so track coverage and ranking together.

> [!TIP]
> Practice this answer pattern: analogy, implementation, evidence, limitation. Naming a function and acknowledging what the test did not prove is more convincing than saying the system is "fully autonomous" or "hallucination-free."

Return to [[00_START_HERE]]. For the exact table, open [[05_API_and_Evals]].
