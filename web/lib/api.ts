// In production the API is same-origin (Firebase Hosting rewrites /api/** to Cloud Run).
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string, public ruleId?: string, public requestId?: string) {
    super(message);
  }
}

export async function api<T>(path: string, headers: Record<string, string>, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...headers, ...(init.headers as Record<string, string>) },
  });
  if (!res.ok) {
    let body: { detail?: string; rule_id?: string; request_id?: string } = {};
    try { body = await res.json(); } catch { /* not json */ }
    const msg = res.status === 429 ? "Too many requests. Please wait a moment." : body.detail ?? `Error ${res.status}`;
    throw new ApiError(res.status, msg, body.rule_id, body.request_id);
  }
  return res.json() as Promise<T>;
}
