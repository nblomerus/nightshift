"use client";

import { useCallback, useEffect, useState } from "react";

import type { OwnerRequest } from "./types";

const POLL_MS = 15000;

// The PI's requests to the owner, lab-wide (not per run): polled, so the mailbox lights up while a run is going.
export function useRequests(rig: string) {
  const [requests, setRequests] = useState<OwnerRequest[]>([]);
  const q = rig ? `?rig=${encodeURIComponent(rig)}` : "";
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetch(`/api/requests${q}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((rs: OwnerRequest[]) => !cancelled && setRequests(rs))
        .catch(() => undefined);
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [q]);
  const reply = useCallback(
    async (id: string, text: string) => {
      const r = await fetch(`/api/requests/reply${q}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, text }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? `HTTP ${r.status}`);
      setRequests(await r.json());
    },
    [q],
  );
  return { requests, open: requests.filter((r) => r.status === "open").length, reply };
}

// A request as a brief to paste to whoever will act on it.
export function requestBrief(r: OwnerRequest): string {
  const lines = [`The Nightshift PI asks (${r.id}, asked ${r.asks}x):`, `What: ${r.what}`];
  if (r.why) lines.push(`Why: ${r.why}`);
  if (r.how) lines.push(`How: ${r.how}`);
  if (r.done) lines.push(`Done when: ${r.done}`);
  lines.push(`When it is handled, answer it: make reply REQUEST=${r.id} MSG="..."`);
  return lines.join("\n");
}
