"use client";

import { useState } from "react";
import { api, ApiError } from "./api";
import { useSession } from "./auth";
import type { CaseView } from "./types";

/** Runs one case action against the API and reports errors with their guard rule id. */
export function useCaseAction(onDone: (c: CaseView) => void) {
  const s = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run<T = CaseView>(path: string, body: unknown, pick?: (r: T) => CaseView, ok?: string) {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await api<T>(path, await s.headers(), { method: "POST", body: JSON.stringify(body) });
      onDone(pick ? pick(r) : (r as unknown as CaseView));
      if (ok) setNotice(ok);
      return r;
    } catch (e) {
      const err = e as ApiError;
      setError(err.ruleId ? `${err.message} (rule ${err.ruleId})` : err.message);
      return null;
    } finally { setBusy(false); }
  }
  return { run, busy, error, notice };
}
