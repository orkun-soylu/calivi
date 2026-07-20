import { useState, useEffect, useCallback } from "react";
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

// Settings > Users tab.
// - admin: the full user list + management (role/block/delete, id1 = super admin, locked).
// - regular user: only their own row; click the row → edit email/username (self-service).
// On their own row everyone can only change email/username (no role/block/delete).
export default function UserManagement({ me, onMeUpdated, onAccountDeleted }) {
  const t = useT();
  const isAdmin = me?.role === "admin";
  const [users, setUsers] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!isAdmin) {
      setUsers([me]); // a regular user only sees themselves
      return;
    }
    try {
      setUsers(await api.listUsers());
    } catch (e) {
      setError(errText(e));
    }
  }, [isAdmin, me]);

  useEffect(() => {
    load();
  }, [load]);

  function openRow(u) {
    if (openId === u.id) {
      setOpenId(null);
      return;
    }
    setOpenId(u.id);
    setEmail(u.email);
    setUsername(u.username);
    setError("");
  }

  async function act(fn) {
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(errText(e));
    }
  }

  // Kendi profilini kaydet (email/username) — self endpoint; App'teki me'yi de günceller.
  async function saveSelf() {
    setError("");
    try {
      const updated = await api.updateMe({ email, username });
      onMeUpdated?.(updated);
      if (isAdmin) await load();
      else setUsers([updated]);
    } catch (e) {
      setError(errText(e));
    }
  }

  // Kendi hesabını sil (onaylı) → başarıda oturum düşer, App login ekranına atar.
  async function deleteSelf() {
    if (!window.confirm(t("users.deleteSelfConfirm"))) return;
    setError("");
    try {
      await api.deleteMe();
      onAccountDeleted?.();
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <div className="h-full overflow-y-auto themed-scroll space-y-2">
      {error && <div className="text-xs text-red-500 dark:text-red-400">{error}</div>}

      {users.filter(Boolean).map((u) => {
        const isSelf = u.id === me.id;
        const isSuper = u.id === 1;
        const open = openId === u.id;
        return (
          <div key={u.id} className="rounded-lg bg-neutral-800/60">
            <div
              onClick={() => openRow(u)}
              className="flex items-center gap-2 px-3 py-2 text-sm cursor-pointer hover:bg-neutral-800 rounded-lg"
            >
              <span className="text-neutral-500 tabular-nums">#{String(u.id).padStart(4, "0")}</span>
              <span className="flex-1 truncate text-neutral-200">
                {u.username}
                {isSelf && <span className="ml-2 text-xs text-neutral-500">({t("users.you")})</span>}
                {u.blocked && <span className="ml-2 text-xs text-red-400">● {t("users.blocked")}</span>}
              </span>
              <span
                className={`text-xs px-2 py-0.5 rounded ${
                  u.role === "admin" ? "bg-accent/25 text-accent-text" : "bg-neutral-700 text-neutral-400"
                }`}
              >
                {isSuper ? t("users.superAdmin") : u.role === "admin" ? t("users.roleAdmin") : t("users.roleUser")}
              </span>
            </div>

            {open && (
              <div className="px-3 pb-3 pt-1 space-y-2">
                {/* email/username düzenleme: kendi satırın → self endpoint; admin başkası → admin endpoint */}
                <div className="flex gap-2">
                  <input
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={t("auth.email")}
                    className="flex-1 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                  />
                  <input
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder={t("auth.username")}
                    className="flex-1 bg-neutral-800 rounded-lg px-3 py-1.5 text-sm"
                  />
                  <button
                    onClick={() =>
                      isSelf ? saveSelf() : act(() => api.updateUser(u.id, { email, username }))
                    }
                    className="px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-sm shrink-0"
                  >
                    {t("common.save")}
                  </button>
                </div>

                {/* Kendi hesabını sil (süper admin hariç). */}
                {isSelf && !isSuper && (
                  <div className="flex">
                    <button
                      onClick={deleteSelf}
                      className="px-3 py-1.5 rounded-lg text-sm text-red-400 hover:bg-neutral-700 ml-auto"
                    >
                      {t("users.deleteSelf")}
                    </button>
                  </div>
                )}

                {/* Admin management buttons: only on OTHER users (no role/block/delete on yourself). */}
                {isAdmin && !isSelf && (
                  isSuper ? (
                    <div className="text-xs text-neutral-500">{t("users.locked")}</div>
                  ) : (
                    <div className="flex gap-2 flex-wrap">
                      <button
                        onClick={() => act(() => api.updateUser(u.id, { role: u.role === "admin" ? "user" : "admin" }))}
                        className="px-3 py-1.5 rounded-lg bg-neutral-700 hover:bg-neutral-600 text-sm"
                      >
                        {u.role === "admin" ? t("users.removeAdmin") : t("users.makeAdmin")}
                      </button>
                      <button
                        onClick={() => act(() => api.updateUser(u.id, { blocked: !u.blocked }))}
                        className="px-3 py-1.5 rounded-lg bg-neutral-700 hover:bg-neutral-600 text-sm"
                      >
                        {u.blocked ? t("users.unblock") : t("users.block")}
                      </button>
                      <button
                        onClick={() => {
                          if (window.confirm(t("users.deleteConfirm"))) {
                            act(() => api.deleteUser(u.id));
                            setOpenId(null);
                          }
                        }}
                        className="px-3 py-1.5 rounded-lg text-sm text-red-400 hover:bg-neutral-700 ml-auto"
                      >
                        {t("common.delete")}
                      </button>
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
