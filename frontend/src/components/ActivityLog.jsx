import { useState, useEffect, useCallback, useMemo } from "react";
import { api } from "../api.js";
import { useT } from "../i18n.js";

// Settings → Activity (calivi-vm, the owner only): the owner's "always allow" rules (#113), which
// can be deleted here, and the audit log of host-tool calls (#115), read-only. It outlives the chats, so a row can point at a chat that no longer exists.
// The arguments are model-written and untrusted, so they are shown as raw JSON text in a <pre>
// — never markdown, never a summary — for the same reason as on the approval card.
export default function ActivityLog() {
  const t = useT();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tool, setTool] = useState("");
  const [chat, setChat] = useState("");
  const [rules, setRules] = useState([]);

  const load = useCallback(async () => {
    try {
      const [activity, ruleList] = await Promise.all([api.getActivity(), api.listApprovalRules()]);
      setData(activity);
      setRules(ruleList);
      setError("");
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const entries = useMemo(() => data?.entries || [], [data]);
  const tools = useMemo(() => [...new Set(entries.map((e) => e.tool))].sort(), [entries]);
  const chats = useMemo(() => {
    const seen = new Map();
    for (const e of entries) if (!seen.has(e.chat)) seen.set(e.chat, e.chat_title);
    return [...seen];
  }, [entries]);
  const shown = entries.filter((e) => (!tool || e.tool === tool) && (!chat || String(e.chat) === chat));

  const chatLabel = (id, title) => title || t("activity.deletedChat", { id });

  async function deleteRule(id) {
    try {
      await api.deleteApprovalRule(id);
      setRules((list) => list.filter((r) => r.id !== id));
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  return (
    <div className="h-full flex flex-col gap-3 text-sm">
      <section className="space-y-1.5">
        <h3 className="text-neutral-200">{t("rules.title")}</h3>
        {rules.length === 0 ? (
          <p className="text-neutral-500">{t("rules.empty")}</p>
        ) : (
          rules.map((r) => (
            <div key={r.id} className="flex items-center gap-2 rounded-lg bg-neutral-800/60 px-3 py-1.5">
              <span className="shrink-0 text-neutral-400">{r.tool}</span>
              <span className="shrink-0 text-neutral-500">{t(`rules.kind.${r.kind}`)}</span>
              <code className="flex-1 min-w-0 truncate font-mono text-neutral-200" title={r.pattern}>
                {r.pattern}
              </code>
              <span className="shrink-0 text-neutral-500">{t("rules.uses", { n: r.uses })}</span>
              <button
                onClick={() => deleteRule(r.id)}
                title={t("rules.delete")}
                aria-label={t("rules.delete")}
                className="shrink-0 px-1.5 text-neutral-500 hover:text-red-400"
              >
                ✕
              </button>
            </div>
          ))
        )}
      </section>
      <p className="text-neutral-500 leading-relaxed">{t("activity.hint")}</p>
      <div className="flex flex-wrap gap-2">
        <select
          value={tool}
          onChange={(e) => setTool(e.target.value)}
          className="bg-neutral-800 rounded-lg px-2 py-1.5"
          aria-label={t("activity.allTools")}
        >
          <option value="">{t("activity.allTools")}</option>
          {tools.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <select
          value={chat}
          onChange={(e) => setChat(e.target.value)}
          className="bg-neutral-800 rounded-lg px-2 py-1.5 min-w-0 max-w-full"
          aria-label={t("activity.allChats")}
        >
          <option value="">{t("activity.allChats")}</option>
          {chats.map(([id, title]) => (
            <option key={id} value={String(id)}>
              {chatLabel(id, title)}
            </option>
          ))}
        </select>
        <button onClick={load} className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700">
          {t("activity.refresh")}
        </button>
      </div>
      {error && <p className="text-red-400">{error}</p>}
      {data && !data.enabled && <p className="text-amber-400">{t("activity.off")}</p>}
      {data && data.enabled && shown.length === 0 && <p className="text-neutral-500">{t("activity.empty")}</p>}
      <div className="flex-1 min-h-0 overflow-y-auto themed-scroll space-y-2">
        {shown.map((e) => (
          <ActivityRow key={e.id} e={e} chatLabel={chatLabel(e.chat, e.chat_title)} />
        ))}
      </div>
    </div>
  );
}

function ActivityRow({ e, chatLabel }) {
  const t = useT();
  const r = e.result;
  let status;
  let tone;
  if (e.approval === "denied") {
    [status, tone] = [t("timeline.denied"), "text-red-400"];
  } else if (!r) {
    [status, tone] = [t("activity.noResult"), "text-amber-400"];
  } else if (r.cancelled) {
    [status, tone] = [t("timeline.interrupted"), "text-amber-400"];
  } else {
    [status, tone] = [r.ok ? t("timeline.ok") : t("timeline.failed"), r.ok ? "text-emerald-400" : "text-red-400"];
  }
  const approval =
    e.approval === "owner"
      ? t("activity.approved")
      : e.approval === "auto"
        ? t("activity.auto")
        : e.approval === "rule" && e.rule
          ? t("rules.approvedBy", { rule: `${t(`rules.kind.${e.rule.kind}`)} ${e.rule.pattern}` })
          : e.approval === "plan"
            ? t("plan.approvedByPlan")
            : null;
  const when = e.ts ? new Date(e.ts).toLocaleString() : "";

  return (
    <div className="rounded-lg bg-neutral-800/60 px-3 py-2 space-y-1">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="font-mono text-neutral-100">{e.tool}</span>
        <span className={tone}>{status}</span>
        {r && r.exit !== null && r.exit !== undefined && (
          <span className="text-neutral-400">{t("activity.exit", { code: r.exit })}</span>
        )}
        {approval && <span className="text-neutral-500 min-w-0 truncate">{approval}</span>}
        {e.off_plan && <span className="text-amber-300">{t("plan.offPlan")}</span>}
        <span className="text-neutral-500 ml-auto">{when}</span>
      </div>
      <div className="text-neutral-500 truncate">
        {chatLabel} · {e.model}
        {r && typeof r.ms === "number" ? ` · ${(r.ms / 1000).toFixed(1)}s` : ""}
        {r?.output ? ` · ${r.output.size} B · ` : ""}
        {r?.output && (
          <span className="font-mono" title={r.output.sha256}>
            {r.output.sha256.slice(0, 12)}
          </span>
        )}
      </div>
      <pre className="font-mono text-xs text-neutral-300 whitespace-pre-wrap break-all">
        {JSON.stringify(e.args, null, 2)}
      </pre>
    </div>
  );
}
