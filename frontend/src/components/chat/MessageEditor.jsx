import ServerModelPicker from "../ServerModelPicker.jsx";
import { useT } from "../../i18n.js";

/** Edit bubble for a user message: Update (truncate+regen) or New chat (fork).
 * The target server/model can be picked separately here → reroute to a different model. */
export default function MessageEditor({
  content,
  onContentChange,
  target,
  onTargetChange,
  upServers,
  onCancel,
  onFork,
  onUpdate,
}) {
  const t = useT();
  return (
    <div className="flex justify-end">
      <div className="w-full max-w-[70%] rounded-2xl border border-accent/50 bg-neutral-900 p-3 space-y-2">
        <textarea
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          rows={Math.min(8, content.split("\n").length + 1)}
          className="w-full bg-neutral-800 rounded-lg px-3 py-2 text-sm outline-none border border-neutral-700 focus:border-neutral-500 resize-y"
        />
        <div className="flex items-center gap-2 flex-wrap">
          <ServerModelPicker servers={upServers} value={target} onChange={onTargetChange} />
          <div className="flex-1" />
          <button onClick={onCancel} className="px-3 py-1 rounded-lg text-sm text-neutral-400 hover:bg-neutral-800">
            {t("common.cancel")}
          </button>
          <button
            onClick={onFork}
            className="px-3 py-1 rounded-lg text-sm bg-neutral-700 hover:bg-neutral-600"
            title={t("chat.forkNewTitle")}
          >
            {t("chat.forkNew")}
          </button>
          <button onClick={onUpdate} className="px-3 py-1 rounded-lg text-sm bg-accent hover:bg-accent-hover">
            {t("chat.update")}
          </button>
        </div>
      </div>
    </div>
  );
}
