// Pure scene derivation: (replay, t) -> everything the lab floor draws. No React, no clocks, so the same code
// drives replay (t from the player) and live mode (t = the end of the latest snapshot), and is unit-tested.

import { besideSpot, MAILBOX_SPOT, seatSpot, SEAT_ORDER, VAULT_SPOT, workstationSpot } from "./layout";
import type { Beat, BeatKind, Call, Replay, Slice } from "./types";

export type Action = "idle" | "type" | "compute" | "talk" | "listen" | "lock" | "refused";
export type Tone = BeatKind | "listen";

export interface BubbleBox {
  seat: string;
  title?: string; // a thinking seat: its task; `text` is then its reasoning at this moment
  text: string;
  tone: Tone;
  strong: boolean; // the current beat; weak = what this seat was last doing
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SeatState {
  seat: string;
  x: number;
  y: number;
  action: Action;
  current: boolean;
  lastBeat: number | null; // index of this seat's latest beat at t
}

export interface Scene {
  index: number; // current beat, -1 before the first
  beat: Beat | null;
  frac: number; // progress through the current beat, 0..1
  seats: SeatState[];
  bubbles: BubbleBox[];
  monitors: Record<string, boolean>; // desk seat or gpu id -> lit
  campaign: number;
  activeSlice: string;
  mail: number; // open requests to the owner: the mailbox is lit while > 0
}

export const BUBBLE_W = 176;
export const BUBBLE_H = 46;
export const THOUGHT_W = 236;
export const THOUGHT_H = 78;
const THOUGHT_CHARS = 150;

// A seat's reasoning in its own words: models quote their prompt back to themselves ("You may also propose ONE new
// idea..."), echo JSON and paste code; none of that says what the seat thinks, so the bubble leaves it out.
export function ownWords(text: string): string {
  let out = text.replace(/```[\s\S]*?(```|$)/g, " ").replace(/"[^"]{14,}"/g, "“…”");
  for (let prev = ""; prev !== out; ) {
    prev = out;
    out = out.replace(/\{[^{}]*\}/g, "⟨…⟩"); // innermost JSON first, then its parents (the placeholder has no braces)
  }
  return out.replace(/⟨…⟩/g, "{…}").replace(/\s+/g, " ").trim();
}

// What a thinking seat is thinking at `frac` of its call: in replay, the stretch of its recorded reasoning that far in
// (so the bubble keeps moving); for a call still running, the latest reasoning the stream reported.
export const SECONDS_PER_THOUGHT = 2.5; // display seconds each sentence stays in a bubble: long enough to read

function sentences(text: string): string[] {
  return text
    .split(/(?<=[.?!])\s+/)
    .map((x) => x.trim())
    .filter((x) => x.length >= 12);
}

function fit(sentence: string): string {
  return sentence.length <= THOUGHT_CHARS ? sentence : sentence.slice(0, THOUGHT_CHARS - 1).replace(/\s+\S*$/, "") + "…";
}

// What a thinking seat is thinking, one sentence at a time. In replay, sentences are taken evenly through its recorded
// reasoning and each stays SECONDS_PER_THOUGHT display seconds, so the bubble moves at reading pace however long the
// reasoning is; the last one is where it ended up. For a call still running, the latest complete sentence streamed.
export function thoughtAt(call: Call | undefined, frac: number, dur = 12): string {
  if (!call) return "";
  const text = ownWords(call.reasoning || "");
  if (!text) return call.in_flight ? "…" : call.reply ? fit(call.reply.replace(/\s+/g, " ")) : "";
  const all = sentences(text);
  if (!all.length) return fit(text);
  if (call.in_flight) {
    const done = text.endsWith(".") || text.endsWith("?") || text.endsWith("!");
    return fit(all[done || all.length === 1 ? all.length - 1 : all.length - 2]);
  }
  const n = Math.max(1, Math.min(all.length, Math.round(dur / SECONDS_PER_THOUGHT)));
  const k = Math.min(n - 1, Math.floor(Math.max(0, frac) * n));
  const idx = n === 1 ? all.length - 1 : Math.round((k * (all.length - 1)) / (n - 1));
  return fit(all[idx]);
}
export const HOLD = 24; // display seconds a finished action stays visible as a faint bubble

export function beatIndexAt(beats: Beat[], t: number): number {
  let lo = 0,
    hi = beats.length - 1,
    ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (beats[mid].at <= t) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}

export function spotFor(seat: string, beat: Beat | null): { x: number; y: number; action: Action } {
  const home = seatSpot(seat);
  if (!beat) return { ...home, action: "idle" };
  if (beat.actor === seat) {
    switch (beat.kind) {
      case "think":
        return { ...home, action: "type" };
      case "compute":
        return { ...workstationSpot(beat.place ?? ""), action: "compute" };
      case "lock":
        return { ...VAULT_SPOT, action: "lock" };
      case "talk":
      case "queue":
        return beat.target ? { ...besideSpot(beat.target), action: "talk" } : { ...home, action: "talk" };
      case "refuse":
        return { ...home, action: "refused" };
    }
  }
  if (beat.target === seat && (beat.kind === "talk" || beat.kind === "queue")) return { ...home, action: "listen" };
  return { ...home, action: "idle" };
}

function overlaps(a: BubbleBox, b: BubbleBox): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

// Place bubbles above heads; the current beat's bubbles first. A bubble that collides moves up a row; a faint
// bubble that still collides is dropped rather than covering a live one.
export function layoutBubbles(wanted: Omit<BubbleBox, "x" | "y" | "w" | "h">[], seats: SeatState[]): BubbleBox[] {
  const pos = new Map(seats.map((s) => [s.seat, s]));
  const placed: BubbleBox[] = [];
  const order = [...wanted].sort((a, b) => Number(b.strong) - Number(a.strong));
  for (const w of order) {
    const s = pos.get(w.seat);
    if (!s) continue;
    const width = w.text === "…" ? 40 : w.title ? THOUGHT_W : BUBBLE_W;
    const height = w.title ? THOUGHT_H : BUBBLE_H;
    const box: BubbleBox = { ...w, w: width, h: height, x: Math.max(4, s.x + 24 - width / 2), y: s.y - height - 10 };
    let ok = false;
    for (let tries = 0; tries < 3; tries++) {
      if (!placed.some((p) => overlaps(p, box))) {
        ok = true;
        break;
      }
      box.y -= box.h + 6;
    }
    if (ok || w.strong) placed.push(box);
  }
  return placed;
}

// `mail`: open requests to the owner. While there are any, the PI waits at the mailbox whenever it has nothing else to
// do (its own beats and being talked to still take it back to work).
export function sceneAt(replay: Replay, t: number, mail = 0): Scene {
  const beats = replay.beats;
  const index = beatIndexAt(beats, t);
  const beat = index >= 0 ? beats[index] : null;
  const frac = beat ? Math.max(0, Math.min(1, (t - beat.at) / beat.dur)) : 0;
  const seatNames = SEAT_ORDER.filter((s) => s in replay.seats || replay.seats === undefined);
  const last: Record<string, number> = {};
  for (let k = 0; k <= index; k++) last[beats[k].actor] = k;
  const seats: SeatState[] = seatNames.map((seat) => {
    const spot = spotFor(seat, beat);
    const { x, y } = seat === "pi" && mail > 0 && spot.action === "idle" ? MAILBOX_SPOT : spot;
    return { seat, x, y, action: spot.action, current: beat?.actor === seat, lastBeat: last[seat] ?? null };
  });
  const wanted: Omit<BubbleBox, "x" | "y" | "w" | "h">[] = [];
  for (const s of seats) {
    if (beat && s.current && beat.kind === "think") {
      const call = beat.call !== undefined ? replay.calls[String(beat.call)] : undefined;
      wanted.push({ seat: s.seat, title: beat.text, text: thoughtAt(call, frac, beat.dur) || beat.text, tone: "think", strong: true });
    } else if (beat && s.current) wanted.push({ seat: s.seat, text: beat.text, tone: beat.kind, strong: true });
    else if (s.action === "listen") wanted.push({ seat: s.seat, text: "…", tone: "listen", strong: true });
    else if (s.lastBeat !== null) {
      const b = beats[s.lastBeat];
      if (t - (b.at + b.dur) < HOLD && b.kind !== "queue") wanted.push({ seat: s.seat, text: b.text, tone: b.kind, strong: false });
    }
    if (s.seat === "pi" && mail > 0 && s.action === "idle" && !wanted.some((w) => w.seat === "pi"))
      wanted.push({ seat: "pi", text: `Waiting on the owner: ${mail} request${mail > 1 ? "s" : ""} in the mailbox`, tone: "talk", strong: false });
  }
  const monitors: Record<string, boolean> = {};
  if (beat?.kind === "think") monitors[beat.actor] = true;
  if (beat?.kind === "compute" && beat.place) monitors[beat.place] = true;
  let activeSlice = "";
  for (let k = index; k >= 0 && !activeSlice; k--) activeSlice = beats[k].slice;
  return {
    index,
    beat,
    frac,
    seats,
    bubbles: layoutBubbles(wanted, seats),
    monitors,
    campaign: beat?.campaign ?? 1,
    activeSlice,
    mail,
  };
}

// ---------------------------------------------------------------------------- slices

export const PIPELINE: { key: string; label: string; stages: string[] }[] = [
  { key: "question", label: "question", stages: ["question"] },
  { key: "hypothesis", label: "hypothesis", stages: ["hypothesis"] },
  { key: "prereg_draft", label: "prereg", stages: ["prereg_draft"] },
  { key: "review", label: "review", stages: ["design_review"] },
  { key: "approved", label: "approved", stages: ["approved_design", "implementation_checked", "controls_passed"] },
  { key: "locked", label: "locked", stages: ["locked"] },
  { key: "run", label: "run", stages: ["run"] },
  { key: "analysed", label: "analysed", stages: ["analysed", "replication_queued"] },
  { key: "replicated", label: "replicated", stages: ["replicated", "not_replicated"] },
  { key: "written", label: "written", stages: ["written"] },
];

// The stage a slice is in at display time t (null before it exists). Refused moves don't change the stage.
export function stageAt(slice: Slice, t: number): string | null {
  let stage: string | null = null;
  for (const e of slice.events) {
    if (e.at > t) break;
    if (e.ok) stage = e.to;
  }
  return stage;
}

// How far along the pipeline the slice got before t: index into PIPELINE (the furthest step reached).
export function pipelineReached(slice: Slice, t: number): { reached: number; current: number; parked: boolean } {
  let reached = -1,
    current = -1,
    parked = false;
  for (const e of slice.events) {
    if (e.at > t) break;
    if (!e.ok) continue;
    if (e.to === "parked") {
      parked = true;
      continue;
    }
    const step = PIPELINE.findIndex((p) => p.stages.includes(e.to));
    if (step >= 0) {
      current = step;
      reached = Math.max(reached, step);
    }
  }
  return { reached, current, parked };
}

export function decisionVisible(slice: Slice, t: number): boolean {
  return slice.events.some((e) => e.ok && e.to === "analysed" && e.at <= t);
}

export function campaignOf(sliceId: string): number {
  const m = /^C(\d+)-/.exec(sliceId);
  return m ? Number(m[1]) : 0;
}

export function mmss(s: number): string {
  s = Math.max(0, s);
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "–";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}
