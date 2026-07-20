import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useT } from "../i18n.js";

// Raw YAML config editor (routing / system_prompts). The server validates the YAML on save.
// readOnly: a non-admin user can see the content but cannot save it (PUT is admin-only anyway).
export default function ConfigEditor({ name, hint, readOnly = false }) {
  const t = useT();
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.getConfig(name).then((d) => {
      setContent(d.content);
      setLoading(false);
    });
  }, [name]);

  // Loads the factory default into the editor (does not save — applied when the user hits Save).
  async function loadDefault() {
    try {
      const d = await api.getConfigDefault(name);
      setContent(d.content);
      setStatus(t("config.defaultLoaded"));
      setTimeout(() => setStatus(""), 4000);
    } catch (e) {
      setStatus("⚠️ " + e.message);
    }
  }

  async function save() {
    setSaving(true);
    setStatus("");
    try {
      await api.saveConfig(name, content);
      setStatus(t("config.saved"));
      setTimeout(() => setStatus(""), 2500);
    } catch (e) {
      let msg = e.message;
      const m = msg.match(/\{[\s\S]*\}/);
      if (m) {
        try {
          msg = JSON.parse(m[0]).detail || msg;
        } catch {
          /* ignore */
        }
      }
      setStatus("⚠️ " + msg);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="text-neutral-500 text-sm">{t("common.loading")}</div>;

  return (
    <div className="flex flex-col gap-2 h-full">
      {hint && <p className="text-xs text-neutral-500">{hint}</p>}
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        readOnly={readOnly}
        spellCheck={false}
        className="themed-scroll w-full flex-1 min-h-0 bg-neutral-950 rounded-lg p-3 font-mono text-xs leading-relaxed outline-none"
      />
      {readOnly ? (
        <p className="text-xs text-neutral-500">{t("config.readOnly")}</p>
      ) : (
        <div className="flex items-center gap-3">
          <button
            onClick={save}
            disabled={saving}
            className="px-3 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-sm disabled:opacity-40"
          >
            {t("common.save")}
          </button>
          <button
            onClick={loadDefault}
            disabled={saving}
            title={t("config.defaultTitle")}
            className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-sm text-neutral-300 disabled:opacity-40"
          >
            {t("config.default")}
          </button>
          <span className={`text-sm ${status.startsWith("⚠️") ? "text-red-400" : "text-neutral-400"}`}>{status}</span>
        </div>
      )}
    </div>
  );
}
