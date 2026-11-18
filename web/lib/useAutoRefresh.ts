"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useSession } from "./auth";

const POLL_MS = 12_000; // check for changes every 12 s
const FULL_MS = 300_000; // and reload anyway every 5 min (covers a restart or a second instance)

/** Auto-refresh: polls GET /api/changes (no database read on the server) while the tab is visible and calls
 * reload() when anything changed, so an action in one tab shows in another. Paused while the tab is hidden. */
export function useAutoRefresh(reload: () => unknown, enabled = true) {
  const s = useSession();
  const last = useRef<string | null>(null);
  const lastFull = useRef(Date.now());
  const fn = useRef(reload);
  fn.current = reload;
  const [visible, setVisible] = useState(true);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled || !s.role) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function tick() {
      if (stopped) return;
      if (document.visibilityState === "visible") {
        try {
          const { version } = await api<{ version: string }>("/api/changes", await s.headers());
          const due = Date.now() - lastFull.current > FULL_MS;
          if ((last.current !== null && version !== last.current) || due) {
            lastFull.current = Date.now();
            await fn.current();
          }
          last.current = version;
          setCheckedAt(new Date());
        } catch { /* offline or rate limited: try again next tick */ }
      }
      timer = setTimeout(tick, POLL_MS);
    }
    const onVis = () => {
      const v = document.visibilityState === "visible";
      setVisible(v);
      if (v) { clearTimeout(timer); tick(); }
    };
    document.addEventListener("visibilitychange", onVis);
    timer = setTimeout(tick, POLL_MS);
    return () => { stopped = true; clearTimeout(timer); document.removeEventListener("visibilitychange", onVis); };
  }, [enabled, s]);

  return { visible, checkedAt };
}

/** Small "Live" indicator for pages that auto-refresh. */
export function liveText(visible: boolean, checkedAt: Date | null): string {
  if (!visible) return "Auto-refresh paused (tab hidden)";
  return checkedAt ? `Live: checks for changes every 12 s · last check ${checkedAt.toLocaleTimeString()}` : "Live: checks for changes every 12 s";
}
