import Markdown from "../Markdown.jsx";
import { AttachmentChip, CopyButton, DeleteButton, EditButton } from "./MessageActions.jsx";
import { formatTs, tokensPerSecLabel } from "../../lib/format.js";

/** A single message bubble (edit mode excluded — that is `MessageEditor`).
 *
 * The assistant footer is only rendered when `model_used` is present: on old/partial records
 * that field can be empty, and in that case the copy/delete buttons were not shown either —
 * the behaviour is preserved.
 */
export default function MessageItem({ m, onEdit, onDelete, onImageClick }) {
  const isUser = m.role === "user";
  return (
    <div className={`group flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[70%] rounded-2xl px-4 py-2 ${
          isUser ? "bg-accent text-white" : "bg-neutral-800 text-neutral-100"
        }`}
      >
        {!isUser && m.model_used && (
          <div className="flex items-center justify-between gap-3 mb-2 pb-1.5 text-xs text-neutral-400">
            <span>{formatTs(m.timestamp)}</span>
            <span>
              {m.model_used} · {m.server_used}
            </span>
          </div>
        )}
        {isUser && <div className="mb-2 pb-1.5 text-xs text-white/70">{formatTs(m.timestamp)}</div>}

        {m.images?.length > 0 && (
          <div className="flex gap-2 flex-wrap mb-2">
            {m.images.map((src, i) => (
              <img
                key={i}
                src={src}
                alt=""
                onClick={() => onImageClick(src)}
                className="max-h-48 rounded-lg cursor-zoom-in"
              />
            ))}
          </div>
        )}
        {m.attachments?.length > 0 && (
          <div className="flex gap-2 flex-wrap mb-2">
            {m.attachments.map((a, i) => (
              <AttachmentChip key={i} name={a.name} onAccent={isUser} />
            ))}
          </div>
        )}

        {isUser ? <span className="whitespace-pre-wrap">{m.content}</span> : <Markdown content={m.content} />}

        {!isUser && m.model_used && (
          <div className="flex items-center justify-between gap-3 mt-2 py-1.5 text-xs text-neutral-400">
            <div className="flex items-center gap-2">
              <CopyButton text={m.content} />
              <DeleteButton onDelete={onDelete} />
            </div>
            <span>{tokensPerSecLabel(m)}</span>
          </div>
        )}
        {isUser && (
          <div className="flex items-center justify-between gap-3 mt-2 py-1.5 text-xs text-white/70">
            <div className="flex items-center gap-2">
              <CopyButton text={m.content} />
              <EditButton onEdit={onEdit} />
              <DeleteButton onDelete={onDelete} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
