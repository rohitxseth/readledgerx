-- Initialize ReadLedger database schema (Production-Ready)
-- Run this on PostgreSQL to set up tables
-- Date: January 19, 2026

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- USERS TABLE: Authentication and user identity
-- Purpose: JWT-based auth with support for local and OAuth providers
-- ==============================================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,  -- NULL for OAuth users
    auth_provider TEXT NOT NULL DEFAULT 'local' CHECK (auth_provider IN ('local', 'google')),
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==============================================================================
-- BOOKS TABLE: Global canonical book catalog
-- Purpose: Canonicalized books using Google Books volumeId
-- ==============================================================================
CREATE TABLE IF NOT EXISTS books (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    google_volume_id TEXT UNIQUE NOT NULL,  -- Canonical identity
    title TEXT NOT NULL,
    subtitle TEXT,
    authors TEXT[],
    published_year INT CHECK (published_year >= 1000 AND published_year <= 2100),
    description TEXT,
    page_count INT CHECK (page_count > 0),
    categories TEXT[],
    thumbnail_url TEXT,
    language TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==============================================================================
-- READING_SESSIONS TABLE: one row per reading entry; progress is derived from
-- these rows, never stored
-- Purpose: Source of truth for reading activity
-- ==============================================================================
CREATE TABLE IF NOT EXISTS reading_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    pages INT NOT NULL CONSTRAINT reading_sessions_pages_check CHECK (pages >= 0),
    read_on DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==============================================================================
-- INDEXES: Performance optimization for common query patterns
-- ==============================================================================

-- Users: Implicit index on email via UNIQUE constraint

-- Books: Case-insensitive title search
CREATE INDEX IF NOT EXISTS idx_books_title ON books(LOWER(title));

-- Reading Sessions: Single-column indexes for basic queries
CREATE INDEX IF NOT EXISTS idx_reading_sessions_user_id ON reading_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_reading_sessions_book_id ON reading_sessions(book_id);
CREATE INDEX IF NOT EXISTS idx_reading_sessions_read_on ON reading_sessions(read_on);

-- Reading Sessions: Composite index for user+book queries
CREATE INDEX IF NOT EXISTS idx_rs_user_book ON reading_sessions(user_id, book_id);

-- ==============================================================================
-- CHAT_SESSIONS TABLE: Conversation sessions for the router-agent chat
-- Purpose: Persists multi-turn chat sessions per user
-- ==============================================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    message_count INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);

-- ==============================================================================
-- CHAT_MESSAGES TABLE: Individual messages within a chat session
-- Purpose: Stores user and assistant messages with optional BDUI payloads
-- ==============================================================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT,
    message_type TEXT NOT NULL DEFAULT 'text',
    ui_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(session_id, created_at ASC);

-- ==============================================================================
-- AUDIT_LOG TABLE: Tracks key user actions for observability
-- ==============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
