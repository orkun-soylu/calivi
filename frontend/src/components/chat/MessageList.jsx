import { useEffect, useRef } from "react";
import Markdown from "../Markdown.jsx";
import MessageItem from "./MessageItem.jsx";
import MessageEditor from "./MessageEditor.jsx";
import { AttachmentChip } from "./MessageActions.jsx";
import ApprovalCard from "./ApprovalCard.jsx";
import { searchLabel } from "../../lib/format.js";
import { useT } from "../../i18n.js";

/** Within this many px of the bottom the list counts as "at the bottom" and follows new output;
 *  scrolled further up, it stays where the user left it. */
export const STICK_THRESHOLD_PX = 32;

/** The message stream: persisted messages + the optimistic user bubble + live stream indicators. */
export default function MessageList({
  chat,
  edit,
  upServers,
  stream,
  pending,
  onImageClick,
  onStartEdit,
  onDeleteMessage,
  onDecide,
  onInspect,
}) {
  const t = useT();
  const scrollRef = useRef(null);
  // Follow new output only while the user is at the bottom. The list used to scroll to the end on
  // every streamed token, so scrolling up to read a long answer was undone mid-sentence.
  const stickRef = useRef(true);
  // Where the list last scrolled itself to. The browser delivers that scroll's event a frame later,
  // and content can grow in between (a code block arriving), so a plain distance-from-bottom check
  // read the list's own scroll as the user leaving. Only moving above this position is the user.
  const autoTopRef = useRef(0);
  const { streaming, thinking, sending, searchInfo, approval } = stream;

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_THRESHOLD_PX) {
      stickRef.current = true;
    } else if (el.scrollTop < autoTopRef.current - 1) {
      stickRef.current = false;
    }
  };

  // Opening a chat or sending a message means "take me to the end" again. A finishing answer
  // (pending.user back to null) does not: the user may be reading further up.
  useEffect(() => {
    stickRef.current = true;
  }, [chat?.id]);
  useEffect(() => {
    if (pending.user !== null) stickRef.current = true;
  }, [pending.user]);

  useEffect(() => {
    const el = scrollRef.current;
    // Instant, not smooth: a smooth scroll emits intermediate scroll events, which read as the user
    // leaving the bottom and would switch following off in the middle of a stream.
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight;
      autoTopRef.current = el.scrollTop; // read back: the browser clamps it to the real maximum
    }
  }, [chat?.messages, streaming, thinking, pending.user]);

  return (
    <div className="relative flex-1 min-h-0">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="themed-scroll h-full overflow-y-auto px-3 py-4 md:px-6 md:py-6 space-y-4"
      >
        {chat?.messages.map((m) =>
          m.role === "user" && edit.editingId === m.id ? (
            <MessageEditor
              key={m.id}
              content={edit.content}
              onContentChange={edit.setContent}
              target={edit.target}
              onTargetChange={edit.setTarget}
              upServers={upServers}
              onCancel={edit.cancel}
              onFork={edit.fork}
              onUpdate={edit.update}
            />
          ) : (
            <MessageItem
              key={m.id}
              m={m}
              onEdit={() => onStartEdit(m)}
              onDelete={() => onDeleteMessage(m.id)}
              onImageClick={onImageClick}
              onInspect={onInspect}
            />
          )
        )}

        {pending.user !== null && (
          <div className="flex justify-end">
            <div className="max-w-[88%] md:max-w-[70%] rounded-2xl px-4 py-2 whitespace-pre-wrap bg-accent text-white">
              {pending.images.length > 0 && (
                <div className="flex gap-2 flex-wrap mb-2">
                  {/* Same behaviour as the persisted images in MessageItem: it must stay
                      clickable while the message is in flight, otherwise the image was
                      unclickable for a few seconds and then abruptly became clickable
                      once the message was saved. */}
                  {pending.images.map((src, i) => (
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
              {pending.attachments.length > 0 && (
                <div className="flex gap-2 flex-wrap mb-2">
                  {pending.attachments.map((a, i) => (
                    <AttachmentChip key={i} name={a.name} onAccent />
                  ))}
                </div>
              )}
              {pending.user}
            </div>
          </div>
        )}

        {sending && approval && <ApprovalCard approval={approval} onDecide={onDecide} />}

        {sending && searchInfo && (
          <div className="flex justify-start">
            <div className="max-w-[88%] md:max-w-[70%] rounded-xl px-3 py-1.5 bg-neutral-900 text-neutral-400 text-xs">
              {searchLabel(t, searchInfo)}
            </div>
          </div>
        )}

        {/* Fixed height: as the thinking text grows the box must not expand and jump the page. */}
        {sending && thinking && !streaming && (
          <div className="flex justify-start">
            <div className="w-[88%] md:w-[70%] h-64 overflow-hidden rounded-2xl px-4 py-2 bg-neutral-900 text-neutral-500 text-sm italic whitespace-pre-wrap flex flex-col justify-end">
              💭 {thinking.slice(-400)}
            </div>
          </div>
        )}

        {sending && (streaming || !thinking) && (
          <div className="flex justify-start">
            <div className="max-w-[88%] md:max-w-[70%] rounded-2xl px-4 py-2 bg-neutral-800 text-neutral-100">
              {streaming ? <Markdown content={streaming} /> : "…"}
            </div>
          </div>
        )}
      </div>
      {/* Top/bottom fade: a dark→transparent transition from the model-picker and composer bars
          into the message area. Inset 10px from the right so it does not cover the scrollbar. */}
      <div className="pointer-events-none absolute left-0 right-2.5 top-0 h-8 bg-gradient-to-b from-neutral-950 to-neutral-950/0" />
      <div className="pointer-events-none absolute left-0 right-2.5 bottom-0 h-8 bg-gradient-to-t from-neutral-950 to-neutral-950/0" />
    </div>
  );
}
