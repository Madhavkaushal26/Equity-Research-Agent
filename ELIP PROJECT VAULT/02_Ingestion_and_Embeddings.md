# Ingestion and embeddings: making a searchable card catalog

Imagine a librarian receiving long reports, cutting useful passages into index cards, discarding identical cards, and assigning each card coordinates on a topic map. That is this repository's ingestion pipeline.

**Follow the code:** [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>), `ingest_ticker()`, coordinates the process. [app/main.py](<C:/Users/madha/Desktop/ELIP/app/main.py>), `ingest()`, exposes it as `POST /ingest/{ticker}`.

```text
ticker -> normalize -> fetch documents -> chunks -> content hashes
                                                     |
                                              remove duplicates
                                                     |
                                              embed new chunks
                                                     |
                                              insert + metadata
```

## 1. Receiving the reports

Two couriers bring different kinds of evidence. SEC filings are company regulatory disclosures; Yahoo news supplies reporting and summaries.

**In `app/ingest.py`:**

- `normalize_ticker()` uppercases and trims the symbol, then validates its characters and length.
- `_fetch_filings()` calls `edgar.Company(ticker).get_filings(form=["10-Q", "8-K"]).latest(2)`. A 10-Q is a quarterly report; an 8-K reports specified current events. This selects the latest **two total** matches, not two of each form. Both can be 8-Ks.
- Each filing's `.text()` is truncated to 30,000 characters before chunking. An individual filing failure is logged; news ingestion still proceeds.
- `_fetch_news()` reads at most ten entries from `yf.Ticker(ticker).news`. It handles nested `content` dictionaries and older top-level fields. It combines title and available summary/description, not a full article downloaded from the news URL.
- `_as_datetime()` standardizes source times to timezone-aware UTC values. News without usable text, a valid URL, or a usable publication date is skipped.

> [!NOTE]
> This is a limited evidence collection. The measured 59-chunk corpus contained 8-K and news chunks, with no 10-Q chunks. A latest-two selection, a filing truncation, and short news summaries can miss the very paragraph a question needs.

## 2. Cutting reports into overlapping cards

If you cut a recipe between the ingredient and its amount, both halves become confusing. Overlapping cuts repeat a little context near each boundary.

**In `chunk_text(text, chunk_size=1500, overlap=200)`:** whitespace is cleaned, paragraph separation is retained, and the splitter prefers paragraph, sentence, then word boundaries near the end of a chunk. A long unbroken stretch can be split at the character limit. The next slice starts with character overlap; trimming whitespace can affect the visible overlap.

```text
Original:  [--------------- long document ----------------]
Chunk A:   [first section----------]
Chunk B:                  [-------next section----------]
                          repeated context
```

The limits are **characters**, not words, tokens, or sentences. More overlap can preserve context but also stores repeated material and consumes more embedding calls and prompt space. Chunking changes what retrieval can select, so treat chunk-size changes as an experiment.

## 3. Rejecting exact duplicate cards

A fingerprint helps identify the same card without comparing every character each time. SHA-256 computes a deterministic digest from the chunk's bytes.

**In `ingest_ticker()`:** the digest is `hashlib.sha256(chunk.encode()).hexdigest()`. A dictionary removes repeats within the current fetched batch. A SQL query finds hashes already stored in `market_documents`; only unseen chunks are sent for embedding.

The final insert uses `ON CONFLICT (content_hash) DO NOTHING`. Think of two librarians simultaneously checking for a missing card: both might see it as absent, but the unique database constraint still allows only one insertion. Returned metrics count successful inserts and treat conflicting inserts as duplicates.

> [!NOTE]
> A content hash detects exact equality, not similar meaning. A changed number produces a different hash. Uniqueness is global in [schema.sql](<C:/Users/madha/Desktop/ELIP/schema.sql>), so identical text attached to two tickers is stored only once under this schema. Re-ingestion is safe, but newly changed news can still add rows.

## 4. Giving text coordinates on a meaning map

On a city map, nearby coordinates suggest nearby places. An **embedding** places text in a learned numerical space where related passages often have similar directions. "Sales increased" may be close to "revenue grew" even though the words differ.

**In `embed_texts()`:** the Google GenAI async client calls `client.models.embed_content()` using `settings.EMBEDDING_MODEL`, with `EmbedContentConfig(output_dimensionality=768)`. It sends batches of at most 20 texts, checks the returned count, and rejects vectors with the wrong length, non-finite numbers, or all-zero values.

You can picture a vector as `[0.12, -0.07, 0.31]` for a three-coordinate toy example. The real result has 768 coordinates. Individual coordinates do not come with dependable labels such as "profit" or "risk." The representation supports comparison; it is not a truth score and does not verify financial facts.

No custom training happens here. The embedding service computes a representation using an already-trained model. The research-generation model is a separate role: it produces the answer after retrieval.

> [!TIP]
> Both documents and questions use the same `embed_texts()` function. If you change the embedding model, re-embed the corpus and evaluate again. Two models can each produce 768 numbers while using incompatible coordinate systems.

## 5. Filing the cards in PostgreSQL

A card needs both its topic coordinates and its original text, so a librarian can find it and then read it.

**In `ingest_ticker()`:** each row stores content and metadata alongside the vector. The vector is serialized as `f"[{','.join(map(str, vec))}]"`, and SQL uses `CAST(:embedding AS vector)`. Values are passed as bound parameters. This is the repository's required vector-casting convention.

```text
One market_documents row
+-----------+--------------------------+
| ticker    | NVDA                     |
| doc_type  | 8-K or news               |
| content   | original chunk text      |
| hash      | SHA-256 digest           |
| embedding | 768 numeric coordinates  |
| source    | URL + source date        |
+-----------+--------------------------+
```

## 6. Why async does not mean every library is async

A waiter can take another order while one dish cooks. Async I/O lets the event loop serve other work while an operation is waiting.

**In `ingest_ticker()`:** `asyncio.gather()` starts the filing and news fetch paths together; `asyncio.to_thread()` moves their blocking SDK calls off the event-loop thread. Embeddings and database calls use async clients directly. Threads do not remove remote rate limits or make expensive CPU work magically free.

**Verification to inspect:** [tests/test_backend.py](<C:/Users/madha/Desktop/ELIP/tests/test_backend.py>), `IngestionTests`, checks batching, duplicates, nested news data, and SEC failure isolation. `ChunkAndContractTests.test_long_text_coverage_overlap_and_limits()` checks that splitting does not lose the tested text.

Next: [[03_Hybrid_Search]]. Related: [[01_Setup_and_Database]].
