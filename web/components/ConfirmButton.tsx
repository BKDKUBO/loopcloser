"use client";

import { useState, type ReactNode } from "react";

/**
 * A one-click action with a confirm step. Every status change is a permanent event in the audit log
 * (there is no silent undo), so the first click asks "Are you sure?" inline instead of acting.
 */
export function ConfirmButton({ children, confirm, onConfirm, disabled, primary }: {
  children: ReactNode; confirm: string; onConfirm: () => unknown; disabled?: boolean; primary?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return <button className={primary ? "primary" : undefined} disabled={disabled} onClick={() => setAsking(true)}>{children}</button>;
  }
  return (
    <span className="confirm" role="group" aria-label="Confirm action">
      <span>{confirm}</span>{" "}
      <button className="primary" disabled={disabled} autoFocus
        onClick={async () => { setAsking(false); await onConfirm(); }}>Yes, do it</button>{" "}
      <button onClick={() => setAsking(false)}>Cancel</button>
    </span>
  );
}
