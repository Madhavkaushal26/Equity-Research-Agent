# Agents and structured outputs: an assistant with tools and an answer form

Imagine asking an assistant to write a report. A plain chatbot can draft an answer immediately. An agent can first request a filing-cabinet search, consult a market-data service, and update your preference notebook. The application controls which actions are available.

**Follow the code:** [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>), the module-level `research_agent`, the three decorated tool functions, and `run_research_turn()`.

## 1. What the agent loop actually does

Think of the model handing Python a request slip: "Call this function with these arguments." The model does not directly execute Python or receive unrestricted shell access. PydanticAI interprets an allowed tool request, invokes the function, and sends its result back to the model.

```text
User message + stored context
             |
             v
            LLM
             |
       tool request?
        /         \
      yes          final structured answer
       |                     |
Python executes tool         v
       |                validation
       v                 /       \
tool result -> LLM     retry      accepted brief
```

**In `research_agent`:** `model=f"google-gla:{settings.GEMINI_MODEL}"` selects the provider/model, `deps_type=AgentDeps` declares runtime dependencies, and `output_type=ResearchBrief` declares the answer contract. `defer_model_check=True` delays model checking rather than requiring it during module import. Dependencies are like the assistant's assigned desk: `AgentDeps` carries the database session, session ID, ticker restriction, retrieved evidence, and database-access lock.

The system prompt tells the model how to work, including searching before claims and treating retrieved text as data. Instructions influence model behavior; Python validation and tool code enforce the concrete checks described below.

## 2. The three authorized tools

Each tool is a particular device on the assistant's desk. All three are decorated with `@research_agent.tool` in `app/agent.py`.

| Desk device | Exact function | Behavior |
|---|---|---|
| Filing-cabinet search | `hybrid_research_search()` | Calls `retrieval.search_documents()`, enforces the request's ticker filter, marks that search happened, and records retrieved documents by ID |
| Market-data terminal | `fetch_live_fundamentals()` | Runs yfinance's blocking `get_info()` in a worker thread and returns price, market cap, trailing/forward P/E, 52-week high/low, and revenue growth |
| Preference notebook | `update_investor_profile()` | Normalizes watchlist symbols, validates risk tolerance and focus metrics, and calls `sessions.save_profile()` |

A P/E ratio compares stock price with earnings per share; market cap is the market value of the company's equity. These are source-provided values here, not independently calculated or audited financial figures. Missing or non-finite numeric values become `None` rather than invented numbers.

The profile tool accepts risk tolerance `conservative`, `moderate`, or `aggressive`, and focus metrics `margins`, `revenue growth`, `FCF`, or `P/E`. FCF means free cash flow. The tool saves complete updated lists; it does not automatically append every new list to the old one. The prompt tells the model to preserve preferences the user has not changed.

> [!NOTE]
> Live Yahoo metrics have no `market_documents` ID. The prompt tells the agent to attribute them in the summary, not invent a filing citation. A catalyst or risk still needs a retrieved document citation. A model can also fail to call a relevant optional tool; the code does not have a separate semantic detector proving every valuation question triggered fundamentals lookup.

## 3. Memory is a notebook we reopen

A tutor remembers your preferences because someone gives them the notebook again, not because their brain is retrained after every lesson.

**In `run_research_turn()`:** `sessions.ensure_session()` creates or loads the session and locks its row. The prompt includes its watchlist, risk tolerance, focus metrics, and the last 12 stored message entries, representing up to six user/assistant pairs created by this application.

After success, `sessions.append_turn()` stores the user's message and the assistant's executive summary. It does not store the full brief or all tool messages in `message_history`. Full history remains in PostgreSQL, while only the recent window goes into the next prompt.

**Read the persistence functions:** [app/sessions.py](<C:/Users/madha/Desktop/ELIP/app/sessions.py>), `ensure_session()`, `get_session(lock=True)`, `save_profile()`, and `append_turn()`.

## 4. Structured output is a checked answer sheet

A form can require a name, a date, and a number in the right boxes. It cannot prove that the person filling it out told the truth.

**In [app/models.py](<C:/Users/madha/Desktop/ELIP/app/models.py>):** `StrictModel` sets `extra="forbid"`, strict validation, and disallows non-finite numbers. `ResearchBrief` requires these fields:

```text
ResearchBrief
  query_intent: string
  executive_summary: string
  bull_catalysts: list[CatalystItem]
  bear_risks: list[CatalystItem]
  cited_sources: list[SourceCitation]
  confidence_score: number from 0.0 to 1.0

CatalystItem                         SourceCitation
  title                               doc_id
  impact_summary                      ticker, doc_type, filed_at
  metric_or_evidence                  source_url
  source_id ----------------------->  excerpt
```

`ChatRequest` checks the incoming session ID, message, and optional ticker-filter field; its `reject_blank()` validator rejects whitespace-only input. `ChatResponse` wraps the brief and the current profile. A field typed as `str`, such as `source_url`, is not automatically a validated URL just because its name sounds like one.

## 5. Citation validation adds an evidence check

A teacher can check that a cited page exists and that a quoted sentence really appears there. That is stronger than checking the answer form, but still different from checking whether the sentence supports the student's conclusion.

**In `validate_evidence()`:**

1. A search must have happened during this turn.
2. Citations must have unique IDs among the documents actually retrieved this turn.
3. Ticker, type, date, and URL must exactly match those retrieved records.
4. Each excerpt must be a nonempty, exact substring of its document.
5. Each catalyst/risk `source_id` must appear among the citations.
6. If no documents were retrieved, confidence must be zero.

On a mismatch, `ModelRetry` gives feedback so the model can correct its output. The configured agent retry limit is four. No separate rule proves that every summary number follows logically from its cited passage. That remaining question is why [[05_API_and_Evals]] includes a faithfulness judge.

> [!TIP]
> The brief's `confidence_score` is generated by the model. It is not a calibrated probability, retrieval similarity, or the benchmark's faithfulness score. Keep these three numbers separate when explaining the project.

## 6. Locks and retries protect the notebook

If two assistants edit the same notebook page at once, one can erase the other's work. A row lock serializes turns for the same session; `AgentDeps.db_lock` serializes tool access to its shared `AsyncSession`. These protect different levels of concurrency.

If a provider temporarily fails, a savepoint is like a pencil mark you can erase before trying again. `run_research_turn()` makes up to three attempts for specified transient HTTP statuses, including 429 and 503. Each attempt has fresh evidence tracking and a `db.begin_nested()` savepoint, so failed-attempt database tool writes roll back. History is appended only after success.

The model-run block is bounded by `asyncio.timeout(180)`, and each attempt uses `UsageLimits(request_limit=15)`. The 180-second block begins after session acquisition; it is not a blanket timeout for every earlier database wait. Final request commit/rollback belongs to `get_db()` in [app/database.py](<C:/Users/madha/Desktop/ELIP/app/database.py>).

**Verification:** [tests/test_backend.py](<C:/Users/madha/Desktop/ELIP/tests/test_backend.py>), `AgentTests.test_real_agent_tool_cycle_and_history()`, `test_citations_require_search_and_exact_evidence()`, and `test_transient_provider_failure_retries_without_duplicate_history()`.

Next: [[05_API_and_Evals]]. Related: [[03_Hybrid_Search]].
