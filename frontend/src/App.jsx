import { useEffect, useState, useCallback, useRef } from "react";
import Sidebar from "./components/Sidebar.jsx";
import ChatView from "./components/ChatView.jsx";
import SettingsModal from "./components/SettingsModal.jsx";
import AuthView from "./components/AuthView.jsx";
import { SettingsIcon } from "./components/icons.jsx";
import { api, setUnauthorizedHandler } from "./api.js";
import { useT } from "./i18n.js";

// Renders a chat as plain text: title + "User:" / "Assistant (model @ server):" blocks.
// The content stays raw markdown (copy-raw philosophy); the model attribution is valuable
// because the model can be picked per message.
function formatChatForCopy(chat) {
  const parts = [chat.title, ""];
  for (const m of chat.messages) {
    if (m.role === "user") {
      parts.push("User:", m.content, "");
    } else if (m.role === "assistant") {
      const tag = m.model_used
        ? `Assistant (${m.model_used}${m.server_used ? ` @ ${m.server_used}` : ""})`
        : "Assistant";
      parts.push(`${tag}:`, m.content, "");
    }
  }
  return parts.join("\n").trimEnd() + "\n";
}

const ACTIVE_CHAT_KEY = "calivi_active_chat_id";

export default function App() {
  const t = useT();

  // Session state: me=null + authReady=true → show AuthView.
  const [me, setMe] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [registrationEnabled, setRegistrationEnabled] = useState(true);

  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(() => {
    const n = Number(localStorage.getItem(ACTIVE_CHAT_KEY));
    return n || null; // restore the last active chat after a refresh
  });
  const [activeChat, setActiveChat] = useState(null);
  const [servers, setServers] = useState([]);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // handleMessageSent runs after the stream ends (seconds later); a ref is used instead of a
  // stale closure so it refreshes whichever chat is active at that moment (critical after a fork).
  const activeChatIdRef = useRef(null);

  const refreshChats = useCallback(async () => {
    setChats(await api.listChats());
  }, []);

  const refreshServers = useCallback(async () => {
    setServers(await api.listServers());
  }, []);

  const refreshActiveChat = useCallback(async (id) => {
    if (!id) return;
    try {
      setActiveChat(await api.getChat(id));
    } catch {
      // The saved chat was deleted / not found → fall back to the empty state.
      setActiveChatId(null);
      setActiveChat(null);
    }
  }, []);

  // Bootstrap the session: 401 hook (→ AuthView), auth config, check for an existing session.
  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null));
    (async () => {
      try {
        const cfg = await api.getAuthConfig();
        setRegistrationEnabled(cfg.registration_enabled);
      } catch {
        /* ignore */
      }
      try {
        setMe(await api.getMe());
      } catch {
        setMe(null);
      } finally {
        setAuthReady(true);
      }
    })();
  }, []);

  // Load data only once signed in (otherwise a 401 loop).
  useEffect(() => {
    if (!me) return;
    refreshChats();
    refreshServers();
    const interval = setInterval(refreshServers, 3000);
    return () => clearInterval(interval);
  }, [me, refreshChats, refreshServers]);

  useEffect(() => {
    activeChatIdRef.current = activeChatId;
    if (me) refreshActiveChat(activeChatId);
    if (activeChatId) localStorage.setItem(ACTIVE_CHAT_KEY, String(activeChatId));
    else localStorage.removeItem(ACTIVE_CHAT_KEY);
  }, [activeChatId, refreshActiveChat, me]);

  function handleAuthed(user) {
    setMe(user);
    setAuthReady(true);
  }

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      /* the cookie is dropped regardless */
    }
    setMe(null);
    setActiveChatId(null);
    setActiveChat(null);
    setChats([]);
    setServers([]);
    setSettingsOpen(false);
  }

  async function handleNewChat() {
    const chat = await api.createChat();
    await refreshChats();
    setActiveChatId(chat.id);
  }

  async function handleDeleteChat(id) {
    await api.deleteChat(id);
    if (id === activeChatId) {
      setActiveChatId(null);
      setActiveChat(null);
    }
    await refreshChats();
  }

  async function handleRenameChat(id, title) {
    await api.updateChat(id, { title });
    await refreshChats();
  }

  async function handleTogglePin(id, pinned) {
    await api.updateChat(id, { pinned });
    await refreshChats();
  }

  // Copies the whole chat (title + user/assistant blocks) to the clipboard.
  async function handleCopyChat(id) {
    const chat = await api.getChat(id); // the list carries no messages; fetch the detail
    try {
      await navigator.clipboard.writeText(formatChatForCopy(chat));
    } catch {
      /* no clipboard access — fail silently */
    }
  }

  async function handleMessageSent() {
    await refreshChats();
    await refreshActiveChat(activeChatIdRef.current);
  }

  // Fork: switch to the new chat id once it arrives in the header (the stream keeps flowing into it).
  async function handleForked(newChatId) {
    setActiveChatId(newChatId);
    await refreshChats();
  }

  async function handleAddServer(data) {
    await api.addServer(data);
    await refreshServers();
  }

  async function handleUpdateServer(id, data) {
    await api.updateServer(id, data);
    await refreshServers();
  }

  async function handleDeleteServer(id) {
    await api.deleteServer(id);
    await refreshServers();
  }

  if (!authReady) {
    return <div className="flex items-center justify-center h-screen text-neutral-500">{t("common.loading")}</div>;
  }
  if (!me) {
    return <AuthView registrationEnabled={registrationEnabled} onAuthed={handleAuthed} />;
  }

  return (
    <div className="flex">
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onSelectChat={setActiveChatId}
        onNewChat={handleNewChat}
        onDeleteChat={handleDeleteChat}
        onRenameChat={handleRenameChat}
        onTogglePin={handleTogglePin}
        onCopyChat={handleCopyChat}
        me={me}
        onLogout={handleLogout}
      />

      {activeChat ? (
        <ChatView
          chat={activeChat}
          servers={servers}
          onMessageSent={handleMessageSent}
          onForked={handleForked}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      ) : (
        <div className="flex-1 relative h-screen">
          <button
            onClick={() => setSettingsOpen(true)}
            className="absolute top-4 right-5 text-neutral-300 opacity-70 hover:opacity-100"
            title={t("common.settings")}
          >
            <SettingsIcon className="w-5 h-5" />
          </button>
          <div className="flex items-center justify-center h-full text-neutral-500">
            {t("app.empty")}
          </div>
        </div>
      )}

      {settingsOpen && (
        <SettingsModal
          servers={servers}
          me={me}
          onClose={() => setSettingsOpen(false)}
          onAdd={handleAddServer}
          onUpdate={handleUpdateServer}
          onDelete={handleDeleteServer}
          onMeUpdated={setMe}
          onAccountDeleted={handleLogout}
        />
      )}
    </div>
  );
}
