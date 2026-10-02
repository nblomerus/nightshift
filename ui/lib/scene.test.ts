import { describe, expect, it } from "vitest";

import { besideSpot, MAILBOX_SPOT, seatSpot, VAULT_SPOT, workstationSpot } from "./layout";
import { beatIndexAt, BUBBLE_H, layoutBubbles, pipelineReached, ownWords, sceneAt, stageAt, thoughtAt } from "./scene";
import type { Beat, Replay, Slice } from "./types";

const seats = Object.fromEntries(
  ["pi", "methodologist", "critic", "writer", "replicator", "statistician", "experimenter"].map((s) => [
    s,
    { kind: s === "statistician" ? "code" : "llm", tier: "reasoning", owns: "" },
  ]),
) as Replay["seats"];

function beat(kind: Beat["kind"], actor: string, at: number, extra: Partial<Beat> = {}): Beat {
  return { kind, actor, slice: "C1-S1-holidays", text: `${kind} by ${actor}`, ts: at, at, dur: 5, campaign: 1, ...extra };
}

const beats: Beat[] = [
  beat("think", "pi", 0, { text: "Planning the campaign", slice: "" }),
  beat("queue", "pi", 5, { target: "methodologist" }),
  beat("think", "methodologist", 10),
  beat("talk", "critic", 15, { target: "methodologist", msg: 1 }),
  beat("compute", "experimenter", 20, { place: "gpu1", task: "run_experiment" }),
  beat("lock", "statistician", 25, { place: "vault" }),
];
const replay = { seats, beats, total: 30, calls: {}, msgs: [], slices: [], stages: [], standards: {}, rig: "", mission: "", ledger: {} } as Replay;

describe("sceneAt", () => {
  it("finds the beat in play at t", () => {
    expect(beatIndexAt(beats, -1)).toBe(-1);
    expect(beatIndexAt(beats, 0)).toBe(0);
    expect(beatIndexAt(beats, 14.9)).toBe(2);
    expect(beatIndexAt(beats, 99)).toBe(5);
  });

  it("puts a thinking seat at its own desk, typing, with its monitor lit", () => {
    const s = sceneAt(replay, 11);
    const m = s.seats.find((x) => x.seat === "methodologist")!;
    expect([m.x, m.y, m.action]).toEqual([seatSpot("methodologist").x, seatSpot("methodologist").y, "type"]);
    expect(s.monitors).toEqual({ methodologist: true });
    expect(s.frac).toBeCloseTo(0.2);
  });

  it("walks a talking seat to its listener, who waits with a '…' bubble", () => {
    const s = sceneAt(replay, 16);
    const critic = s.seats.find((x) => x.seat === "critic")!;
    expect([critic.x, critic.y, critic.action]).toEqual([besideSpot("methodologist").x, besideSpot("methodologist").y, "talk"]);
    expect(s.seats.find((x) => x.seat === "methodologist")!.action).toBe("listen");
    expect(s.bubbles.find((b) => b.seat === "methodologist")!.text).toBe("…");
  });

  it("sends experiments to their workstation and locks to the vault", () => {
    const run = sceneAt(replay, 21).seats.find((x) => x.seat === "experimenter")!;
    expect([run.x, run.y, run.action]).toEqual([workstationSpot("gpu1").x, workstationSpot("gpu1").y, "compute"]);
    expect(sceneAt(replay, 21).monitors).toEqual({ gpu1: true });
    const lock = sceneAt(replay, 26).seats.find((x) => x.seat === "statistician")!;
    expect([lock.x, lock.y]).toEqual([VAULT_SPOT.x, VAULT_SPOT.y]);
  });

  it("keeps a faint bubble of what a seat just did, and drops it after a while", () => {
    expect(sceneAt(replay, 16).bubbles.find((b) => b.seat === "pi")).toBeUndefined(); // last beat was a queue
    const faint = sceneAt(replay, 21).bubbles.find((b) => b.seat === "methodologist")!;
    expect(faint.strong).toBe(false);
    expect(sceneAt(replay, 60).bubbles.some((b) => !b.strong)).toBe(false);
  });

  it("remembers the active slice through beats without one", () => {
    expect(sceneAt(replay, 1).activeSlice).toBe("");
    expect(sceneAt(replay, 6).activeSlice).toBe("C1-S1-holidays");
  });
});

describe("layoutBubbles", () => {
  it("stacks colliding bubbles instead of overlapping them", () => {
    const st = [
      { seat: "a", x: 100, y: 200, action: "type" as const, current: true, lastBeat: 0 },
      { seat: "b", x: 110, y: 200, action: "idle" as const, current: false, lastBeat: 0 },
    ];
    const out = layoutBubbles(
      [
        { seat: "a", text: "x", tone: "think", strong: true },
        { seat: "b", text: "y", tone: "think", strong: false },
      ],
      st,
    );
    expect(out).toHaveLength(2);
    expect(Math.abs(out[0].y - out[1].y)).toBeGreaterThanOrEqual(BUBBLE_H);
  });
});

describe("slices", () => {
  const slice = {
    id: "C1-S1-holidays",
    events: [
      { at: 1, to: "hypothesis", ok: true },
      { at: 2, to: "prereg_draft", ok: true },
      { at: 3, to: "run", ok: false },
      { at: 4, to: "design_review", ok: true },
      { at: 5, to: "parked", ok: true },
    ],
  } as unknown as Slice;

  it("ignores refused moves and reports parking", () => {
    expect(stageAt(slice, 0)).toBeNull();
    expect(stageAt(slice, 3.5)).toBe("prereg_draft");
    expect(pipelineReached(slice, 4.5)).toEqual({ reached: 3, current: 3, parked: false });
    expect(pipelineReached(slice, 9).parked).toBe(true);
  });
});

describe("thinking bubbles", () => {
  const reasoning = Array.from({ length: 60 }, (_, k) => `Thought number ${k} is here.`).join(" ");
  const call = { seat: "pi", tier: "reasoning", s: 10, error: null, prompt: "p", reasoning, reply: "{}" };

  it("moves one whole sentence at a time, at reading pace, through the recorded reasoning", () => {
    const shown = new Set([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99].map((f) => thoughtAt(call, f, 12)));
    expect(shown.size).toBe(5); // 12 display seconds / 2.5 per sentence
    expect(thoughtAt(call, 0, 12)).toBe("Thought number 0 is here.");
    expect(thoughtAt(call, 0.99, 12)).toBe("Thought number 59 is here."); // where the reasoning ended up
    expect(thoughtAt(call, 0.1, 12)).toBe(thoughtAt(call, 0.15, 12)); // no sweep within a sentence's slot
  });

  it("shows the latest complete sentence while a call is still running", () => {
    const live = { ...call, in_flight: true, s: null, reasoning: "Is the comparator explicit? Yes it names the champ" };
    expect(thoughtAt(live, 0)).toBe("Is the comparator explicit?");
  });

  it("titles a thinking seat's bubble with its task and fills it with the thought", () => {
    const b = { ...beats[2], call: 7 };
    const withCalls = { ...replay, calls: { "7": call }, beats: [...beats.slice(0, 2), b, ...beats.slice(3)] } as Replay;
    const bubble = sceneAt(withCalls, 12).bubbles.find((x) => x.seat === "methodologist")!;
    expect(bubble.title).toBe(b.text);
    expect(bubble.text).toMatch(/^Thought number \d+ is here\.$/);
  });
});

describe("own words", () => {
  it("leaves out quoted prompt text, JSON and code, and keeps the seat's own reasoning", () => {
    const r =
      'Maybe include rationale. The message says "You may also propose ONE new idea... Pick it as {key}". ' +
      'Reply {"picks": [{"key": "new", "name": "x"}]} then ```python\nprint(1)\n``` Lessons say screens gate.';
    const out = ownWords(r);
    expect(out).toContain("Maybe include rationale.");
    expect(out).toContain("Lessons say screens gate.");
    expect(out).not.toContain("You may also propose");
    expect(out).not.toContain('"picks"');
    expect(out).not.toContain("print(1)");
  });
});

describe("the mailbox", () => {
  it("sends an idle PI to the mailbox while requests to the owner are open, and lights it", () => {
    const s = sceneAt(replay, 11, 2); // the methodologist is thinking; the PI has nothing to do
    const pi = s.seats.find((x) => x.seat === "pi")!;
    expect([pi.x, pi.y, pi.action]).toEqual([MAILBOX_SPOT.x, MAILBOX_SPOT.y, "idle"]);
    expect(s.mail).toBe(2);
    expect(s.bubbles.some((b) => b.seat === "pi" && b.text.includes("2 requests"))).toBe(true);
  });

  it("keeps the PI at work when it has a beat, and at its desk when nothing is open", () => {
    const busy = sceneAt(replay, 1, 2).seats.find((x) => x.seat === "pi")!;
    expect([busy.x, busy.y, busy.action]).toEqual([seatSpot("pi").x, seatSpot("pi").y, "type"]);
    const none = sceneAt(replay, 11).seats.find((x) => x.seat === "pi")!;
    expect([none.x, none.y]).toEqual([seatSpot("pi").x, seatSpot("pi").y]);
    expect(sceneAt(replay, 11).mail).toBe(0);
  });
});
