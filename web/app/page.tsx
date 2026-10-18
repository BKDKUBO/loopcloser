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

      <h2>Staff sign-in</h2>
      <p className="muted">Real accounts use Firebase Auth. Your role (worker, coordinator, supervisor, program
        manager) is set by an administrator and checked on every request.</p>
      <button className="primary" disabled={!s.firebaseConfigured} onClick={async () => {
        try { await s.signInWithGoogle(); router.push("/today"); }
        catch { setErr("Sign-in failed. Please try again."); }
      }}>Sign in with Google</button>
      {!s.firebaseConfigured && <p className="muted">Firebase sign-in is not configured in this build.</p>}

      {s.demoMode && (
        <section className="card demo" aria-labelledby="demo-h" style={{ marginTop: 24 }}>
          <h2 id="demo-h">Demo mode: pick a role</h2>
          <p>For judges. Each button signs you in as a fictional demo account with that role&apos;s permissions.
            Demo mode is switched on by a server setting and is off for real deployments.</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {ROLES.map((r) => (
              <button key={r.id} onClick={() => { s.setDemoRole(r.id as Role); router.push("/today"); }}>
                {r.label} (demo)
              </button>
            ))}
          </div>
        </section>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}
