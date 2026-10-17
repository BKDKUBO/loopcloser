"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Status() {
  const [data, setData] = useState<unknown>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api("/ready", {}).then(setData).catch((e: Error) => setErr(e.message)); }, []);
  return (
    <>
      <h1>System status</h1>
      {err ? <p className="error" role="alert">API not ready: {err}</p> : <pre>{JSON.stringify(data, null, 2)}</pre>}
    </>
  );
}
