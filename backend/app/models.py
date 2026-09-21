from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()


users = Table(
    "users",
    metadata,
    Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    ),
    Column("email", Text, unique=True, nullable=False),
    Column("password_hash", Text, nullable=True),
    Column("auth_provider", Text, nullable=False, server_default="local"),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("last_login_at", TIMESTAMP(timezone=True), nullable=True),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    ),
    CheckConstraint("auth_provider IN ('local', 'google')", name="chk_auth_provider"),
)


books = Table(
    "books",
    metadata,
    Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    ),
    Column("google_volume_id", Text, unique=True, nullable=False),
    Column("title", Text, nullable=False),
    Column("subtitle", Text, nullable=True),
    Column("authors", ARRAY(Text), nullable=True),
    Column("published_year", Integer, nullable=True),
    Column("description", Text, nullable=True),
    Column("page_count", Integer, nullable=True),
    Column("categories", ARRAY(Text), nullable=True),
    Column("thumbnail_url", Text, nullable=True),
    Column("language", Text, nullable=True),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    ),
    CheckConstraint("page_count IS NULL OR page_count > 0", name="chk_page_count"),
    CheckConstraint(
        "published_year IS NULL OR (published_year >= 1000 AND published_year <= 2100)",
        name="chk_published_year",
    ),
)

Index("idx_books_title", text("LOWER(title)"))


reading_sessions = Table(
    "reading_sessions",
    metadata,
    Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "book_id",
        UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("pages", Integer, nullable=False),
    Column("read_on", Date, nullable=False),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    ),
    CheckConstraint("pages >= 0", name="chk_pages_positive"),
)

Index("idx_reading_sessions_user_id", reading_sessions.c.user_id)
Index("idx_reading_sessions_book_id", reading_sessions.c.book_id)
Index("idx_reading_sessions_read_on", reading_sessions.c.read_on)
Index("idx_rs_user_book", reading_sessions.c.user_id, reading_sessions.c.book_id)

# Chat tables

chat_sessions = Table(
    "chat_sessions",
    metadata,
    Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("message_count", Integer, nullable=False, server_default="0"),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    ),
    Column(
        "updated_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    ),
)

Index("idx_chat_sessions_user_id", chat_sessions.c.user_id)


chat_messages = Table(
    "chat_messages",
    metadata,
    Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    ),
    Column(
        "session_id",
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=True),
    Column("message_type", Text, nullable=False, server_default="'text'"),
    Column("ui_payload", JSONB, nullable=True),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    ),
    CheckConstraint("role IN ('user', 'assistant')", name="chk_message_role"),
)

Index("idx_chat_messages_session", chat_messages.c.session_id)
