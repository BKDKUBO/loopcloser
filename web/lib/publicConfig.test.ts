import { describe, expect, it } from "vitest";
import { loadDemoMode } from "./publicConfig";

const ok = (body: unknown) => (async () => new Response(JSON.stringify(body), { status: 200 })) as unknown as typeof fetch;

describe("loadDemoMode", () => {
  it("reads demo_mode from the API", async () => {
    expect(await loadDemoMode("/x", ok({ demo_mode: true }))).toBe(true);
    expect(await loadDemoMode("/x", ok({ demo_mode: false }))).toBe(false);
  });
  it("returns null on a server error", async () => {
    const bad = (async () => new Response("no", { status: 503 })) as unknown as typeof fetch;
    expect(await loadDemoMode("/x", bad)).toBeNull();
  });
  it("returns null when the server never answers (timeout)", async () => {
    const hang = ((_u: string, init?: RequestInit) => new Promise((_res, rej) => {
      init?.signal?.addEventListener("abort", () => rej(new Error("aborted")));
    })) as unknown as typeof fetch;
    expect(await loadDemoMode("/x", hang, 20)).toBeNull();
  });
});
