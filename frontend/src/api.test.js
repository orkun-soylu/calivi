import { afterEach, describe, expect, test, vi } from "vitest";
import { api } from "./api.js";

afterEach(() => vi.unstubAllGlobals());

describe("followTurn (#85)", () => {
  test("a reply that already finished (404) is not an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("gone", { status: 404 })));
    const onPiece = vi.fn();
    await expect(api.followTurn(3, {}, onPiece)).resolves.toBeUndefined();
    expect(onPiece).not.toHaveBeenCalled();
  });

  test("replays the running reply's events", async () => {
    const body = '{"type":"content","text":"a"}\n{"type":"content","text":"b"}\n';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    const onPiece = vi.fn();
    await api.followTurn(3, {}, onPiece);
    expect(onPiece.mock.calls.map((c) => c[0].text)).toEqual(["a", "b"]);
  });

  test("cancelTurn treats an already-finished reply (404) as done", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(api.cancelTurn(3)).resolves.toBeUndefined();
  });
});

describe("image_options (🎨 picker)", () => {
  const body = (fetchMock) => JSON.parse(fetchMock.mock.calls[0][1].body);

  test("goes out when something is set", async () => {
    const f = vi.fn(async () => new Response("", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await api.sendMessage(1, { content: "fox", serverId: 2, model: "m", imageOptions: { size: "1024x1536", seed: 7 } }, () => {});
    expect(body(f).image_options).toEqual({ size: "1024x1536", seed: 7 });
  });

  test("is left out when nothing is set, on send, edit and fork", async () => {
    const f = vi.fn(async () => new Response("", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await api.sendMessage(1, { content: "x", serverId: 2, model: "m", imageOptions: {} }, () => {});
    await api.editMessage(1, 5, { content: "x", serverId: 2, model: "m" }, () => {});
    await api.forkChat(1, { messageId: 5, content: "x", serverId: 2, model: "m", imageOptions: {} }, () => {}, () => {});
    for (const call of f.mock.calls) expect(JSON.parse(call[1].body)).not.toHaveProperty("image_options");
  });

  test("edit and fork carry it too", async () => {
    const f = vi.fn(async () => new Response("", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await api.editMessage(1, 5, { content: "x", serverId: 2, model: "m", imageOptions: { steps: 20 } }, () => {});
    await api.forkChat(1, { messageId: 5, content: "x", serverId: 2, model: "m", imageOptions: { steps: 20 } }, () => {}, () => {});
    expect(f.mock.calls.map((c) => JSON.parse(c[1].body).image_options)).toEqual([{ steps: 20 }, { steps: 20 }]);
  });
});
