// The replay served by api/replay.py (GET /api/replay, SSE /api/events). Keep in step with build_replay().

export type BeatKind = "think" | "queue" | "talk" | "compute" | "lock" | "refuse";

export interface Beat {
  kind: BeatKind;
  actor: string;
  target?: string;
  place?: string; // gpu1 | gpu2 | vault
  slice: string;
  text: string;
  task?: string | null;
  call?: number; // think: key into calls
  msg?: number; // talk: id in msgs
  real?: number | null; // think: real seconds; null while the call is in flight
  frm?: string; // refuse
  to?: string;
  ts: number; // real epoch seconds
  at: number; // display seconds
  dur: number;
  campaign: number;
}

export interface Call {
  seat: string;
  tier: string | null;
  s: number;
  error: string | null;
  prompt: string;
  reasoning: string;
  reply: string;
}

export interface Message {
  id: number;
  at: number;
  frm: string;
  to: string;
  slice: string;
  body: string;
}

export interface SliceEvent {
  at: number;
  ts: number;
  seat: string;
  frm: string;
  to: string;
  ok: boolean;
  note: string;
}

export interface Slice {
  id: string;
  title: string;
  key: string;
  stage: string;
  events: SliceEvent[];
  locked: {
    statement: string;
    digest: string;
    judge: string;
    design: string;
    months: string[];
    alpha: number;
    sesoi: number;
  } | null;
  decision: { decision: string; point: number; lo: number; hi: number; alpha: number; sesoi: number } | null;
  run: { data: string; design: string; judge: string; stations: number; rel: (number | null)[] } | null;
  pilot: Record<string, number | string | boolean> | null;
  replication: Record<string, unknown> | null;
}

export interface Seat {
  kind: "llm" | "code";
  tier: string | null;
  owns: string;
}

export interface Replay {
  rig: string;
  mission: string;
  seats: Record<string, Seat>;
  stages: string[];
  standards: Record<string, number>;
  beats: Beat[];
  total: number;
  calls: Record<string, Call>;
  msgs: Message[];
  slices: Slice[];
  ledger: { campaigns?: { campaign: number; promoted: string | null }[] };
}

export interface RunInfo {
  name: string;
  rig: string;
  modified: number;
  recorded: boolean;
}
