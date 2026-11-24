-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Market documents table with vector embeddings
CREATE TABLE IF NOT EXISTS market_documents (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(16) NOT NULL,
    doc_type VARCHAR(32) NOT NULL,
    filed_at TIMESTAMPTZ NOT NULL,
    source_url TEXT NOT NULL,
    content_hash VARCHAR(64) UNIQUE NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW vector cosine index for semantic similarity search
CREATE INDEX IF NOT EXISTS idx_market_docs_embedding
    ON market_documents
    USING hnsw (embedding vector_cosine_ops);

-- Composite index for fast metadata filtering and chronological sorting
CREATE INDEX IF NOT EXISTS idx_market_docs_meta
    ON market_documents (ticker, doc_type, filed_at DESC);

-- User sessions table for persistent context and research preferences
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id VARCHAR(128) PRIMARY KEY,
    watchlist JSONB DEFAULT '[]'::jsonb,
    risk_tolerance VARCHAR(32) DEFAULT 'moderate',
    focus_metrics JSONB DEFAULT '[]'::jsonb,
    message_history JSONB DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
