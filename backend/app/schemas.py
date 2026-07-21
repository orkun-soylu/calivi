import datetime

from pydantic import BaseModel, ConfigDict


class RegisterIn(BaseModel):
    email: str
    username: str
    password: str


class LoginIn(BaseModel):
    identifier: str  # email or username
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    role: str
    blocked: bool = False
    created_at: datetime.datetime


class UserUpdate(BaseModel):
    # Partial admin update: only the fields actually sent are applied.
    email: str | None = None
    username: str | None = None
    role: str | None = None  # "admin" | "user"
    blocked: bool | None = None


class AuthConfigOut(BaseModel):
    registration_enabled: bool


class SettingsUpdate(BaseModel):
    registration_enabled: bool | None = None


class AttachmentIn(BaseModel):
    name: str
    text: str  # extracted document text (injected into the model's context)


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str  # shown as a chip in the UI; the text itself is not returned


class ServerCreate(BaseModel):
    name: str
    type: str = "ollama"  # "ollama" | "openai"
    host: str = ""  # ollama
    port: int = 11434  # ollama
    base_url: str | None = None  # openai
    api_key: str | None = None  # openai


class ServerUpdate(BaseModel):
    # Partial update: only fields that were explicitly set are applied.
    # Omitting api_key keeps the existing key (exclude_unset).
    name: str | None = None
    type: str | None = None
    host: str | None = None
    port: int | None = None
    base_url: str | None = None
    api_key: str | None = None


class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str = "ollama"
    host: str | None = None
    port: int
    base_url: str | None = None
    has_api_key: bool = False  # the key itself is never returned
    status: str = "unknown"  # "up" | "down"
    models: list[str] = []
    vision_models: list[str] = []  # subset of models: those supporting images (vision)


class McpServerCreate(BaseModel):
    name: str
    url: str
    transport: str = "http"  # "http" (Streamable HTTP) | "sse" (older HTTP+SSE)
    secret: str | None = None
    secret_header: str = "Authorization"
    secret_prefix: str = "Bearer "
    headers: dict[str, str] | None = None
    enabled: bool = True
    tool_modes: dict[str, str] | None = None


class McpServerUpdate(BaseModel):
    # Partial update: only explicitly set fields are applied. Omitting `secret` keeps the
    # stored one (exclude_unset) — the same contract as ServerUpdate.api_key.
    name: str | None = None
    url: str | None = None
    transport: str | None = None
    secret: str | None = None
    secret_header: str | None = None
    secret_prefix: str | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None
    tool_modes: dict[str, str] | None = None


class McpToolOut(BaseModel):
    name: str  # the namespaced registry name
    raw_name: str = ""  # the server's own name — sent so the UI never re-parses the namespace
    description: str = ""
    read_only: bool = False
    mode: str = "auto"  # "off" | "auto" | "approve"


class McpServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    transport: str = "http"
    has_secret: bool = False  # the secret itself is never returned
    secret_header: str = "Authorization"
    secret_prefix: str = "Bearer "
    headers: dict[str, str] = {}
    enabled: bool = True
    tool_modes: dict[str, str] = {}
    status: str = "unknown"  # "up" | "down" | "disabled"
    error: str | None = None  # why it is down — shown as a tooltip in Settings
    tools: list[McpToolOut] = []  # every discovered tool, with its mode


class ApprovalDecision(BaseModel):
    approved: bool


class ChatCreate(BaseModel):
    title: str = "New Chat"


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    pinned: bool = False
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ChatUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    images: list[str] | None = None  # list of base64 data-URIs (images on a user message)
    attachments: list[AttachmentOut] | None = None  # document attachments (name only is returned)
    model_used: str | None
    server_used: str | None
    tokens_per_sec: float | None = None
    timestamp: datetime.datetime


class ChatDetailOut(ChatOut):
    messages: list[MessageOut] = []


class SendMessageIn(BaseModel):
    content: str
    images: list[str] = []  # base64 data-URI listesi (vision)
    attachments: list[AttachmentIn] = []  # document attachments (extracted text)
    server_id: int | None = None  # None → chosen by the caller
    model: str | None = None  # None → chosen by the caller (on server_id if given)
    use_tools: bool = False  # when on, the tool layer is offered to the model (it decides what to call)


class EditMessageIn(BaseModel):
    content: str
    images: list[str] | None = None  # None → existing images are kept
    server_id: int | None = None
    model: str | None = None
    use_tools: bool = False


class ForkIn(BaseModel):
    message_id: int
    content: str
    images: list[str] = []
    attachments: list[AttachmentIn] = []
    server_id: int | None = None
    model: str | None = None
    use_tools: bool = False
