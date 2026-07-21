import { useState, useEffect, useCallback } from "react";
import StatusLight from "./StatusLight.jsx";
import { api } from "../api.js";
import { useT } from "../i18n.js";

// Extracts the user-facing message from a request() error ("STATUS body").
function errText(err) {
  const detail = String(err.message || "").replace(/^\d+\s*/, "");
  try {
    return JSON.parse(detail).detail || detail;
  } catch {
    return detail;
  }
}

// Well-known servers. This only prefills the form — the point is that each server carries its
// auth differently (Context7 wants a custom header with a raw value, GitHub wants
// `Authorization: Bearer`), and nobody should have to look that up to add one.
// GitHub is pinned to the server-enforced `/readonly` endpoint: the read-only guarantee then
// comes from GitHub, not from a tool annotation we chose to believe.
export const PRESETS = {
  context7: {
    name: "context7",
    url: "https://mcp.context7.com/mcp",
    transport: "http",
    secret_header: "CONTEXT7_API_KEY",
    secret_prefix: "",
    headers: {},
  },
  github: {
    name: "github",
    url: "https://api.githubcopilot.com/mcp/readonly",
    transport: "http",
    secret_header: "Authorization",
    secret_prefix: "Bearer ",
    headers: { "X-MCP-Toolsets": "repos,issues,pull_requests" },
  },
  exa: {
    name: "exa",
    url: "https://mcp.exa.ai/mcp",
    transport: "http",
    secret_header: "Authorization",
    secret_prefix: "Bearer ",
    headers: {},
  },
};

const BLANK = {
  name: "",
  url: "",
  transport: "http",
  secret: "",
  secret_header: "Authorization",
  secret_prefix: "Bearer ",
  headers: {},
  enabled: true,
};

// Settings > MCP tab (admin only). Mirrors the Servers tab: list with a status light, click a
// row to edit, [-] to delete, one form for both adding and editing.
export default function McpServers() {
  const t = useT();
  const [servers, setServers] = useState([]);
  const [editingId, setEditingId] = useState(null); // null → adding
  const [form, setForm] = useState(BLANK);
  const [headersText, setHeadersText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (refresh) => {
    try {
      setServers(await api.listMcpServers(refresh));
      setError("");
    } catch (e) {
      setError(errText(e));
    }
  }, []);

  // Loaded once, not polled: unlike the Ollama probe, a status check here opens a full MCP
  // session (initialize → tools/list). Refreshing is explicit, via the button.
  useEffect(() => {
    load(false);
  }, [load]);

  function set(patch) {
    setForm((f) => ({ ...f, ...patch }));
  }

  function resetForm() {
    setEditingId(null);
    setForm(BLANK);
    setHeadersText("");
    setError("");
  }

  function applyPreset(key) {
    const preset = PRESETS[key];
    if (!preset) return;
    setForm({ ...BLANK, ...preset, secret: "" });
    setHeadersText(JSON.stringify(preset.headers || {}, null, 2));
  }

  function startEdit(s) {
    setEditingId(s.id);
    // `secret` stays empty on purpose: the backend never returns it, and an empty field means
    // "unchanged" on save.
    setForm({
      name: s.name,
      url: s.url,
      transport: s.transport,
      secret: "",
      secret_header: s.secret_header,
      secret_prefix: s.secret_prefix,
      headers: s.headers || {},
      enabled: s.enabled,
    });
    setHeadersText(Object.keys(s.headers || {}).length ? JSON.stringify(s.headers, null, 2) : "");
    setError("");
  }

  async function handleSubmit() {
    let headers = {};
    if (headersText.trim()) {
      try {
        headers = JSON.parse(headersText);
      } catch {
        setError(t("mcp.headersInvalid"));
        return;
      }
    }
    const payload = { ...form, headers };
    // An empty secret field must not wipe the stored one when editing — omitting the key lets
    // the backend's exclude_unset keep it.
    if (editingId && !payload.secret) delete payload.secret;

    setBusy(true);
    try {
      if (editingId) await api.updateMcpServer(editingId, payload);
      else await api.addMcpServer(payload);
      resetForm();
      await load(false);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id) {
    if (editingId === id) resetForm();
    try {
      await api.deleteMcpServer(id);
      await load(false);
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <div className="h-full overflow-y-auto themed-scroll space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-neutral-500">{t("mcp.hint")}</p>
        <button
          onClick={() => load(true)}
          className="px-2 py-1 rounded-lg text-xs text-neutral-400 hover:bg-neutral-800"
        >
          {t("mcp.refresh")}
        </button>
      </div>

      <div className="space-y-2">
        {servers.map((s) => (
          <div
            key={s.id}
            onClick={() => startEdit(s)}
            title={s.error || t("mcp.editHint")}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer ${
              editingId === s.id ? "bg-neutral-700" : "bg-neutral-800/60 hover:bg-neutral-800"
            }`}
          >
            <StatusLight status={s.status} />
            <span className="flex-1 truncate">
              {s.name} — <span className="text-neutral-500">{s.url}</span>
            </span>
            <span className="text-xs text-neutral-500 shrink-0">
              {s.status === "up"
                ? t("mcp.toolCount", { n: s.tools.length })
                : s.status === "disabled"
                  ? t("mcp.disabled")
                  : t("mcp.unreachable")}
            </span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDelete(s.id);
              }}
              className="text-neutral-500 hover:text-red-400"
            >
              [-]
            </button>
          </div>
        ))}
        {servers.length === 0 && <p className="text-sm text-neutral-500">{t("mcp.empty")}</p>}
      </div>

      {/* Tools of the selected server: what was registered, and what was withheld and why. */}
      {editingId != null &&
        (() => {
          const s = servers.find((x) => x.id === editingId);
          if (!s) return null;
          return (
            <div className="rounded-lg bg-neutral-800/40 px-3 py-2 space-y-1">
              {s.tools.map((tool) => (
                <div key={tool.name} className="text-xs text-neutral-400 truncate" title={tool.description}>
                  🔧 {tool.name}
                </div>
              ))}
              {s.skipped_tools.length > 0 && (
                <div className="text-xs text-neutral-500 pt-1">
                  {t("mcp.skipped", { tools: s.skipped_tools.join(", ") })}
                </div>
              )}
              {s.error && <div className="text-xs text-red-400 break-words">{s.error}</div>}
            </div>
          );
        })()}

      <div className="space-y-2 pt-2">
        <p className="text-xs text-neutral-500">{editingId ? t("mcp.editTitle") : t("mcp.newTitle")}</p>

        {!editingId && (
          <div className="flex gap-2">
            <span className="text-xs text-neutral-500 self-center">{t("mcp.preset")}</span>
            {Object.keys(PRESETS).map((key) => (
              <button
                key={key}
                onClick={() => applyPreset(key)}
                className="px-2 py-1 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-xs"
              >
                {PRESETS[key].name}
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <select
            value={form.transport}
            onChange={(e) => set({ transport: e.target.value })}
            className="bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="http">{t("mcp.transportHttp")}</option>
            <option value="sse">{t("mcp.transportSse")}</option>
          </select>
          <input
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
            placeholder={t("mcp.namePlaceholder")}
            className="flex-1 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
          />
        </div>

        <input
          value={form.url}
          onChange={(e) => set({ url: e.target.value })}
          placeholder={t("mcp.urlPlaceholder")}
          className="w-full bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
        />

        <div className="flex gap-2">
          <input
            value={form.secret_header}
            onChange={(e) => set({ secret_header: e.target.value })}
            placeholder={t("mcp.secretHeaderPlaceholder")}
            className="w-48 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
          />
          <input
            value={form.secret_prefix}
            onChange={(e) => set({ secret_prefix: e.target.value })}
            placeholder={t("mcp.secretPrefixPlaceholder")}
            className="w-28 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
          />
          <input
            value={form.secret}
            onChange={(e) => set({ secret: e.target.value })}
            type="password"
            placeholder={editingId ? t("mcp.secretEdit") : t("mcp.secretNew")}
            className="flex-1 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
          />
        </div>

        <textarea
          value={headersText}
          onChange={(e) => setHeadersText(e.target.value)}
          placeholder={t("mcp.headersPlaceholder")}
          rows={3}
          className="w-full bg-neutral-800 rounded-lg px-3 py-1.5 text-sm font-mono"
        />

        <label className="flex items-center gap-2 text-sm text-neutral-300">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set({ enabled: e.target.checked })}
          />
          {t("mcp.enabled")}
        </label>

        {error && <p className="text-sm text-red-400 break-words">{error}</p>}

        <div className="flex gap-2 mt-2">
          {editingId && (
            <button
              onClick={resetForm}
              className="px-3 py-2 rounded-lg text-sm text-neutral-400 hover:bg-neutral-800"
            >
              {t("common.cancel")}
            </button>
          )}
          <button
            onClick={handleSubmit}
            disabled={busy}
            className="flex-1 px-3 py-2 rounded-lg bg-accent hover:bg-accent-hover text-sm disabled:opacity-50"
          >
            {editingId ? t("common.save") : t("mcp.addBtn")}
          </button>
        </div>
      </div>
    </div>
  );
}
