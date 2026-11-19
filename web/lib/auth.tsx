"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { loadDemoMode } from "./publicConfig";
import type { Role } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";
const FIREBASE_CONFIGURED = Boolean(process.env.NEXT_PUBLIC_FIREBASE_API_KEY);

interface Session {
  demoMode: boolean;
  firebaseConfigured: boolean;
  role: Role | null;
  uid: string | null;
  isDemoUser: boolean;
  ready: boolean;
  headers: () => Promise<Record<string, string>>;
  setDemoRole: (r: Role) => void;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<Session | null>(null);
export const DEMO_USERS: Record<Role, string> = {
  worker: "demo-worker-01", coordinator: "demo-coord-01", supervisor: "demo-sup-01",
  program_manager: "demo-pm-01", patient: "demo-patient-01",
};

/**
 * Real auth: Firebase Auth ID token (role from the "role" custom claim) is always supported.
 * Demo mode: only when the API reports DEMO_MODE=true, a labeled role switcher is offered too.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [demoMode, setDemoMode] = useState(false);
  const [role, setRole] = useState<Role | null>(null);
  const [uid, setUid] = useState<string | null>(null);
  const [isDemoUser, setIsDemoUser] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let unsub = () => {};
    (async () => {
      // null = API did not answer in time or errored: treat as non-demo (the sign-in page then asks to reload).
      const demo = (await loadDemoMode(`${API}/api/public-config`)) ?? false;
      setDemoMode(demo);
      const stored = demo ? (localStorage.getItem("lc_demo_role") as Role | null) : null;
      if (!demo) localStorage.removeItem("lc_demo_role");
      if (stored) { setRole(stored); setUid(DEMO_USERS[stored]); setIsDemoUser(true); }
      if (!FIREBASE_CONFIGURED) { setReady(true); return; }
      const { firebaseAuth } = await import("./firebase");
      const { onIdTokenChanged } = await import("firebase/auth");
      unsub = onIdTokenChanged(firebaseAuth(), async (u) => {
        if (u) {
          const t = await u.getIdTokenResult();
          setRole((t.claims.role as Role) ?? null);
          setUid(u.uid);
          setIsDemoUser(false);
        } else if (!localStorage.getItem("lc_demo_role")) {
          setRole(null); setUid(null);
        }
        setReady(true);
      });
    })();
    return () => unsub();
  }, []);

  const headers = useCallback(async (): Promise<Record<string, string>> => {
    if (FIREBASE_CONFIGURED && !isDemoUser) {
      const { firebaseAuth } = await import("./firebase");
      const u = firebaseAuth().currentUser;
      if (u) return { authorization: `Bearer ${await u.getIdToken()}` };
    }
    if (demoMode && isDemoUser && role) return { "x-demo-role": role, "x-demo-user": DEMO_USERS[role] };
    return {};
  }, [role, demoMode, isDemoUser]);

  const setDemoRole = (r: Role) => {
    if (!demoMode) return;
    localStorage.setItem("lc_demo_role", r);
    setRole(r); setUid(DEMO_USERS[r]); setIsDemoUser(true);
  };

  const signInWithGoogle = async () => {
    const { firebaseAuth } = await import("./firebase");
    const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
    localStorage.removeItem("lc_demo_role");
    await signInWithPopup(firebaseAuth(), new GoogleAuthProvider());
  };

  const signOut = async () => {
    localStorage.removeItem("lc_demo_role");
    setRole(null); setUid(null); setIsDemoUser(false);
    if (FIREBASE_CONFIGURED) {
      const { firebaseAuth } = await import("./firebase");
      await firebaseAuth().signOut();
    }
  };

  return (
    <Ctx.Provider value={{ demoMode, firebaseConfigured: FIREBASE_CONFIGURED, role, uid, isDemoUser, ready,
      headers, setDemoRole, signInWithGoogle, signOut }}>
      {children}
    </Ctx.Provider>
  );
}

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside AuthProvider");
  return s;
}
