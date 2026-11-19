/** How long the sign-in page waits for the API's public config before showing the reload message. */
export const PUBLIC_CONFIG_TIMEOUT_MS = 40_000;

/**
 * Ask the API whether demo mode is on. Returns null when the server does not answer in time or errors,
 * so the sign-in page can show "did not answer, reload" instead of waiting forever.
 */
export async function loadDemoMode(
  url: string,
  fetchFn: typeof fetch = fetch,
  timeoutMs: number = PUBLIC_CONFIG_TIMEOUT_MS,
): Promise<boolean | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetchFn(url, { signal: ctrl.signal });
    if (!r.ok) return null;
    const cfg = (await r.json()) as { demo_mode?: unknown };
    return Boolean(cfg.demo_mode);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
