"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { SafetyLine } from "@/components/SafetyLine";
import { useSession } from "@/lib/auth";
import { ROLES, type Role } from "@/lib/types";

// Set NEXT_PUBLIC_GOOGLE_SIGNIN=off at build time until the Google provider is enabled in Firebase Auth.
const GOOGLE_SIGNIN_ON = process.env.NEXT_PUBLIC_GOOGLE_SIGNIN !== "off";

export default function SignIn() {
  const s = useSession();
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);

  const staffSignIn = (
    <>
      <p className="muted">Real accounts use Firebase Auth. Your role (worker, coordinator, supervisor, program
        manager) is set by an administrator and checked on every request.</p>
      <button className="primary" disabled={!s.firebaseConfigured || !GOOGLE_SIGNIN_ON} onClick={async () => {
        try { await s.signInWithGoogle(); router.push("/today"); }
        catch { setErr("Sign-in failed. Please try again."); }
      }}>Sign in with Google</button>
      {!s.firebaseConfigured && <p className="muted">Staff sign-in is not set up in this build.</p>}
      {s.firebaseConfigured && !GOOGLE_SIGNIN_ON && (
        <p className="muted">Google sign-in is not switched on yet for this deployment.</p>
      )}
    </>
  );

  return (
    <section aria-labelledby="h">
      <h1 id="h">LoopCloser</h1>
      <p>LoopCloser makes sure every actionable screening result has a next action, an owner, a deadline,
        and a documented outcome. It tracks follow-up work; it is not a diagnostic tool.</p>

      {!s.ready && (
        <p className="card" role="status">Starting the demo server. The first visit can take up to 10 seconds.</p>
      )}

      {s.ready && s.demoMode && (
        <section className="card demo" aria-labelledby="demo-h">
          <h2 id="demo-h">Try it now: pick a role</h2>
          <p>For judges. No password. Each button signs you in as a fictional demo account with that role&apos;s
            permissions. All records are fictional (SIMULATED).</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {ROLES.map((r) => (
              <button key={r.id} className="primary" onClick={() => { s.setDemoRole(r.id as Role); router.push("/today"); }}>
                {r.label}
              </button>
            ))}
          </div>
          <p className="muted">Suggested start: Coordinator. Switch to Supervisor to sign off and close a case.</p>
        </section>
      )}

      {s.ready && !s.demoMode && !s.firebaseConfigured && (
        <p className="error" role="alert">The demo server did not answer. Please reload the page in a few seconds.</p>
      )}

      <SafetyLine />

      {s.ready && s.demoMode ? (
        <details style={{ marginTop: 24 }}>
          <summary>Staff sign-in (real accounts, not needed for the demo)</summary>
          {staffSignIn}
        </details>
      ) : (
        <>
          <h2>Staff sign-in</h2>
          {staffSignIn}
        </>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}
