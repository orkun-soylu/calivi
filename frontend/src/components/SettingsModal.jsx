import { useState, useRef, useEffect } from "react";
import StatusLight from "./StatusLight.jsx";
import ConfigEditor from "./ConfigEditor.jsx";
import UserManagement from "./UserManagement.jsx";
import McpServers from "./McpServers.jsx";
import { api } from "../api.js";
import { useT, useLang, setLang, LANGUAGES } from "../i18n.js";
import { useTheme, setTheme } from "../theme.js";
import { useAccent, setAccent, ACCENTS } from "../accent.js";

export default function SettingsModal({ servers, me, onClose, onAdd, onUpdate, onDelete, onMeUpdated, onAccountDeleted }) {
  const t = useT();
  const lang = useLang();
  const theme = useTheme();
  const accent = useAccent();
  const isAdmin = me?.role === "admin";

  // Tabs: Servers is admin-only. Users is visible to everyone
  // (admin → full list + management, regular user → only their own row + profile editing).
  const TABS = [
    { id: "general", key: "settings.tab.general" },
    ...(isAdmin ? [{ id: "servers", key: "settings.tab.servers" }] : []),
    // MCP is admin-only for a stronger reason than Servers: adding one grants every
    // user of this instance whatever that server can do.
    ...(isAdmin ? [{ id: "mcp", key: "settings.tab.mcp" }] : []),
    { id: "prompts", key: "settings.tab.prompts" },
    { id: "tools", key: "settings.tab.tools" },
    { id: "users", key: "settings.tab.users" },
    { id: "about", key: "settings.tab.about" },
  ];

  const [tab, setTab] = useState("general");

  // Registration on/off toggle (admin, General tab).
  const [regEnabled, setRegEnabled] = useState(null);
  useEffect(() => {
    if (!isAdmin) return;
    api.getSettings().then((s) => setRegEnabled(s.registration_enabled)).catch(() => {});
  }, [isAdmin]);

  async function toggleRegistration(next) {
    setRegEnabled(next);
    try {
      const s = await api.updateSettings({ registration_enabled: next });
      setRegEnabled(s.registration_enabled);
    } catch {
      setRegEnabled(!next); // geri al
    }
  }
  const [editingId, setEditingId] = useState(null); // null → adding, id → editing
  const [type, setType] = useState("ollama");
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("11434");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  // Dragging + resizing
  const [size, setSize] = useState({ w: 816, h: 560 });
  const [pos, setPos] = useState(() => ({
    x: Math.max(20, Math.round((window.innerWidth - 816) / 2)),
    y: Math.max(20, Math.round((window.innerHeight - 560) / 2)),
  }));
  const dragRef = useRef(null);
  const resizeRef = useRef(null);

  useEffect(() => {
    function onMove(e) {
      if (dragRef.current) {
        setPos({ x: e.clientX - dragRef.current.dx, y: Math.max(0, e.clientY - dragRef.current.dy) });
      } else if (resizeRef.current) {
        const r = resizeRef.current;
        setSize({
          w: Math.max(380, r.w + (e.clientX - r.x)),
          h: Math.max(320, r.h + (e.clientY - r.y)),
        });
      }
    }
    function onUp() {
      dragRef.current = null;
      resizeRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function startDrag(e) {
    if (e.target.closest("button")) return; // don't start dragging when clicking the tab/close buttons
    dragRef.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
  }
  function startResize(e) {
    e.stopPropagation();
    resizeRef.current = { x: e.clientX, y: e.clientY, w: size.w, h: size.h };
  }

  function resetForm() {
    setEditingId(null);
    setType("ollama");
    setName("");
    setHost("");
    setPort("11434");
    setBaseUrl("");
    setApiKey("");
  }

  // Clicking a server row fills the form with that server and switches to edit mode.
  function startEdit(s) {
    setEditingId(s.id);
    setType(s.type);
    setName(s.name);
    setHost(s.host || "");
    setPort(String(s.port || 11434));
    setBaseUrl(s.base_url || "");
    setApiKey(""); // empty = the existing key is kept
  }

  function buildPayload() {
    if (type === "openai") {
      const p = { name: name.trim(), type: "openai", base_url: baseUrl.trim() };
      if (apiKey.trim()) p.api_key = apiKey.trim();
      else if (!editingId) p.api_key = null; // empty when adding → null; empty when editing → unchanged
      return p;
    }
    return { name: name.trim(), type: "ollama", host: host.trim(), port: Number(port) || 11434 };
  }

  async function handleSubmit() {
    if (!name.trim()) return;
    if (type === "ollama" && !host.trim()) return;
    if (type === "openai" && !baseUrl.trim()) return;
    const payload = buildPayload();
    if (editingId) await onUpdate(editingId, payload);
    else await onAdd(payload);
    resetForm();
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50">
      <div
        className="absolute bg-neutral-900 rounded-2xl shadow-2xl ring-1 ring-neutral-700/60 flex flex-col overflow-hidden"
        style={{ left: pos.x, top: pos.y, width: size.w, height: size.h }}
      >
        {/* Title bar = drag handle */}
        <div
          onMouseDown={startDrag}
          className="flex items-center justify-between px-5 py-3 cursor-move select-none shrink-0"
        >
          <div className="flex gap-1">
            {TABS.map((tb) => (
              <button
                key={tb.id}
                onClick={() => setTab(tb.id)}
                className={`px-3 py-1.5 rounded-lg text-sm ${
                  tab === tb.id ? "bg-neutral-800 text-neutral-100" : "text-neutral-400 hover:bg-neutral-800/60"
                }`}
              >
                {t(tb.key)}
              </button>
            ))}
          </div>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-200">
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 px-5 pb-5">
          {tab === "general" && (
            <div className="h-full overflow-y-auto themed-scroll">
              {/* Row-based settings. Future settings are added here as additional rows. */}
              <div className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm text-neutral-200">{t("settings.general.theme")}</div>
                  <div className="text-xs text-neutral-500">{t("settings.general.themeDesc")}</div>
                </div>
                <div className="flex gap-1 bg-neutral-800 rounded-lg p-1 text-sm shrink-0">
                  {["light", "dark"].map((mode) => (
                    <button
                      key={mode}
                      onClick={() => setTheme(mode)}
                      className={`px-3 py-1 rounded-md ${
                        theme === mode ? "bg-neutral-700 text-neutral-100" : "text-neutral-400 hover:text-neutral-200"
                      }`}
                    >
                      {mode === "light" ? `☀ ${t("theme.light")}` : `🌙 ${t("theme.dark")}`}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm text-neutral-200">{t("settings.general.accent")}</div>
                  <div className="text-xs text-neutral-500">{t("settings.general.accentDesc")}</div>
                </div>
                <div className="flex gap-1.5 shrink-0 justify-end">
                  {ACCENTS.map((a) => (
                    <button
                      key={a.key}
                      onClick={() => setAccent(a.key)}
                      title={t(`accent.${a.key}`)}
                      style={{ backgroundColor: a.hex }}
                      className={`w-6 h-6 rounded-full ring-2 ring-offset-2 ring-offset-neutral-900 transition ${
                        accent === a.key ? "ring-neutral-100" : "ring-transparent hover:ring-neutral-500"
                      }`}
                    />
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm text-neutral-200">{t("settings.general.language")}</div>
                  <div className="text-xs text-neutral-500">{t("settings.general.languageDesc")}</div>
                </div>
                <select
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                  className="bg-neutral-800 rounded-lg px-3 py-1.5 text-sm shrink-0"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </div>

              {isAdmin && (
                <div className="flex items-center justify-between gap-4 py-3">
                  <div className="min-w-0">
                    <div className="text-sm text-neutral-200">{t("settings.general.registration")}</div>
                    <div className="text-xs text-neutral-500">{t("settings.general.registrationDesc")}</div>
                  </div>
                  <button
                    onClick={() => toggleRegistration(!regEnabled)}
                    disabled={regEnabled === null}
                    className={`shrink-0 w-11 h-6 rounded-full transition-colors relative disabled:opacity-40 ${
                      regEnabled ? "bg-accent" : "bg-neutral-700"
                    }`}
                    title={regEnabled ? t("settings.general.registration") : t("auth.registrationClosed")}
                  >
                    <span
                      className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${
                        regEnabled ? "left-[22px]" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              )}
            </div>
          )}

          {tab === "users" && (
            <UserManagement me={me} onMeUpdated={onMeUpdated} onAccountDeleted={onAccountDeleted} />
          )}

          {tab === "prompts" && <ConfigEditor name="system_prompts" hint={t("settings.prompts.hint")} readOnly={!isAdmin} />}

          {tab === "tools" && <ConfigEditor name="tools" hint={t("settings.tools.hint")} readOnly={!isAdmin} />}

          {tab === "about" && (
            <div className="text-sm text-neutral-300 space-y-3 leading-relaxed">
              <p className="text-lg text-neutral-100">Calivi</p>
              <p>{t("about.desc")}</p>
              <p className="text-neutral-500">{t("about.footer")}</p>
            </div>
          )}

          {tab === "mcp" && isAdmin && <McpServers />}

          {tab === "servers" && (
            <div className="h-full overflow-y-auto themed-scroll space-y-4">
              <div className="space-y-2">
                {servers.map((s) => (
                  <div
                    key={s.id}
                    onClick={() => startEdit(s)}
                    title={t("servers.editHint")}
                    className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer ${
                      editingId === s.id ? "bg-neutral-700" : "bg-neutral-800/60 hover:bg-neutral-800"
                    }`}
                  >
                    <StatusLight status={s.status} />
                    <span className="flex-1 truncate">
                      {s.name} — {s.type === "openai" ? s.base_url : `${s.host}:${s.port}`}
                      <span className="text-neutral-500">
                        {s.type === "openai" ? t("servers.typeOpenai") : t("servers.typeOllama")}
                      </span>
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (editingId === s.id) resetForm();
                        onDelete(s.id);
                      }}
                      className="text-neutral-500 hover:text-red-400"
                    >
                      [-]
                    </button>
                  </div>
                ))}
              </div>

              <div className="space-y-2 pt-2">
                <p className="text-xs text-neutral-500">
                  {editingId ? t("servers.editTitle") : t("servers.newTitle")}
                </p>
                <div className="flex gap-2">
                  <select
                    value={type}
                    onChange={(e) => setType(e.target.value)}
                    className="bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                  >
                    <option value="ollama">{t("servers.optOllama")}</option>
                    <option value="openai">{t("servers.optOpenai")}</option>
                  </select>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("servers.namePlaceholder")}
                    className="flex-1 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                  />
                </div>

                {type === "openai" ? (
                  <>
                    <input
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      placeholder={t("servers.baseUrlPlaceholder")}
                      className="w-full bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                    />
                    <input
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      type="password"
                      placeholder={editingId ? t("servers.apiKeyEdit") : t("servers.apiKeyNew")}
                      className="w-full bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                    />
                  </>
                ) : (
                  <div className="flex gap-2">
                    <input
                      value={host}
                      onChange={(e) => setHost(e.target.value)}
                      placeholder={t("servers.hostPlaceholder")}
                      className="flex-1 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                    />
                    <input
                      value={port}
                      onChange={(e) => setPort(e.target.value)}
                      placeholder={t("servers.portPlaceholder")}
                      className="w-24 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                    />
                  </div>
                )}

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
                    className="flex-1 px-3 py-2 rounded-lg bg-accent hover:bg-accent-hover text-sm"
                  >
                    {editingId ? t("common.save") : t("servers.addBtn")}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Resize handle (bottom-right corner) */}
        <div
          onMouseDown={startResize}
          className="absolute bottom-0 right-0 w-5 h-5 flex items-end justify-end pr-1 pb-0.5 cursor-nwse-resize text-neutral-600 hover:text-neutral-400 text-xs leading-none select-none"
          title={t("settings.resize")}
        >
          ◢
        </div>
      </div>
    </div>
  );
}
