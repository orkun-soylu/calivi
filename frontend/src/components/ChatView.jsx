import { useEffect, useState } from "react";
import ServerModelPicker from "./ServerModelPicker.jsx";
import MessageList from "./chat/MessageList.jsx";
import Composer from "./chat/Composer.jsx";
import { SettingsIcon } from "./icons.jsx";
import { useChatStream } from "../hooks/useChatStream.js";
import { useServerModel } from "../hooks/useServerModel.js";
import { fileToScaledDataUrl } from "../lib/images.js";
import { USE_TOOLS_KEY, loadUseTools } from "../lib/modelPrefs.js";
import { api } from "../api.js";
import { useT } from "../i18n.js";

/** Orchestrates the chat screen: combines the selected target (useServerModel), stream state
 * (useChatStream) and attachment/edit state; the rendering is done by child components. */
export default function ChatView({ chat, servers, onMessageSent, onForked, onOpenSettings }) {
  const t = useT();
  const { serverId, model, setTarget, upServers, selectedServer } = useServerModel(servers);
  const stream = useChatStream();

  const [input, setInput] = useState("");
  const [images, setImages] = useState([]); // attached images (data-URI), until sent
  const [attachments, setAttachments] = useState([]); // attached documents {name, text}
  const [pending, setPending] = useState({ user: null, images: [], attachments: [] });
  const [lightbox, setLightbox] = useState(null); // image to display full size (data-URI)
  const [useTools, setUseTools] = useState(loadUseTools);

  const [editingId, setEditingId] = useState(null);
  const [editContent, setEditContent] = useState("");
  const [editTarget, setEditTarget] = useState({ serverId: null, model: "" });

  const supportsVision = !!selectedServer?.vision_models?.includes(model);
  const canSend = (!!input.trim() || !!images.length || !!attachments.length) && !!serverId && !!model;

  useEffect(() => {
    localStorage.setItem(USE_TOOLS_KEY, useTools ? "1" : "0");
  }, [useTools]);

  // Clear attached images if the model does not support vision (they cannot be sent).
  useEffect(() => {
    if (!supportsVision) setImages([]);
  }, [supportsVision]);

  // While the lightbox is open Esc closes it — and does NOT stop the stream.
  // useChatStream also binds Escape on window (to cancel the stream). Pressing Esc with the
  // lightbox open used to cancel the in-flight answer; the user lost the generation while
  // only meaning to close the overlay. capture:true runs this listener BEFORE the other one
  // (deterministic, independent of registration order), and stopPropagation keeps it from firing.
  useEffect(() => {
    if (!lightbox) return;
    function onKey(e) {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setLightbox(null);
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [lightbox]);

  async function addFiles(files) {
    // Images → vision (only on models that support it); everything else → document text extraction (all models).
    // On a non-vision model an image is not dropped SILENTLY: the user must see why it was not attached.
    if (!supportsVision && files.some((f) => f.type.startsWith("image/"))) {
      stream.flashError(t("chat.visionUnsupported"));
    }
    const imgs = supportsVision ? files.filter((f) => f.type.startsWith("image/")) : [];
    const docs = files.filter((f) => !f.type.startsWith("image/"));
    if (imgs.length) {
      const urls = await Promise.all(imgs.map((f) => fileToScaledDataUrl(f)));
      setImages((prev) => [...prev, ...urls]);
    }
    for (const f of docs) {
      try {
        const { name, text } = await api.extractFile(f);
        setAttachments((prev) => [...prev, { name, text }]);
      } catch (e) {
        stream.flashError(`${f.name}: ${e.message}`);
      }
    }
  }

  function handlePaste(e) {
    const files = Array.from(e.clipboardData?.items || [])
      .filter((it) => it.type.startsWith("image/"))
      .map((it) => it.getAsFile())
      .filter(Boolean);
    if (!files.length) return; // plain-text paste — leave the default behaviour alone
    e.preventDefault();
    // The vision check lives HERE, not in an early return: pasting on a non-vision model used
    // to die without a trace ("images don't paste from the clipboard" report). addFiles warns.
    addFiles(files);
  }

  async function handleSend() {
    if (!canSend || stream.sending) return;
    const content = input.trim();
    const imgs = images;
    const atts = attachments;
    setInput("");
    setImages([]);
    setAttachments([]);
    setPending({ user: content, images: imgs, attachments: atts });

    await stream.run(
      ({ signal, onPiece }) =>
        api.sendMessage(
          chat.id,
          { content, images: imgs, attachments: atts, serverId, model, useTools, signal },
          onPiece
        ),
      {
        // Clear the streaming bubble only AFTER the new message lands in the list (no empty gap).
        beforeClear: async () => {
          await onMessageSent();
          setPending({ user: null, images: [], attachments: [] });
        },
      }
    );
  }

  function startEdit(m) {
    setEditingId(m.id);
    setEditContent(m.content);
    setEditTarget({ serverId, model });
  }

  function cancelEdit() {
    setEditingId(null);
    setEditContent("");
  }

  // Answers a pending tool approval. The stream is still open and resumes on its own once the
  // backend records the decision, so there is nothing to do with the response here.
  async function handleApprovalDecision(approvalId, approved) {
    if (!chat) return;
    await api.respondToApproval(chat.id, approvalId, approved);
  }

  async function handleDeleteMessage(id) {
    if (stream.sending) return;
    if (editingId === id) cancelEdit();
    await api.deleteMessage(chat.id, id);
    await onMessageSent();
  }

  async function handleUpdate() {
    if (!editContent.trim() || stream.sending) return;
    const mid = editingId;
    const content = editContent.trim();
    cancelEdit();
    await stream.run(
      ({ signal, onPiece }) =>
        api.editMessage(chat.id, mid, { content, ...editTarget, useTools, signal }, onPiece),
      { afterClear: () => onMessageSent() }
    );
  }

  async function handleFork() {
    if (!editContent.trim() || stream.sending) return;
    const mid = editingId;
    const content = editContent.trim();
    cancelEdit();
    await stream.run(
      ({ signal, onPiece }) =>
        api.forkChat(
          chat.id,
          { messageId: mid, content, ...editTarget, useTools, signal },
          (newId) => onForked(newId),
          onPiece
        ),
      { afterClear: () => onMessageSent() }
    );
  }

  const edit = {
    editingId,
    content: editContent,
    setContent: setEditContent,
    target: editTarget,
    setTarget: setEditTarget,
    cancel: cancelEdit,
    fork: handleFork,
    update: handleUpdate,
  };

  return (
    <div className="flex-1 flex flex-col h-screen">
      <div className="flex items-center gap-3 px-5 py-4">
        <ServerModelPicker servers={upServers} value={{ serverId, model }} onChange={setTarget} />
        <button
          onClick={onOpenSettings}
          className="ml-auto text-neutral-300 opacity-70 hover:opacity-100"
          title={t("common.settings")}
        >
          <SettingsIcon className="w-5 h-5" />
        </button>
      </div>

      <MessageList
        chat={chat}
        edit={edit}
        upServers={upServers}
        stream={stream}
        pending={pending}
        onImageClick={setLightbox}
        onStartEdit={startEdit}
        onDeleteMessage={handleDeleteMessage}
        onDecide={handleApprovalDecision}
      />

      <Composer
        input={input}
        onInputChange={setInput}
        onSend={handleSend}
        onStop={stream.stop}
        sending={stream.sending}
        canSend={canSend}
        images={images}
        onRemoveImage={(i) => setImages(images.filter((_, j) => j !== i))}
        attachments={attachments}
        onRemoveAttachment={(i) => setAttachments(attachments.filter((_, j) => j !== i))}
        onFiles={addFiles}
        onPaste={handlePaste}
        useTools={useTools}
        onToggleUseTools={() => setUseTools((v) => !v)}
      />

      {lightbox && (
        <div
          onClick={() => setLightbox(null)}
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6 cursor-zoom-out"
        >
          <img src={lightbox} alt="" className="max-h-full max-w-full rounded-lg" />
        </div>
      )}
    </div>
  );
}
