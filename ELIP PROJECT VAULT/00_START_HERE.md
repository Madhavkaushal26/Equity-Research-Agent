# Start here: an open-book research assistant

Imagine two students taking an exam. One answers from memory: a **closed-book exam**. The other first finds the relevant pages, reads them, and cites them: an **open-book exam**. ELIP tries to make an AI assistant behave like the second student.

**Follow the code:** [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>), `run_research_turn()`, asks the model to use tools. Its `hybrid_research_search()` tool calls [app/retrieval.py](<C:/Users/madha/Desktop/ELIP/app/retrieval.py>), `search_documents()`, to find evidence.

ELIP is the Autonomous Equity & Earnings Research Agent. You ask about a company, and it returns a structured brief with an executive summary, possible positive catalysts, risks, and citations. A ticker is a company's market symbol, such as `NVDA` for NVIDIA.

## The smallest useful vocabulary

Each analogy introduces a term you will see in the code.

| Everyday analogy | Concept | Exact location |
|---|---|---|
| A very capable text-completion assistant | **LLM**, or large language model: generates text and tool requests from the supplied context | `research_agent` in [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>) |
| Coordinates on a map of meaning | **Embedding**: a list of numbers representing text for comparison | `embed_texts()` in [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>) |
| A librarian finding relevant pages | **Retrieval**: selecting stored passages for a question | `search_documents()` in [app/retrieval.py](<C:/Users/madha/Desktop/ELIP/app/retrieval.py>) |
| Giving the student those pages before the answer | **RAG**, retrieval-augmented generation: retrieval feeds evidence into generation | `hybrid_research_search()` and `run_research_turn()` in `app/agent.py` |
| An assistant allowed to use a calculator and filing cabinet | **Agent**: the model can request defined functions and use their results | The three `@research_agent.tool` functions in `app/agent.py` |
| An answer sheet with required boxes | **Structured output**: a checked JSON-shaped response | `ResearchBrief` in [app/models.py](<C:/Users/madha/Desktop/ELIP/app/models.py>) |

The LLM works with tokens, which are pieces of text that can be shorter than a word. This repository chunks documents by **characters**, not tokens. It uses an existing model; it does not train or fine-tune that model on the filings.

## Full system map

```text
PREPARE THE OPEN BOOK

POST /ingest/{ticker}
          |
          v
   ingest_ticker()
      /       \
     v         v
SEC filings   Yahoo news titles + summaries
     \         /
      v       v
     chunk_text()
          |
          v
SHA-256 hash + duplicate check
          |
          v
Gemini embedding model: 768 numbers per new chunk
          |
          v
PostgreSQL + pgvector: market_documents


ANSWER A QUESTION

POST /research/chat
          |
          v
ChatRequest -> run_research_turn() <-> user_sessions
                         |             profile + history
                         v
                 Gemini research agent
                         |
           +-------------+------------------+
           |             |                  |
           v             v                  v
 hybrid_research_   fetch_live_       update_investor_
 search()          fundamentals()    profile()
           |             |                  |
           v             v                  v
 search_documents()   Yahoo Finance      PostgreSQL
           |
    Embed the question
           |
    SQL filters + cosine ranking
           |
           +---- evidence back to agent ----+
                         |
                         v
            ResearchBrief + validate_evidence()
                         |
                         v
          Save user message + assistant summary
                         |
                         v
                 ChatResponse JSON

MEASURE IT

eval.py -> same search_documents() + run_research_turn()
        -> retrieval metrics + Gemini faithfulness judge
        -> eval_results.json + Markdown table
```

## Reading roadmap

Read these in order, then use the final note for revision:

1. [[01_Setup_and_Database]]: where the application, settings, and data live.
2. [[02_Ingestion_and_Embeddings]]: how source text becomes searchable chunks.
3. [[03_Hybrid_Search]]: how the system chooses passages for a question.
4. [[04_Agent_and_Structured_Outputs]]: how the model uses tools and returns checked JSON.
5. [[05_API_and_Evals]]: how to call the backend and interpret the measured results.
6. [[06_Elip_Interview_Cheat_Sheet]]: eight questions to practice explaining aloud.

> [!NOTE]
> An open book does not guarantee a correct answer. The assistant can select weak evidence or misinterpret a valid passage. JSON validation, citation validation, and faithfulness evaluation check different things.

## What was actually demonstrated

Think of a test drive: it proves the car completed that route, not every possible road condition. The recorded live checks on **2026-11-26** returned HTTP 200 for health, NVDA ingestion, and research chat. The last chat had three citations. The saved benchmark used 59 chunks, completed 24 searches and five brief/judge pairs, and reported mean faithfulness of 0.8200.

**Evidence:** [scripts/smoke_test.py](<C:/Users/madha/Desktop/ELIP/scripts/smoke_test.py>), `verify()`; [eval.py](<C:/Users/madha/Desktop/ELIP/eval.py>), `evaluate()`; and [eval_results.json](<C:/Users/madha/Desktop/ELIP/eval_results.json>). The 28 regression tests passed, and all 13 project Python files compiled during the previous implementation work. This vault describes those recorded checks; writing these notes did not rerun paid model calls.

> [!TIP]
> Open `C:\Users\madha\Desktop\ELIP\ELIP PROJECT VAULT` as an Obsidian vault and begin here. Note-to-note navigation uses wikilinks. Code references name the exact symbol and point to the actual source file outside the vault. Search that symbol in your code editor while reading.
