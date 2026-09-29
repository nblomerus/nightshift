"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { beatIndexAt } from "./scene";
import type { Beat } from "./types";

export const SPEEDS = [1, 2, 4, 8];

export interface Player {
  t: number;
  playing: boolean;
  speed: number;
  follow: boolean; // live: stay at the newest beat
  setT: (t: number) => void;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  setSpeed: (s: number) => void;
  prev: () => void;
  next: () => void;
  restart: () => void;
  goLive: () => void;
}

// The replay clock. In live mode it keeps up with the newest beat unless the viewer scrubs away.
export function useReplay(beats: Beat[], total: number, live: boolean, startAt: number | null = null): Player {
  const [t, setTState] = useState(startAt ?? 0);
  const [playing, setPlaying] = useState(startAt === null); // a deep link opens paused at its moment
  const [speed, setSpeed] = useState(2);
  const [detached, setDetached] = useState(false); // live: the viewer scrubbed away from the edge
  const [prevLive, setPrevLive] = useState(live);
  if (live !== prevLive) {
    setPrevLive(live);
    setDetached(false);
  }
  const follow = live && !detached;
  const last = useRef<number | null>(null);

  useEffect(() => {
    let raf = 0;
    const tick = (now: number) => {
      if (last.current !== null && playing) {
        const dt = ((now - last.current) / 1000) * speed;
        setTState((cur) => Math.min(total, cur + dt));
      }
      last.current = now;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      last.current = null;
    };
  }, [playing, speed, total]);

  // Live and following: stay a few seconds behind the newest beat, so arrivals still animate.
  const shown = follow ? Math.max(t, total - 6) : t;

  const setT = useCallback(
    (v: number) => {
      setTState(Math.max(0, Math.min(total, v)));
      setDetached(true);
    },
    [total],
  );
  const jump = useCallback(
    (dir: -1 | 1) => {
      setTState((cur) => {
        const i = beatIndexAt(beats, cur);
        const j = Math.max(0, Math.min(beats.length - 1, i + dir));
        return beats[j]?.at ?? 0;
      });
      setPlaying(false);
      setDetached(true);
    },
    [beats],
  );

  const player: Player = {
    t: shown,
    playing,
    speed,
    follow,
    setT,
    play: () => setPlaying(true),
    pause: () => setPlaying(false),
    toggle: () => {
      if (!playing && shown >= total) setTState(0);
      setPlaying((p) => !p);
    },
    setSpeed,
    prev: () => jump(-1),
    next: () => jump(1),
    restart: () => {
      setTState(0);
      setDetached(true);
    },
    goLive: () => {
      setDetached(false);
      setPlaying(true);
      setTState(Math.max(0, total - 6));
    },
  };

  // Keyboard: space play/pause, arrows step beats, 1-4 speed. Ignored while typing in a field.
  const ref = useRef(player);
  useEffect(() => {
    ref.current = player;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const p = ref.current;
      if (e.key === " ") {
        e.preventDefault();
        p.toggle();
      } else if (e.key === "ArrowLeft") p.prev();
      else if (e.key === "ArrowRight") p.next();
      else if (["1", "2", "3", "4"].includes(e.key)) p.setSpeed(SPEEDS[Number(e.key) - 1]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return player;
}
