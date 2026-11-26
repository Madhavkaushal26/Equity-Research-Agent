# APIs and evaluations: serving answers and grading the process

Imagine a service counter with labeled windows: one checks whether the building is open, one accepts reports, and one answers questions. FastAPI exposes those windows as HTTP routes.

**Follow the code:** [app/main.py](<C:/Users/madha/Desktop/ELIP/app/main.py>), `lifespan()` and the endpoint functions below.

## 1. Which window do I use?

| Window analogy | Route | Exact function and behavior |
|---|---|---|
| Is the filing room reachable? | `GET /health` | `health()` queries PostgreSQL for the installed vector extension version |
| Add reports to the cabinet | `POST /ingest/{ticker}` | `ingest()` validates the ticker and calls `ingest_ticker()` |
| Ask for a research brief | `POST /research/chat` | `chat()` accepts `ChatRequest`, calls `run_research_turn()`, and returns `ChatResponse` |
| Reopen my notebook | `GET /sessions/{session_id}` | `session_details()` returns profile, history, and update time, or 404 |
| Count the passage cards | `GET /documents/stats` | `document_stats()` counts chunks by ticker/type and totals them |
| Read the sign on the building | `GET /` | `root()` returns the service name and version |

The five core endpoints are accompanied by that root route. Interactive API documentation is at [localhost:8000/docs](http://localhost:8000/docs).

An example chat request is:

```json
{
  "session_id": "smoke-test",
  "message": "Summarize Nvidia's recent revenue drivers and key risks.",
  "ticker_filter": "NVDA"
}
```

Ingest first: chatting does not automatically populate missing ticker documents. A healthy database also does not prove Gemini or Yahoo is available. `database_error()`, `provider_error()`, and `timeout_error()` map relevant failures to 503, 502, and 504; invalid request bodies return 422.

> [!NOTE]
> CORS is like telling a browser which web pages may approach the counter. It is not a lock on the counter. `app.main` permits all origins and disables credentialed CORS, but implements no authentication. Session IDs identify records; they are not passwords. Public deployment needs access control and rate limits outside or inside this service.

## 2. Three different kinds of checks

A driving simulator, a road test, and a graded navigation exercise tell you different things.

| Analogy | Check | Location and recorded result |
|---|---|---|
| Simulator with controlled conditions | Regression tests use database/provider doubles and a real PydanticAI test-model loop | [tests/test_backend.py](<C:/Users/madha/Desktop/ELIP/tests/test_backend.py>): 28 tests passed |
| Real road test | Live HTTP requests use the real database and providers | [scripts/smoke_test.py](<C:/Users/madha/Desktop/ELIP/scripts/smoke_test.py>), `verify()`: health, ingestion, and chat returned 200 |
| Graded navigation exercise | Fixed research questions compare retrieval and judge generated answers | [eval.py](<C:/Users/madha/Desktop/ELIP/eval.py>), `evaluate()` |

The recorded database had pgvector 0.8.7. NVDA ingestion first inserted 17 chunks; a later run inserted four more and skipped 13 duplicates, leaving 21 NVDA chunks. The last recorded chat had three citations. `py_compile` passed on all 13 Python files, which proves syntax validity, not provider connectivity or research quality.

## 3. What the benchmark actually labels

Imagine grading a library search using a checklist of company names and words expected on useful pages. That is a cheap approximation to expert judgment, not an expert's full reading of each passage.

**In `BENCHMARK_QUERIES`:** `eval.py` defines four topics for each of AAPL, NVDA, and MSFT: revenue, margins, risks, and product catalysts. `relevant_document_ids()` labels a chunk relevant if its ticker matches and it contains at least one expected whole keyword phrase, case-insensitively.

`evaluate()` ingests any missing ticker, snapshots the corpus, and makes two searches for each of the 12 questions:

```text
Baseline: search_documents(..., ticker=None, top_k=5)
Hybrid:   search_documents(..., ticker=expected_ticker, top_k=5)
```

There were 59 chunks in the saved run: 19 AAPL, 21 NVDA, and 19 MSFT. Six questions had no relevant chunks under the labeling rule. Their metrics are `null` and are excluded from means; they are not silently counted as successes. All 24 search calls still completed.

## 4. Recall@5: how many useful pages did we recover?

Suppose the library contains ten pages labeled useful, and your first five results contain three of them. You recovered `3 / 10 = 0.30` of all useful pages. That is **Recall@5**.

**In `retrieval_metrics()`:**

```text
Recall@5 = unique relevant chunks in the first five results
           ------------------------------------------------
           all relevant chunks in the corpus for that query
```

It is not precision. Precision@5 would ask how many of the five returned results were relevant, using a different denominator. `average_metric()` takes the mean of the non-null per-query recall values, so every eligible query contributes equally.

In the actual NVDA revenue case, both searches recovered three of five labeled chunks, giving recall 0.60. Across the six eligible questions, the mean was **0.4333** for both strategies. It is not a claim that 43.33% of every question was answered correctly.

## 5. MRR@5: how soon did the first useful page appear?

If the first useful book is the second one handed to you, your reciprocal rank is `1 / 2 = 0.5`. If it is third, the value is `1 / 3`. If no useful result appears in the first five, it is zero.

**In `retrieval_metrics()`:** the first relevant result within the five-result cutoff sets the reciprocal rank. `average_metric()` averages those values across eligible questions to get **Mean Reciprocal Rank**, or MRR@5.

The recorded mean rose from **0.3056** to **0.3333**. For the MSFT margin query, the first relevant hit moved from rank three to rank two. Recall was unchanged because the same useful chunk was still present. This illustrates how ranking can improve without recovering more relevant chunks. This small, weakly labeled sample does not establish statistical significance.

## 6. Faithfulness: did the answer stick to the supplied pages?

A second examiner reads the student's answer beside the exact pages the student received. The examiner asks whether the claims are supported, rather than judging how polished the writing sounds.

**In `evaluate()`:** five calls to `run_research_turn()` produce briefs. That function retains the actual retrieved documents and fundamentals in `db.info["last_research_evidence"]`. The judge receives those tool outputs plus the brief, not just the model-written citation excerpts.

`FaithfulnessJudgment` defines a score in `[0, 1]`, an explanation, and unsupported claims. `client.models.generate_content()` uses `response_json_schema=FaithfulnessJudgment.model_json_schema()`. The earlier `response_schema` path caused a real SDK/API compatibility error for `additional_properties`; this JSON Schema path fixed it while preserving local strict validation.

The five saved scores were `1.0, 0.8, 0.3, 1.0, 1.0`. Their mean is **0.8200**. The low individual score matters even though the average looks stronger.

> [!NOTE]
> Faithfulness is support relative to the supplied evidence, not guaranteed financial truth, answer completeness, or human-verified accuracy. The same `gemini-3.5-flash-lite` model generated and judged these briefs, so their errors may be correlated. The judge assigns zero when there are no substantive supported claims; an empty answer is not automatically a perfect score.

## 7. Exact recorded output, 2026-11-26

| Benchmark | Queries scored | Recall@5 | MRR@5 | Faithfulness |
|---|---:|---:|---:|---:|
| Baseline Vector-Only Search | 6/12 | 0.4333 | 0.3056 | N/A |
| Hybrid SQL + Vector Search | 6/12 | 0.4333 | 0.3333 | N/A |
| LLM-as-a-Judge | 5/5 | N/A | N/A | 0.8200 |

**Source:** [eval_results.json](<C:/Users/madha/Desktop/ELIP/eval_results.json>), and `print_table()` in `eval.py`. The run status was `complete` with an empty error list. Complete execution and complete evidence coverage are separate properties. `N/A` in this table means the metric does not apply to that benchmark row.

The saved generation/judge model was `gemini-3.5-flash-lite`, after the requested `gemini-3.8-flash` repeatedly returned capacity/timeout errors. Embeddings used `gemini-embedding-001`. `verify()` in [scripts/check_models.py](<C:/Users/madha/Desktop/ELIP/scripts/check_models.py>) checks live model availability before saving a working selection.

## 8. How to improve retrieval responsibly

Think of improving a library in this order: acquire missing books, make better cards, improve the catalog, then grade it with a better answer key.

| Improvement idea | Why it could help | Exact place to change or inspect |
|---|---|---|
| Include relevant quarterly reports and longer source sections | A latest-two 8-K/news sample can omit margins and risks | `_fetch_filings()` and its 30,000-character truncation in [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>) |
| Make chunk boundaries match financial sections | A metric and its explanation may be separated | `chunk_text()` in `app/ingest.py` |
| Add lexical candidates, then combine with vector candidates | Exact product names and accounting phrases may be missed by vector ranking | `search_documents()` in [app/retrieval.py](<C:/Users/madha/Desktop/ELIP/app/retrieval.py>) |
| Rerank a larger candidate pool before returning five | A stronger final scorer may promote evidence into the top five | The ranking stage inside `search_documents()` |
| Hand-label relevant passages for each question | Broad keyword matches and missing labels distort the benchmark | `BENCHMARK_QUERIES` and `relevant_document_ids()` in `eval.py` |

> [!TIP]
> Increasing returned results to ten measures Recall@10, not an improved Recall@5. You can retrieve a larger internal candidate pool and rerank it, but still return five when comparing Recall@5. Adding genuinely useful corpus passages can initially lower recall by increasing its denominator. Track coverage as well as recall, and compare strategies on the same frozen corpus and relevance labels.

These are proposed experiments, not features already implemented. Inspect failures, change one thing, and rerun the same evaluation. Avoid changing keyword labels merely to make a number larger.

## Repeat the checks

From the repository root:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m scripts.smoke_test --stage all
.venv\Scripts\python.exe eval.py
```

The first command uses controlled test data. The other two make live requests, may write database rows, and consume Gemini quota. `eval.py` writes full results to JSON, prints the Markdown table to stdout, reports progress on stderr, and exits nonzero for a partial or failed run.

Next: [[06_Elip_Interview_Cheat_Sheet]]. Related: [[03_Hybrid_Search]], [[04_Agent_and_Structured_Outputs]].
