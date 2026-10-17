"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Role } from "./types";

export const AUTH_MODE = (process.env.NEXT_PUBLIC_AUTH_MODE ?? "demo") as "demo" | "firebase";

interface Session {
  mode: "demo" | "firebase";
  role: Role | null;
  uid: string | null;
  ready: boolean;
  headers: () => Promise<Record<string, string>>;
  setDemoRole: (r: Role) => void;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<Session | null>(null);
const DEMO_USERS: Record<Role, string> = {
  worker: "worker-01", coordinator: "coord-01", supervisor: "sup-01", program_manager: "pm-01", patient: "patient-01",
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role | null>(null);
  const [uid, setUid] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (AUTH_MODE === "demo") {
      const r = (localStorage.getItem("lc_demo_role") as Role | null) ?? null;
      setRole(r);
      setUid(r ? DEMO_USERS[r] : null);
      setReady(true);
      return;
    }
    let unsub = () => {};
    import("./firebase").then(async ({ firebaseAuth }) => {
      const { onIdTokenChanged } = await import("firebase/auth");
      unsub = onIdTokenChanged(firebaseAuth(), async (u) => {
        if (!u) { setRole(null); setUid(null); setReady(true); return; }
        const t = await u.getIdTokenResult();
        setRole((t.claims.role as Role) ?? null);
        setUid(u.uid);
        setReady(true);
      });
    });
    return () => unsub();
  }, []);

  const headers = useCallback(async (): Promise<Record<string, string>> => {
    if (AUTH_MODE === "demo") return role ? { "x-demo-role": role, "x-demo-user": DEMO_USERS[role] } : {};
    const { firebaseAuth } = await import("./firebase");
    const u = firebaseAuth().currentUser;
    return u ? { authorization: `Bearer ${await u.getIdToken()}` } : {};
  }, [role]);

  const setDemoRole = (r: Role) => {
    localStorage.setItem("lc_demo_role", r);
    setRole(r);
    setUid(DEMO_USERS[r]);
  };

  const signInWithGoogle = async () => {
    const { firebaseAuth } = await import("./firebase");
    const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
    await signInWithPopup(firebaseAuth(), new GoogleAuthProvider());
  };

  const signOut = async () => {
    if (AUTH_MODE === "demo") { localStorage.removeItem("lc_demo_role"); setRole(null); setUid(null); return; }
    const { firebaseAuth } = await import("./firebase");
    await firebaseAuth().signOut();
  };

  return (
    <Ctx.Provider value={{ mode: AUTH_MODE, role, uid, ready, headers, setDemoRole, signInWithGoogle, signOut }}>
      {children}
    </Ctx.Provider>
  );
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside AuthProvider");
  return s;
}
