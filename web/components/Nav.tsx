"use client";

import Link from "next/link";
import { useSession } from "@/lib/auth";
import { ROLES } from "@/lib/types";

export function Nav() {
  const s = useSession();
  const label = ROLES.find((r) => r.id === s.role)?.label;
  return (
    <header>
      <div className="banner" role="status">Demo mode. All records are fictional (SIMULATED).</div>
      <nav aria-label="Main">
        <strong>LoopCloser</strong>
        <Link href="/today">Today</Link>
        <Link href="/pathways">Pathways</Link>
        <Link href="/status">System status</Link>
        <span style={{ marginLeft: "auto" }} className="muted">
          {s.role ? `Signed in as ${label}` : "Not signed in"}
        </span>
        {s.role ? <button onClick={() => s.signOut()}>Sign out</button> : <Link href="/">Sign in</Link>}
      </nav>
    </header>
  );
}
