// Server + model picker (used both in the top bar and in the message editor).
// value: {serverId: number, model: string}. onChange returns the same shape. Manual selection.
export default function ServerModelPicker({ servers, value, onChange }) {
  const { serverId, model } = value;
  const selectedServer = servers.find((s) => s.id === serverId);
  const cls = "bg-neutral-800 text-sm rounded-lg px-2 py-1 border border-neutral-700";

  function handleServerChange(raw) {
    const next = Number(raw);
    const srv = servers.find((s) => s.id === next);
    const keep = srv?.models.includes(model);
    onChange({ serverId: next, model: keep ? model : srv?.models[0] || "" });
  }

  return (
    <>
      <select value={serverId ?? ""} onChange={(e) => handleServerChange(e.target.value)} className={cls}>
        {servers.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>

      {selectedServer && (
        <select
          value={model}
          onChange={(e) => onChange({ serverId, model: e.target.value })}
          className={cls}
        >
          {selectedServer.models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      )}
    </>
  );
}
