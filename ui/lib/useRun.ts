"use client";

import { useEffect, useState } from "react";

import type { Replay, RunInfo } from "./types";

// Runs come from the stdlib floor server (api/floor.py), proxied under /api by next.config.ts.

export function useRuns(): RunInfo[] {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  useEffect(() => {
    fetch("/api/runs")
      .then((r) => (r.ok ? r.json() : []))
      .then(setRuns)
      .catch(() => setRuns([]));
  }, []);
  return runs;
}

export type Mode = "replay" | "live";

export interface RunState {
  replay: Replay | null;
  error: string | null;
  connected: boolean; // live: the event stream is open
}

// Replay: one fetch. Live: a server-sent snapshot every time the run's records change.
export function useRun(run: string | null, mode: Mode): RunState {
  const [state, setState] = useState<RunState>({ replay: null, error: null, connected: false });
  useEffect(() => {
    if (!run) return;
    const q = `run=${encodeURIComponent(run)}`;
    if (mode === "replay") {
      let cancelled = false;
      fetch(`/api/replay?${q}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((replay: Replay) => !cancelled && setState({ replay, error: null, connected: false }))
        .catch((e: Error) => !cancelled && setState({ replay: null, error: e.message, connected: false }));
      return () => {
        cancelled = true;
      };
    }
    const es = new EventSource(`/api/events?${q}`);
    es.addEventListener("replay", (ev) => {
      setState({ replay: JSON.parse((ev as MessageEvent).data), error: null, connected: true });
    });
    es.onerror = () => setState((s) => ({ ...s, connected: false }));
    return () => es.close();
  }, [run, mode]);
  return state;
}
