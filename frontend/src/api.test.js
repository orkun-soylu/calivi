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
