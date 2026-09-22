CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new',
    chunks_count INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id         TEXT PRIMARY KEY,
    doc_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    metadata   JSONB NOT NULL DEFAULT '{}',
    suspicious BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks (doc_id);
