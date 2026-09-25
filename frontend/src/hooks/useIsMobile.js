import { useSyncExternalStore } from "react";

/** Below Tailwind's `md` breakpoint the app switches to the phone layout (#61): the chat list and
 *  the open chat become separate full-screen views instead of sitting side by side. */
export const MOBILE_QUERY = "(max-width: 767px)";

function query() {
  // jsdom (tests) and very old browsers have no matchMedia → desktop layout.
  return typeof window !== "undefined" && window.matchMedia ? window.matchMedia(MOBILE_QUERY) : null;
}

function subscribe(cb) {
  const mq = query();
  if (!mq) return () => {};
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

export function useIsMobile() {
  return useSyncExternalStore(subscribe, () => !!query()?.matches);
}
