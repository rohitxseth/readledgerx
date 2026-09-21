# Table shapes for building SQLAlchemy Core queries. The schema itself
# (constraints, defaults, indexes) is owned by init_db.sql; FetchedValue()
# only marks the ids the database generates.
from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    Boolean,
    Column,
    Date,
    FetchedValue,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("email", Text),
    Column("password_hash", Text),
    Column("auth_provider", Text),
    Column("is_active", Boolean),
    Column("last_login_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True)),
)

books = Table(
    "books",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("google_volume_id", Text),
    Column("title", Text),
    Column("subtitle", Text),
    Column("authors", ARRAY(Text)),
    Column("published_year", Integer),
    Column("description", Text),
    Column("page_count", Integer),
    Column("categories", ARRAY(Text)),
    Column("thumbnail_url", Text),
    Column("language", Text),
    Column("created_at", TIMESTAMP(timezone=True)),
)

reading_sessions = Table(
    "reading_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("book_id", UUID(as_uuid=True), ForeignKey("books.id")),
    Column("pages", Integer),
    Column("read_on", Date),
    Column("created_at", TIMESTAMP(timezone=True)),
)

chat_sessions = Table(
    "chat_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("name", Text),
    Column("metadata", JSONB),
    Column("message_count", Integer),
    Column("is_active", Boolean),
    Column("created_at", TIMESTAMP(timezone=True)),
    Column("updated_at", TIMESTAMP(timezone=True)),
)

chat_messages = Table(
    "chat_messages",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("session_id", UUID(as_uuid=True), ForeignKey("chat_sessions.id")),
    Column("role", Text),
    Column("content", Text),
    Column("message_type", Text),
    Column("ui_payload", JSONB(none_as_null=True)),
    Column("created_at", TIMESTAMP(timezone=True)),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id")),
    Column("action", Text),
    Column("details", JSONB),
    Column("created_at", TIMESTAMP(timezone=True)),
)
