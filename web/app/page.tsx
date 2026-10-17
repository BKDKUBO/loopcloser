"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useSession } from "@/lib/auth";
import { ROLES, type Role } from "@/lib/types";

export default function SignIn() {
  const s = useSession();
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);

  return (
    <section aria-labelledby="h">
      <h1 id="h">Sign in</h1>
      <p>LoopCloser makes sure every actionable screening result has a next action, an owner, a deadline,
        and a documented outcome. It is not a diagnostic tool.</p>
      {s.mode === "demo" ? (
        <>
          <p className="muted">Demo role switcher. Pick a role to see what it can do.</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {ROLES.map((r) => (
              <button key={r.id} className="primary"
                onClick={() => { s.setDemoRole(r.id as Role); router.push("/today"); }}>
                {r.label}
              </button>
            ))}
          </div>
        </>
      ) : (
        <button className="primary" onClick={async () => {
          try { await s.signInWithGoogle(); router.push("/today"); }
          catch { setErr("Sign-in failed. Please try again."); }
        }}>Sign in with Google</button>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}
