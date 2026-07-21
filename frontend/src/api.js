const BASE = "/api";

// Registers a global hook so that a dropped session (401) sends App back to the login screen.
let onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}
function handleUnauthorized(resp) {
  // A 401 from /auth/* itself (wrong password etc.) must not trigger a global logout.
  if (resp.status === 401 && onUnauthorized && !resp.url.includes("/api/auth/")) {
    onUnauthorized();
  }
}

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include", // httpOnly session cookie
    ...options,
  });
  if (!resp.ok) {
    handleUnauthorized(resp);
    throw new Error(`${resp.status} ${await resp.text()}`);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

// Reads the NDJSON body line by line and hands each line to onPiece as a {type,text} object.
async function streamNdjson(resp, onPiece) {
  if (!resp.ok) {
    handleUnauthorized(resp);
    throw new Error(`${resp.status} ${await resp.text()}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop(); // a possibly half-finished last line carries over to the next chunk
    for (const line of lines) {
      if (line) onPiece(JSON.parse(line));
    }
  }
  if (buffer) onPiece(JSON.parse(buffer));
}

// Converts the "auto" selection into the null the API expects.
function normalizeTarget(serverId, model) {
  return {
    server_id: serverId === "auto" ? null : serverId,
    model: model === "auto" ? null : model,
  };
}

export const api = {
  // Auth
  getAuthConfig: () => request("/auth/config"),
  register: (data) => request("/auth/register", { method: "POST", body: JSON.stringify(data) }),
  login: (data) => request("/auth/login", { method: "POST", body: JSON.stringify(data) }),
  logout: () => request("/auth/logout", { method: "POST" }),
  getMe: () => request("/auth/me"),

  // Update own profile / delete own account (self-service)
  updateMe: (data) => request("/users/me", { method: "PATCH", body: JSON.stringify(data) }),
  deleteMe: () => request("/users/me", { method: "DELETE" }),

  // User management (admin)
  listUsers: () => request("/users"),
  updateUser: (id, data) => request(`/users/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteUser: (id) => request(`/users/${id}`, { method: "DELETE" }),
  getSettings: () => request("/settings"),
  updateSettings: (data) => request("/settings", { method: "PATCH", body: JSON.stringify(data) }),

  listServers: () => request("/servers"),
  addServer: (data) => request("/servers", { method: "POST", body: JSON.stringify(data) }),
  updateServer: (id, data) => request(`/servers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteServer: (id) => request(`/servers/${id}`, { method: "DELETE" }),

  // MCP servers (admin only). `refresh=1` forces a live probe instead of the TTL cache —
  // an MCP probe opens a real session, so it is not something to do on every render.
  // Decide on a pending tool call; unblocks the stream that is still open.
  respondToApproval: (chatId, approvalId, approved) =>
    request(`/chats/${chatId}/approvals/${approvalId}`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),

  listMcpServers: (refresh) => request(`/mcp${refresh ? "?refresh=1" : ""}`),
  addMcpServer: (data) => request("/mcp", { method: "POST", body: JSON.stringify(data) }),
  updateMcpServer: (id, data) => request(`/mcp/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteMcpServer: (id) => request(`/mcp/${id}`, { method: "DELETE" }),

  getConfig: (name) => request(`/config/${name}`),
  getConfigDefault: (name) => request(`/config/${name}/default`),
  saveConfig: (name, content) => request(`/config/${name}`, { method: "PUT", body: JSON.stringify({ content }) }),

  listChats: () => request("/chats"),
  createChat: () => request("/chats", { method: "POST", body: JSON.stringify({ title: "New Chat" }) }),
  getChat: (id) => request(`/chats/${id}`),
  updateChat: (id, data) => request(`/chats/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteChat: (id) => request(`/chats/${id}`, { method: "DELETE" }),
  deleteMessage: (chatId, messageId) => request(`/chats/${chatId}/messages/${messageId}`, { method: "DELETE" }),

  // onPiece: {type:"thinking"|"content", text}
  // Extracts document text (PDF/docx/txt/code). Returns: {name, text, truncated}.
  async extractFile(file) {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${BASE}/extract`, { method: "POST", body: form, credentials: "include" });
    if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
    return resp.json();
  },

  async sendMessage(chatId, { content, images, attachments, serverId, model, useTools, signal }, onPiece) {
    const resp = await fetch(`${BASE}/chats/${chatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        content,
        images: images || [],
        attachments: attachments || [],
        use_tools: !!useTools,
        ...normalizeTarget(serverId, model),
      }),
      signal,
    });
    await streamNdjson(resp, onPiece);
  },

  // Edit a user message / reroute it to a different model → truncate + regen (same chat).
  async editMessage(chatId, messageId, { content, serverId, model, useTools, signal }, onPiece) {
    const resp = await fetch(`${BASE}/chats/${chatId}/messages/${messageId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ content, use_tools: !!useTools, ...normalizeTarget(serverId, model) }),
      signal,
    });
    await streamNdjson(resp, onPiece);
  },

  // Fork a new chat from history. onChatId(newId) comes from the header, then the stream flows.
  async forkChat(chatId, { messageId, content, serverId, model, useTools, signal }, onChatId, onPiece) {
    const resp = await fetch(`${BASE}/chats/${chatId}/fork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ message_id: messageId, content, use_tools: !!useTools, ...normalizeTarget(serverId, model) }),
      signal,
    });
    if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
    const newId = Number(resp.headers.get("X-Calivi-Chat-Id"));
    if (newId) onChatId(newId);
    await streamNdjson(resp, onPiece);
  },
};
