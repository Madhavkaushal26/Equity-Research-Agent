# Hybrid search: choose the shelf, then the closest passages

Imagine asking a librarian for NVIDIA revenue evidence. First the librarian chooses the NVIDIA shelf. Then they look for passages about revenue, even if the passages say "sales" instead. This is ELIP's current combination of metadata filtering and semantic ranking.

**Follow the code:** [app/retrieval.py](<C:/Users/madha/Desktop/ELIP/app/retrieval.py>), `search_documents(db, query, ticker=None, doc_type=None, top_k=6)`.

## Three kinds of search

| Analogy first | Technique | Where it exists here |
|---|---|---|
| Find the exact words in a book's index | Keyword or lexical search matches terms; BM25 is a common lexical scoring method | No BM25 retrieval is implemented. `relevant_document_ids()` in [eval.py](<C:/Users/madha/Desktop/ELIP/eval.py>) uses keyword rules for evaluation labels only |
| Find books discussing a similar idea | Vector search compares question and passage embeddings | `search_documents()` with no ticker constraint |
| Pick the right shelf before comparing ideas | SQL filters plus vector ranking | `search_documents()` with a ticker and/or document-type constraint |

> [!NOTE]
> "Hybrid" often means combining lexical and vector result lists. In this repository it specifically means **SQL metadata filters plus vector similarity**. It does not currently mean BM25 fusion. Do not describe the benchmark as proving a lexical/vector fusion system.

## The actual query path

Like checking a library request before retrieving books, `search_documents()` rejects blank queries and requires integer `top_k` values from 1 to 50. It normalizes a supplied ticker and adds optional SQL predicates.

The function calls `embed_texts([query])` in [app/ingest.py](<C:/Users/madha/Desktop/ELIP/app/ingest.py>) for the question's 768-dimensional vector. Then it sends bound parameters to this SQL shape:

```sql
SELECT id AS doc_id, ticker, doc_type, filed_at, source_url, content,
       1 - (embedding <=> CAST(:query_vec AS vector)) AS similarity
FROM market_documents
WHERE UPPER(ticker) = :ticker
ORDER BY similarity DESC, id ASC
LIMIT :top_k;
```

This illustrates the ticker-filtered branch. The actual function adds a `doc_type` predicate when requested and uses `WHERE TRUE` if no metadata filter is supplied.

```text
Question -> question vector
                    |
All stored chunks -> allowed ticker/type rows -> similarity order -> top_k
```

The filters constrain the eligible rows before the final ranking and limit in the query's logical meaning. PostgreSQL chooses the physical execution plan, so this description is not a claim about its exact scan strategy.

## Cosine distance without the mystery

Picture two arrows drawn from the same starting point. Arrows pointing in nearly the same direction have high cosine similarity, even if their lengths differ.

**In `search_documents()`:** pgvector's `<=>` operator calculates cosine distance. The function converts distance into similarity with `1 - distance`, so larger values sort first.

```text
cosine similarity = dot(a, b) / (length(a) * length(b))
cosine distance   = 1 - cosine similarity

distance 0.10 -> similarity 0.90
distance 0.45 -> similarity 0.55
```

For nonzero vectors, cosine similarity is between -1 and 1. A value of 0.90 is a geometric comparison, not a 90% probability that a passage is relevant or true. The embedding function rejects zero vectors, which would make this direction comparison invalid.

## What comes back

A librarian returns both a page and its catalog reference. `search_documents()` returns dictionaries containing `doc_id`, `ticker`, `doc_type`, `filed_at`, `source_url`, `similarity`, and `content`. Dates are serialized with `.isoformat()`.

The agent receives passage text for reasoning and metadata for citations. The default agent search returns up to six chunks. The benchmark explicitly requests five. The current implementation does not impose a minimum similarity threshold or freshness cutoff; source dates are returned but not used as a recency ranking boost.

**Next caller:** `hybrid_research_search()` in [app/agent.py](<C:/Users/madha/Desktop/ELIP/app/agent.py>) records the retrieved documents and enforces a request-level ticker constraint, even if the model suggests a different ticker.

## Speed and future extensions

An express-route map can speed up navigation, but owning the map does not prove you took the express route. [schema.sql](<C:/Users/madha/Desktop/ELIP/schema.sql>) defines an HNSW cosine index. This query orders by a computed similarity expression, and no query-plan performance result was recorded. Check the plan before claiming HNSW acceleration.

For future improvements, think of two librarians returning lists, followed by a careful editor:

- **Fusion** combines lexical and vector candidate lists. A future BM25 implementation belongs behind `search_documents()`; the API and returned document shape can stay stable, although a lexical index or supporting search infrastructure may be needed.
- **Reranking** has a second scorer compare the question with candidate passages more carefully. It can reorder a larger candidate set before returning the final five or six.
- **Benchmarking** checks whether the extra work helped. Both the agent and `eval.py` already call this same retrieval function, so they can evaluate the same implementation.

> [!TIP]
> A better librarian cannot retrieve a page the library never received. Check evidence coverage before tuning similarity. The measured recall limit is explained in [[05_API_and_Evals]].

Next: [[04_Agent_and_Structured_Outputs]]. Return to [[00_START_HERE]].
