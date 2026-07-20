import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { useChatStream } from "./useChatStream.js";

/** A manually resolvable promise — used to hold the flow open and observe intermediate state.
 * (renderHook's `result.current` only refreshes once the act block ends; intermediate state
 * cannot be read without suspending the flow.) */
function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

/** Starts the flow and leaves it suspended; `emit` sends a piece, `finish` ends it. */
async function startStream(result, opts) {
  const d = deferred();
  let emit;
  let signal;
  let runP;
  await act(async () => {
    runP = result.current.run((ctx) => {
      emit = ctx.onPiece;
      signal = ctx.signal;
      return d.promise;
    }, opts);
  });
  return {
    emit: (piece) => act(() => emit(piece)),
    signal: () => signal,
    finish: async () => {
      await act(async () => {
        d.resolve();
        await runP;
      });
    },
  };
}

describe("onPiece — how NDJSON pieces land in state", () => {
  test("content pieces accumulate", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    await active.emit({ type: "content", text: "Hel" });
    await active.emit({ type: "content", text: "lo" });
    expect(result.current.streaming).toBe("Hello");

    await active.finish();
  });

  test("thinking and content accumulate separately", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    await active.emit({ type: "thinking", text: "pondering" });
    await active.emit({ type: "content", text: "answer" });
    expect(result.current.thinking).toBe("pondering");
    expect(result.current.streaming).toBe("answer");

    await active.finish();
  });

  test("tool_call/tool_result are turned into activity state", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    await active.emit({ type: "tool_call", name: "web_search" });
    expect(result.current.searchInfo).toEqual({ status: "tool_running", name: "web_search" });

    await active.emit({ type: "tool_result", name: "web_search", ok: true });
    expect(result.current.searchInfo).toEqual({ status: "tool_done", name: "web_search" });

    await active.emit({ type: "tool_result", name: "web_search", ok: false });
    expect(result.current.searchInfo).toEqual({ status: "tool_failed", name: "web_search" });

    await active.finish();
  });

  test("an error piece is appended as ⚠️ to the existing text", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    await active.emit({ type: "content", text: "half an answer" });
    await active.emit({ type: "error", message: "upstream 400" });
    expect(result.current.streaming).toBe("half an answer\n\n⚠️ upstream 400");

    await active.finish();
  });

  test("an error on empty text does not prepend \\n\\n", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    await active.emit({ type: "error", message: "server is down" });
    expect(result.current.streaming).toBe("⚠️ server is down");

    await active.finish();
  });
});

describe("run — cleanup and ordering", () => {
  test("sending=true throughout the flow, state is reset when it ends", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    await active.emit({ type: "content", text: "x" });
    expect(result.current.sending).toBe(true);

    await active.finish();
    expect(result.current.sending).toBe(false);
    expect(result.current.streaming).toBe("");
    expect(result.current.thinking).toBe("");
    expect(result.current.searchInfo).toBe(null);
  });

  test("beforeClear is AWAITED — the streaming bubble is not cleared until it settles", async () => {
    // In the send flow beforeClear = onMessageSent(); clearing the bubble before the new message
    // lands in the list shows an empty gap. That is exactly the behaviour this test protects.
    //
    // NOTE: the `startStream` helper is not used here — this test needs to end the stream while
    // leaving beforeClear SUSPENDED, and since the helper's finish() opens its own act, the act
    // blocks would nest (which corrupts React's internal state and breaks later tests).
    const { result } = renderHook(() => useChatStream());
    const streamP = deferred();
    const gate = deferred();
    let emit;
    let runP;

    await act(async () => {
      runP = result.current.run(
        (ctx) => {
          emit = ctx.onPiece;
          return streamP.promise;
        },
        { beforeClear: () => gate.promise }
      );
    });
    await act(() => emit({ type: "content", text: "answer" }));

    // End the stream; run is now waiting inside beforeClear.
    await act(async () => {
      streamP.resolve();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(result.current.streaming).toBe("answer"); // NOT cleared yet

    await act(async () => {
      gate.resolve();
      await runP;
    });
    expect(result.current.streaming).toBe("");
  });

  test("afterClear is NOT awaited — on edit/fork onMessageSent is fire-and-forget", async () => {
    const { result } = renderHook(() => useChatStream());
    let completed = false;
    await act(async () => {
      await result.current.run(() => Promise.resolve(), {
        afterClear: () => new Promise(() => {}), // never resolves
      });
      completed = true;
    });
    expect(completed).toBe(true);
    expect(result.current.sending).toBe(false);
  });

  // handleStreamError shows the error message and waits (2500ms for errors, 500ms for AbortError).
  // These two tests use REAL timers: fake timers deadlock with RTL's async act wrapper (act ties
  // its own waiting to the faked timer too). The cost is a few seconds; the payoff is verifying
  // the real delay behaviour.
  async function startFailingStream(result, err, windowMs) {
    let runP;
    await act(async () => {
      runP = result.current.run(() => Promise.reject(err));
      await new Promise((r) => setTimeout(r, windowMs)); // INSIDE the display window
    });
    return runP;
  }

  test("the error message is shown, then cleanup runs", async () => {
    const { result } = renderHook(() => useChatStream());
    const runP = await startFailingStream(result, new Error("connection lost"), 50);

    expect(result.current.streaming).toBe("⚠️ connection lost");

    await act(async () => {
      await runP;
    });
    expect(result.current.sending).toBe(false);
    expect(result.current.streaming).toBe("");
  }, 10000);

  test("cancellation (AbortError) shows no ⚠️", async () => {
    const { result } = renderHook(() => useChatStream());
    const abortErr = Object.assign(new Error("cancelled"), { name: "AbortError" });
    const runP = await startFailingStream(result, abortErr, 50);

    // The backend persists the partial; no error is shown to the user.
    expect(result.current.streaming).toBe("");

    await act(async () => {
      await runP;
    });
    expect(result.current.sending).toBe(false);
  }, 10000);
});

describe("stop / Esc", () => {
  test("stop aborts the active flow's signal", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    expect(active.signal().aborted).toBe(false);
    act(() => result.current.stop());
    expect(active.signal().aborted).toBe(true);

    await active.finish();
  });

  test("the Esc key aborts during the flow", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(active.signal().aborted).toBe(true);

    await active.finish();
  });

  test("the keydown listener is removed when the flow ends (no accumulation)", async () => {
    // CAREFUL: testing this as "Esc does not abort after the flow ends" is NOT enough — once the
    // flow ends abortRef is already null, so Esc does nothing even if the listener leaks (caught
    // in a mutation test: that assertion still passed with the cleanup deleted). So the add/remove
    // balance is measured directly.
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    const { result } = renderHook(() => useChatStream());

    const active = await startStream(result);
    const added = add.mock.calls.filter(([ev]) => ev === "keydown").length;
    await active.finish();
    const removed = remove.mock.calls.filter(([ev]) => ev === "keydown").length;

    expect(added).toBe(1);
    expect(removed).toBe(1);

    add.mockRestore();
    remove.mockRestore();
  });

  test("after the flow ends Esc aborts nothing", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);
    const signal = active.signal();
    await active.finish();

    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(signal.aborted).toBe(false);
  });

  test("keys other than Esc do not interrupt the flow", async () => {
    const { result } = renderHook(() => useChatStream());
    const active = await startStream(result);

    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" })));
    expect(active.signal().aborted).toBe(false);

    await active.finish();
  });
});

describe("flashError", () => {
  test("shows the message, then clears it on its own", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useChatStream());

    act(() => result.current.flashError("report.pdf: could not be read"));
    expect(result.current.streaming).toBe("⚠️ report.pdf: could not be read");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600);
    });
    expect(result.current.streaming).toBe("");
    vi.useRealTimers();
  });
});
