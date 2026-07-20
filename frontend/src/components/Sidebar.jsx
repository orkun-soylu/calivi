import { useState, useRef, useEffect } from "react";
import { MenuIcon } from "./icons.jsx";
import { useT } from "../i18n.js";

const WIDTH_KEY = "calivi_sidebar_width";

export default function Sidebar({
  chats,
  activeChatId,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
  onTogglePin,
  onCopyChat,
  me,
  onLogout,
}) {
  const t = useT();
  const [width, setWidth] = useState(() => Number(localStorage.getItem(WIDTH_KEY)) || 256);
  const [menu, setMenu] = useState(null); // { id, x, y }
  const [copied, setCopied] = useState(false);
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState("");
  const draggingRef = useRef(false);

  // Sürükleyerek genişlik ayarı
  useEffect(() => {
    function onMove(e) {
      if (!draggingRef.current) return;
      setWidth(Math.min(480, Math.max(200, e.clientX)));
    }
    function onUp() {
      draggingRef.current = false;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  useEffect(() => {
    localStorage.setItem(WIDTH_KEY, String(width));
  }, [width]);

  const menuChat = menu ? chats.find((c) => c.id === menu.id) : null;

  function openMenu(e, id) {
    e.stopPropagation();
    const r = e.currentTarget.getBoundingClientRect();
    setCopied(false);
    setMenu({ id, x: r.right, y: r.bottom + 4 });
  }

  function startRename(id) {
    const c = chats.find((x) => x.id === id);
    setRenamingId(id);
    setRenameValue(c?.title || "");
    setMenu(null);
  }

  function commitRename() {
    if (renamingId != null) {
      const v = renameValue.trim();
      const c = chats.find((x) => x.id === renamingId);
      if (v && c && v !== c.title) onRenameChat(renamingId, v);
    }
    setRenamingId(null);
  }

  return (
    <div className="relative shrink-0 bg-neutral-900 flex flex-col h-screen" style={{ width }}>
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full px-3 py-2 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm text-left transition-colors"
        >
          {t("sidebar.newChat")}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto themed-scroll px-3 space-y-1">
        {chats.map((chat) => (
          <div
            key={chat.id}
            onClick={() => renamingId !== chat.id && onSelectChat(chat.id)}
            className={`group flex items-center gap-1.5 px-3 py-2 rounded-lg cursor-pointer text-sm ${
              chat.id === activeChatId ? "bg-neutral-800" : "hover:bg-neutral-800/60"
            }`}
          >
            {chat.pinned && (
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="shrink-0"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            )}
            {renamingId === chat.id ? (
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename();
                  else if (e.key === "Escape") setRenamingId(null);
                }}
                onBlur={commitRename}
                className="flex-1 min-w-0 bg-neutral-950 rounded px-1.5 py-0.5 outline-none"
              />
            ) : (
              <span className="flex-1 truncate">{chat.title}</span>
            )}
            <button
              onClick={(e) => openMenu(e, chat.id)}
              className="opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 shrink-0 hover:bg-neutral-700 rounded p-0.5 text-neutral-300"
              title={t("sidebar.menu")}
            >
              <MenuIcon className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      {/* User + sign out (bottom) */}
      {me && (
        <div className="shrink-0 flex items-center gap-2 px-3 py-2.5 text-sm border-t border-white/5">
          <div className="min-w-0 flex-1">
            <div className="truncate text-neutral-200">{me.username}</div>
            <div className="text-xs text-neutral-500">
              #{String(me.id).padStart(4, "0")}
              {me.role === "admin" && ` · ${me.id === 1 ? t("users.superAdmin") : t("users.roleAdmin")}`}
            </div>
          </div>
          <button
            onClick={onLogout}
            title={t("auth.logout")}
            className="shrink-0 text-neutral-500 hover:text-red-400 px-2 py-1 rounded text-xl leading-none"
          >
            ⎋
          </button>
        </div>
      )}

      {/* Genişlik ayar tutamağı (sağ kenar) */}
      <div
        onMouseDown={() => (draggingRef.current = true)}
        className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-neutral-700/70"
      />

      {menu && menuChat && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
          <div
            className="fixed z-50 -translate-x-full bg-neutral-800 rounded-lg py-1 text-sm shadow-xl min-w-[180px]"
            style={{ top: menu.y, left: menu.x }}
          >
            <button
              className="block w-full text-left px-3 py-1.5 hover:bg-neutral-700"
              onClick={() => startRename(menu.id)}
            >
              {t("sidebar.rename")}
            </button>
            <button
              className="block w-full text-left px-3 py-1.5 hover:bg-neutral-700"
              onClick={() => {
                onTogglePin(menu.id, !menuChat.pinned);
                setMenu(null);
              }}
            >
              {menuChat.pinned ? t("sidebar.unpin") : t("sidebar.pin")}
            </button>
            <button
              className="block w-full text-left px-3 py-1.5 hover:bg-neutral-700"
              onClick={async () => {
                await onCopyChat(menu.id);
                setCopied(true);
                setTimeout(() => {
                  setCopied(false);
                  setMenu(null);
                }, 900);
              }}
            >
              {copied ? <span className="text-green-400">{t("common.copied")}</span> : t("common.copy")}
            </button>
            <button
              className="block w-full text-left px-3 py-1.5 hover:bg-neutral-700 text-red-400"
              onClick={() => {
                onDeleteChat(menu.id);
                setMenu(null);
              }}
            >
              {t("common.delete")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
