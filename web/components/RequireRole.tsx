"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useSession } from "@/lib/auth";

export function RequireRole({ children }: { children: ReactNode }) {
  const s = useSession();
  if (!s.ready) return <p>Loading…</p>;
  if (!s.role) return <p>Please <Link href="/">sign in</Link> to continue.</p>;
  return <>{children}</>;
}
