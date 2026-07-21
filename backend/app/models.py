import datetime

from sqlalchemy import ForeignKey, String, Text, Boolean, Integer, DateTime, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


class User(Base):
    __tablename__ = "users"
    # sqlite_autoincrement: deleted ids are NEVER reused (monotonically increasing).
    # id==1 is the super admin (first sign-up), protected by business rule (no demote/block/delete).
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")  # "admin" | "user"
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    """Single-row (id=1) application settings."""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20), default="ollama")  # "ollama" | "openai"
    host: Mapped[str] = mapped_column(String(255), default="")  # for ollama; empty for openai
    port: Mapped[int] = mapped_column(Integer, default=11434)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # openai (e.g. https://api.openai.com/v1)
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)  # openai
    wol_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    wol_target: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class McpServer(Base):
    """A remote MCP server. Its tools are registered into the shared tool registry under
    `source="mcp:<id>"` (see tools/mcp_client.py).

    sqlite_autoincrement (unlike `servers`): a deleted id is never reused, so a stale probe
    entry can never be inherited by a different server that happens to get the same id —
    the bug `routers/servers.py` has to defend against with `_invalidate` on DELETE.
    """
    __tablename__ = "mcp_servers"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique because it becomes the tool-name namespace (`mcp__<slug>__<tool>`); two servers
    # with the same name would produce colliding tool names.
    name: Mapped[str] = mapped_column(String(100), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    # "http" = Streamable HTTP, "sse" = the older HTTP+SSE transport (Linear still uses it).
    transport: Mapped[str] = mapped_column(String(10), default="http")
    # The secret lives in its own column, deliberately NOT inside `headers`: `exclude_unset`
    # partial updates cannot express "this one value of the map is unchanged", so a map
    # round-tripped through the edit form with a masked secret would wipe it.
    secret: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Which header carries `secret` — servers differ: "Authorization" (GitHub, needs the
    # "Bearer " prefix) vs "CONTEXT7_API_KEY" (Context7, raw value).
    secret_header: Mapped[str] = mapped_column(String(100), default="Authorization")
    secret_prefix: Mapped[str] = mapped_column(String(20), default="Bearer ")
    # Extra non-secret headers, e.g. {"X-MCP-Readonly": "true", "X-MCP-Toolsets": "repos"}.
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, default=1)
    title: Mapped[str] = mapped_column(String(255), default="New Chat")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)  # base64 data-URI listesi (vision)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{name, text}] document attachments
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    server_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_per_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chat: Mapped["Chat"] = relationship(back_populates="messages")
