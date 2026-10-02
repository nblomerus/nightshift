"use client";

import { useState } from "react";

import { LOOKS } from "@/lib/layout";
import { beatIndexAt, decisionVisible, mmss, pct, type Scene, stageAt } from "@/lib/scene";
import type { Beat, OwnerRequest, Replay } from "@/lib/types";
import { requestBrief } from "@/lib/useRequests";

import { Character } from "./sprites";

export type Tab = "screen" | "seat" | "slice" | "talk" | "mail";
// What the Screen tab shows: follow the action, a desk's computer, a GPU workstation, or one beat.
export type ScreenTarget = "follow" | `desk:${string}` | `gpu${number}` | `beat:${number}`;

const KIND: Record<Beat["kind"], [string, string]> = {
  think: ["Think", "#65D39A"],
  queue: ["Queue", "#7FB2FF"],
  talk: ["Talk", "#FFD05A"],
  compute: ["Compute", "#63D6CC"],
  lock: ["Lock", "#B4A7FF"],
  refuse: ["Refused", "#FF8585"],
};

function Label({ children, color = "#FFD05A" }: { children: React.ReactNode; color?: string }) {
  return (
    <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color }}>
      {children}
    </div>
  );
}

function Mono({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed text-[#D6DCEA] ${className}`}>{children}</div>;
}

// ---------------------------------------------------------------------------- Screen

function pickBeat(replay: Replay, index: number, target: ScreenTarget): number {
  if (target === "follow") return index;
  if (target.startsWith("beat:")) return Number(target.slice(5));
  for (let k = index; k >= 0; k--) {
    const b = replay.beats[k];
    if (target.startsWith("gpu") ? b.kind === "compute" && b.place === target : b.kind === "think" && `desk:${b.actor}` === target) return k;
  }
  return -1;
}

function ScreenTab({ replay, scene, t, target, onFollow }: { replay: Replay; scene: Scene; t: number; target: ScreenTarget; onFollow: () => void }) {
  const k = pickBeat(replay, scene.index, target);
  const b = k >= 0 ? replay.beats[k] : null;
  const f = b ? (k < scene.index ? 1 : Math.max(0, Math.min(1, (t - b.at) / b.dur))) : 0;
  const header = (
    <div className="flex items-start justify-between gap-3">
      <div className="flex flex-col gap-1">
        <span className="text-[17px] font-semibold text-[#E8EDF7]">
          {b ? (b.kind === "compute" ? `${b.place?.toUpperCase()} · ${b.actor}` : b.kind === "think" ? `${b.actor}'s computer` : b.actor) : "Nothing on this screen yet"}
        </span>
        {b ? (
          <span className="text-[12px] text-[#AAB4CA]">
            {mmss(b.at)} · {b.text}
          </span>
        ) : null}
      </div>
      {target !== "follow" ? (
        <button type="button" onClick={onFollow} className="h-9 shrink-0 rounded-md border border-[#263255] px-2 text-[12px] text-[#AAB4CA] hover:text-[#E8EDF7]">
          Follow the action
        </button>
      ) : null}
    </div>
  );
  if (!b) return header;
  if (b.kind === "think") {
    const c = replay.calls[String(b.call)];
    const inFlight = !!c?.in_flight;
    const r = c?.reasoning || "";
    // Replay reveals the recorded reasoning over the beat; a running call shows the latest the stream reported.
    const shown = inFlight ? r : r.slice(0, Math.floor(r.length * Math.min(1, f / 0.8)));
    return (
      <div className="flex flex-col gap-3">
        {header}
        {c ? (
          <div className="flex flex-col gap-2 rounded-md border-2 border-[#263255] bg-[#060A18] p-3">
            <span className="font-mono text-[11px] text-[#AAB4CA]">
              call #{b.call} · {c.tier} · {inFlight ? `thinking… ${c.reasoning_chars ?? 0} chars so far` : `${Math.round(c.s ?? 0)} s`}
              {c.error ? ` · ${c.error}` : ""}
            </span>
            <Label>Prompt</Label>
            <Mono>{c.prompt}</Mono>
            <Label color="#B4A7FF">Reasoning</Label>
            <Mono className="text-[#D3CBFF]">
              {r ? shown : "(the model returned no separate reasoning)"}
              {(inFlight || f < 0.85) && r ? <span className="blink text-[#B4A7FF]">█</span> : null}
            </Mono>
            {!inFlight && f >= 0.85 ? (
              <>
                <Label color="#63D6CC">Reply</Label>
                <Mono>{c.reply}</Mono>
              </>
            ) : null}
          </div>
        ) : (
          <p className="text-[13px] text-[#AAB4CA]">{inFlight ? "The call is still running; its prompt and reply arrive when it ends." : "No record of this call."}</p>
        )}
      </div>
    );
  }
  const s = replay.slices.find((x) => x.id === b.slice);
  if (b.kind === "compute" && b.task === "run_experiment" && s?.run && s.locked) {
    const months = s.locked.months;
    const n = Math.max(0, Math.ceil(f * months.length));
    return (
      <div className="flex flex-col gap-3">
        {header}
        <div className="flex flex-col gap-2 rounded-md border-2 border-[#1F4A45] bg-[#060A18] p-3">
          <span className="font-mono text-[12px] text-[#9EE8DC]">
            frozen judge {s.run.judge.slice(0, 12)} · prereg {s.locked.digest.slice(0, 12)} · design {s.run.design} · {s.run.data} months ·{" "}
            {s.run.stations.toLocaleString()} stations
          </span>
          <div className="h-2.5 rounded-full bg-[#151D3A]">
            <div className="h-2.5 rounded-full bg-[#63D6CC]" style={{ width: `${Math.round(f * 100)}%` }} />
          </div>
          <div className="flex justify-between text-[11px] text-[#AAB4CA]">
            <span>month</span>
            <span>WAPE change: champion better ← | → treatment better</span>
          </div>
          {months.slice(0, n).map((m, j) => {
            const v = s.run!.rel[j] ?? 0;
            const w = Math.min(50, (Math.abs(v) / 0.3) * 50);
            return (
              <div key={m} className="flex items-center gap-2">
                <span className="w-16 font-mono text-[12px] text-[#C9D1E4]">
                  {m.slice(0, 4)}-{m.slice(4)}
                </span>
                <div className="relative h-3.5 flex-1 bg-[#10162B]">
                  <div className="absolute left-1/2 top-0 h-3.5 w-px bg-[#53648E]" />
                  <div className="absolute top-0.5 h-2.5" style={{ left: `${v >= 0 ? 50 : 50 - w}%`, width: `${w}%`, background: v >= 0 ? "#63D6CC" : "#FF8585" }} />
                </div>
                <span className="w-16 text-right font-mono text-[12px] text-[#E8EDF7]">{pct(v)}</span>
              </div>
            );
          })}
          {f >= 1 && s.decision ? (
            <div className="flex justify-between border-t border-[#263255] pt-2 text-[13px]">
              <span className="text-[#C9D1E4]">Pooled over stations × months</span>
              <span className="font-mono text-[#FFD05A]">
                {pct(s.decision.point)} [{pct(s.decision.lo)}, {pct(s.decision.hi)}]
              </span>
            </div>
          ) : null}
        </div>
        <p className="text-[12px] text-[#AAB4CA]">
          The months appear over the beat; the numbers are the run&apos;s final per-month results. Live per-month progress needs the judge to report each
          month as it finishes.
        </p>
      </div>
    );
  }
  if (b.kind === "compute" && s) {
    const p = s.pilot as Record<string, number | string | boolean> | null;
    const lines =
      b.task === "power_controls" && p
        ? [
            `pilot months, design ${p.design}: effect ${pct(p.pilot_effect as number)}, SE ${pct(p.pilot_se as number).replace("+", "")}`,
            `P(decisive) at the pilot effect = ${(p.p_decisive as number).toFixed(2)} (needs ≥ 0.80)`,
            `positive control: ${p.positive_control}`,
            `placebo: ${p.negative_control}`,
            `leak canary: ${p.leak_canary ? "FIRED" : "clean"}`,
            `admissible: ${p.admissible}${p.censor_mask_available === false ? " · censor mask missing" : ""}`,
          ]
        : s.decision
          ? [
              "two-way bootstrap: stations and months resampled together",
              `α reserved at lock = ${s.decision.alpha}`,
              `estimate ${pct(s.decision.point)}, CI [${pct(s.decision.lo)}, ${pct(s.decision.hi)}]`,
              `kernel.decide(SESOI ${pct(s.decision.sesoi, 0)}) → ${s.decision.decision}`,
            ]
          : [b.text];
    return (
      <div className="flex flex-col gap-3">
        {header}
        <ol className="flex flex-col gap-2 rounded-md border-2 border-[#1F4A45] bg-[#060A18] p-3 font-mono text-[12.5px] text-[#D6DCEA]">
          {lines.slice(0, Math.max(1, Math.ceil(f * lines.length))).map((l) => (
            <li key={l}>
              <span className="text-[#63D6CC]">$</span> {l}
            </li>
          ))}
        </ol>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {header}
      <p className={`rounded-md p-3 text-[13px] leading-relaxed ${b.kind === "refuse" ? "bg-[#2A141A] text-[#FFD0D0]" : "bg-[#10162B] text-[#D6DCEA]"}`}>{b.text}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------- Seat

function SeatTab({
  replay,
  scene,
  t,
  seat,
  onBeat,
}: {
  replay: Replay;
  scene: Scene;
  t: number;
  seat: string;
  onBeat: (k: number) => void;
}) {
  const [sub, setSub] = useState<"history" | "calls" | "queues" | "refusals">("history");
  const [open, setOpen] = useState<number | null>(null);
  const info = replay.seats[seat];
  const idx = beatIndexAt(replay.beats, t);
  const mine = replay.beats
    .map((b, k) => [b, k] as const)
    .filter(([b, k]) => k <= idx && (b.actor === seat || b.target === seat));
  const filtered = mine.filter(([b]) =>
    sub === "calls" ? b.kind === "think" && b.actor === seat : sub === "queues" ? b.kind === "queue" : sub === "refusals" ? b.kind === "refuse" : true,
  );
  const cur = scene.beat?.actor === seat ? scene.beat : null;
  const openBeat = open !== null ? replay.beats[open] : null;
  const call = openBeat?.kind === "think" ? replay.calls[String(openBeat.call)] : null;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <div className="rounded-md border border-[#263255] bg-[#10162B] p-1">
          <Character look={LOOKS[seat]} action="idle" moving={false} />
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <span className="text-[19px] font-semibold text-[#E8EDF7]">{seat}</span>
          <span className="text-[12px] text-[#AAB4CA]">{info?.kind === "code" ? "code seat · no LLM" : `LLM seat · ${info?.tier ?? ""} tier`}</span>
        </div>
        <span className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] ${cur ? "border-[#65D39A] text-[#65D39A]" : "border-[#263255] text-[#AAB4CA]"}`}>
          <span className={`h-2 w-2 rounded-full ${cur ? "bg-[#65D39A]" : "bg-[#53648E]"}`} />
          {cur ? "Active" : "Idle"}
        </span>
      </div>
      <p className="text-[13px] leading-relaxed text-[#C9D1E4]">Owns: {info?.owns}</p>
      <div className="rounded-md border border-[#263255] bg-[#10162B] p-3">
        <div className="text-[12px] text-[#AAB4CA]">Current task</div>
        <div className="mt-1 text-[15px] font-semibold text-[#E8EDF7]">{cur ? cur.text : "Waiting for work"}</div>
        <div className="mt-2 h-1.5 rounded-full bg-[#151D3A]">
          <div className="h-1.5 rounded-full bg-[#7FB2FF]" style={{ width: `${cur ? Math.round(scene.frac * 100) : 0}%` }} />
        </div>
      </div>
      <div role="tablist" className="flex gap-4 border-b border-[#263255]">
        {(
          [
            ["history", "History"],
            ["calls", "LLM Calls"],
            ["queues", "Queues"],
            ["refusals", "Refusals"],
          ] as const
        ).map(([k, l]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={sub === k}
            onClick={() => setSub(k)}
            className={`h-10 border-b-2 text-[13px] font-semibold ${sub === k ? "border-[#FFD05A] text-[#E8EDF7]" : "border-transparent text-[#AAB4CA]"}`}
          >
            {l}
          </button>
        ))}
      </div>
      <ol className="flex flex-col">
        {filtered.length === 0 ? <li className="py-3 text-[13px] text-[#AAB4CA]">Nothing yet.</li> : null}
        {[...filtered].reverse().map(([b, k]) => {
          const [label, color] = KIND[b.kind];
          const incoming = b.target === seat && b.actor !== seat;
          return (
            <li key={k}>
              <button
                type="button"
                onClick={() => setOpen(open === k ? null : k)}
                className={`grid w-full grid-cols-[52px_78px_1fr] items-start gap-2 border-b border-[#1B2444] py-2 text-left text-[12.5px] ${open === k ? "bg-[#151D3A]" : "hover:bg-[#10162B]"}`}
              >
                <span className="font-mono text-[#AAB4CA]">{mmss(b.at)}</span>
                <span className="flex items-center gap-1.5 font-semibold" style={{ color }}>
                  <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                  {label}
                </span>
                <span className="text-[#D6DCEA]">
                  {incoming ? <span className="text-[#AAB4CA]">from {b.actor}: </span> : b.target ? <span className="text-[#AAB4CA]">→ {b.target}: </span> : null}
                  {b.text}
                  {b.kind === "think" ? <span className="ml-1 font-mono text-[11px] text-[#AAB4CA]">(call {b.call})</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {openBeat ? (
        <div className="flex flex-col gap-2 rounded-md border border-[#263255] bg-[#0B1122] p-3">
          <div className="flex items-center justify-between">
            <span className="text-[14px] font-semibold text-[#E8EDF7]">{call ? `LLM call #${openBeat.call}` : KIND[openBeat.kind][0]}</span>
            <button type="button" onClick={() => onBeat(open!)} className="h-8 rounded-md border border-[#263255] px-2 text-[12px] text-[#AAB4CA] hover:text-[#E8EDF7]">
              Watch on screen
            </button>
          </div>
          {call ? (
            <>
              <Label>Prompt</Label>
              <Mono>{call.prompt}</Mono>
              <Label color="#B4A7FF">Reasoning</Label>
              <Mono className="text-[#D3CBFF]">{call.reasoning || "(none returned)"}</Mono>
              <Label color="#63D6CC">Reply</Label>
              <Mono>{call.reply}</Mono>
            </>
          ) : (
            <Mono>{openBeat.text}</Mono>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------- Slice

function SliceTab({ replay, t, id, onRun }: { replay: Replay; t: number; id: string | null; onRun: (k: number) => void }) {
  const s = replay.slices.find((x) => x.id === id) ?? replay.slices[0];
  if (!s) return <p className="text-[13px] text-[#AAB4CA]">No slices in this run yet.</p>;
  const stage = stageAt(s, t);
  const dec = decisionVisible(s, t) ? s.decision : null;
  const runBeat = replay.beats.findIndex((b) => b.kind === "compute" && b.task === "run_experiment" && b.slice === s.id);
  const lo = -0.3,
    hi = 0.3;
  const x = (v: number) => `${((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="flex flex-col gap-3">
      <span className="font-mono text-[12px] text-[#AAB4CA]">{s.id}</span>
      <span className="text-[18px] font-semibold text-[#E8EDF7]">{s.title}</span>
      <span className={`self-start rounded-sm border px-2 py-0.5 text-[12px] ${stage === "parked" ? "border-[#FF8585] text-[#FF8585]" : "border-[#FFD05A] text-[#FFD05A]"}`}>
        {(stage ?? "not started").replace(/_/g, " ")}
      </span>
      {dec ? (
        <div className="flex flex-col gap-2 rounded-md border border-[#263255] bg-[#10162B] p-3">
          <div className="flex items-baseline justify-between">
            <span className="text-[13px] text-[#C9D1E4]">Kernel decision</span>
            <span className="text-[16px] font-semibold capitalize text-[#FFD05A]">{dec.decision.replace("_", " ")}</span>
          </div>
          <div className="relative h-10" aria-label={`CI from ${pct(dec.lo)} to ${pct(dec.hi)}, SESOI ${pct(dec.sesoi, 0)}`}>
            <div className="absolute left-0 right-0 top-5 h-0.5 bg-[#263255]" />
            <div className="absolute top-2 h-7 w-0.5 bg-[#AAB4CA]" style={{ left: x(0) }} />
            <div className="absolute top-1 h-9 w-0.5 bg-[#FF8585]" style={{ left: x(dec.sesoi) }} />
            <div className="absolute top-3.5 h-3 rounded-full bg-[#63D6CC]" style={{ left: x(dec.lo), width: `calc(${x(dec.hi)} - ${x(dec.lo)})` }} />
            <div className="absolute top-2.5 -ml-2 h-5 w-5 rounded-full border-2 border-[#10162B] bg-[#FFD05A]" style={{ left: x(dec.point) }} />
          </div>
          <div className="flex justify-between font-mono text-[12px] text-[#AAB4CA]">
            <span>
              {pct(dec.point, 2)} [{pct(dec.lo, 2)}, {pct(dec.hi, 2)}]
            </span>
            <span>
              SESOI {pct(dec.sesoi, 0)} · α {dec.alpha}
            </span>
          </div>
          {runBeat >= 0 ? (
            <button type="button" onClick={() => onRun(runBeat)} className="self-start rounded-md border border-[#1F4A45] px-2 py-1 text-[12px] text-[#9EE8DC]">
              Watch its experiment run
            </button>
          ) : null}
        </div>
      ) : null}
      {s.locked && stage && ["locked", "run", "analysed", "replicated", "not_replicated", "written"].includes(stage) ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex justify-between">
            <Label>Locked prereg</Label>
            <span className="font-mono text-[11px] text-[#AAB4CA]">sha256 {s.locked.digest.slice(0, 12)}</span>
          </div>
          <p className="text-[13px] leading-relaxed text-[#D6DCEA]">{s.locked.statement}</p>
        </div>
      ) : null}
      <Label>Guarded moves</Label>
      <ol className="flex flex-col gap-1.5">
        {s.events
          .filter((e) => e.at <= t)
          .map((e, k) => (
            <li
              key={k}
              className={`flex flex-col gap-0.5 rounded-md border px-3 py-2 ${e.ok ? "border-[#263255] bg-[#10162B]" : "border-[#6B2A33] bg-[#2A141A]"}`}
            >
              <span className="font-mono text-[12px] text-[#E8EDF7]">
                {mmss(e.at)} · {e.seat}: {e.frm} → {e.to}
              </span>
              {e.note || !e.ok ? <span className={`text-[12px] ${e.ok ? "text-[#AAB4CA]" : "text-[#FFD0D0]"}`}>{e.ok ? e.note : `REFUSED · ${e.note}`}</span> : null}
            </li>
          ))}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------------------- Conversations

function TalkTab({ replay, t, current }: { replay: Replay; t: number; current: number | undefined }) {
  const said = replay.msgs.filter((m) => m.at <= t);
  const bySlice = new Map<string, typeof said>();
  for (const m of said) bySlice.set(m.slice || "(no slice)", [...(bySlice.get(m.slice || "(no slice)") ?? []), m]);
  if (!said.length) return <p className="text-[13px] text-[#AAB4CA]">No conversations yet. Seats talk with `send`, which never changes state.</p>;
  return (
    <div className="flex flex-col gap-4">
      {[...bySlice.entries()].reverse().map(([slice, ms]) => (
        <section key={slice} className="flex flex-col gap-2">
          <span className="font-mono text-[12px] text-[#AAB4CA]">{slice}</span>
          {ms.map((m) => (
            <div key={m.id} className={`flex flex-col gap-1 rounded-md border-2 p-3 ${current === m.id ? "border-[#FFD05A] bg-[#FFF3B8]" : "border-[#10162B] bg-[#F4F6FA]"}`}>
              <span className="text-[12px] text-[#40496A]">
                <span className="font-semibold text-[#10162B]">{m.frm}</span> → {m.to} · {mmss(m.at)}
              </span>
              <span className="text-[13px] leading-relaxed text-[#10162B]">{m.body}</span>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------- Mailbox

function when(ts: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
}

function RequestCard({ r, onReply }: { r: OwnerRequest; onReply: (id: string, text: string) => Promise<void> }) {
  const [copied, setCopied] = useState(false);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const open = r.status === "open";
  const copy = () =>
    navigator.clipboard.writeText(requestBrief(r)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  const send = () => {
    setBusy(true);
    setErr(null);
    onReply(r.id, text)
      .then(() => setText(""))
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <div className={`flex flex-col gap-2 rounded-md border-2 p-3 ${open ? "border-[#FFD05A] bg-[#FFF3B8]" : "border-[#10162B] bg-[#F4F6FA] opacity-80"}`}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-[14px] font-semibold leading-snug text-[#10162B]">{r.what}</span>
        <button type="button" onClick={copy} className="h-8 shrink-0 rounded-md border-2 border-[#10162B] bg-white px-2 text-[12px] font-semibold text-[#10162B] hover:bg-[#E8EDF7]">
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {(
        [
          ["Why", r.why],
          ["How", r.how],
          ["Done when", r.done],
        ] as const
      )
        .filter(([, v]) => v)
        .map(([k, v]) => (
          <p key={k} className="text-[13px] leading-relaxed text-[#263255]">
            <span className="font-semibold text-[#10162B]">{k}: </span>
            {v}
          </p>
        ))}
      <span className="text-[11px] text-[#53648E]">
        {open ? "Open" : "Answered"} · asked {r.asks}× · last {when(r.asked)}
      </span>
      {open ? (
        <div className="flex flex-col gap-1.5">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={2}
            placeholder="Answer the PI (closes the request; it reads this in its next plan)"
            className="w-full resize-y rounded-md border-2 border-[#10162B] bg-white p-2 text-[13px] text-[#10162B]"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy || !text.trim()}
              onClick={send}
              className="h-8 rounded-md bg-[#10162B] px-3 text-[12px] font-semibold text-[#FFD05A] disabled:opacity-40"
            >
              Answer
            </button>
            {err ? <span className="text-[12px] text-[#B42318]">{err}</span> : null}
          </div>
        </div>
      ) : (
        <p className="text-[13px] leading-relaxed text-[#10162B]">
          <span className="font-semibold">Your answer ({when(r.answered)}): </span>
          {r.reply}
        </p>
      )}
    </div>
  );
}

function MailTab({ requests, onReply }: { requests: OwnerRequest[]; onReply: (id: string, text: string) => Promise<void> }) {
  const open = requests.filter((r) => r.status === "open");
  const done = requests.filter((r) => r.status !== "open");
  if (!requests.length) return <p className="text-[13px] text-[#AAB4CA]">The PI has not asked you for anything. It asks only for what the lab cannot get or decide itself.</p>;
  return (
    <div className="flex flex-col gap-4">
      <Label>{open.length ? `Open (${open.length})` : "Nothing open"}</Label>
      {open.map((r) => (
        <RequestCard key={r.id} r={r} onReply={onReply} />
      ))}
      {done.length ? <Label color="#AAB4CA">Answered ({done.length})</Label> : null}
      {done.map((r) => (
        <RequestCard key={r.id} r={r} onReply={onReply} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------- Inspector

export function Inspector(props: {
  replay: Replay;
  scene: Scene;
  t: number;
  tab: Tab;
  onTab: (t: Tab) => void;
  seat: string;
  slice: string | null;
  screen: ScreenTarget;
  onScreen: (s: ScreenTarget) => void;
  requests: OwnerRequest[];
  onReply: (id: string, text: string) => Promise<void>;
}) {
  const { replay, scene, t, tab, onTab, seat, slice, screen, onScreen, requests, onReply } = props;
  const openBeat = (k: number) => {
    onScreen(`beat:${k}`);
    onTab("screen");
  };
  return (
    <aside className="flex min-h-0 w-[460px] shrink-0 flex-col border-l-2 border-[#1B2444] bg-[#0B1122]">
      <div role="tablist" className="flex gap-5 border-b-2 border-[#1B2444] px-5">
        {(
          [
            ["screen", "Screen"],
            ["seat", "Seat"],
            ["slice", "Slice"],
            ["talk", "Talk"],
            ["mail", "Mailbox"],
          ] as const
        ).map(([k, l]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => onTab(k)}
            className={`h-12 border-b-[3px] text-[15px] font-semibold ${tab === k ? "border-[#FFD05A] text-[#E8EDF7]" : "border-transparent text-[#AAB4CA] hover:text-[#E8EDF7]"}`}
          >
            {l}
            {k === "mail" && scene.mail ? <span className="ml-1.5 rounded-full bg-[#FF8585] px-1.5 text-[11px] text-[#10162B]">{scene.mail}</span> : null}
          </button>
        ))}
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto p-5">
        {tab === "screen" ? <ScreenTab replay={replay} scene={scene} t={t} target={screen} onFollow={() => onScreen("follow")} /> : null}
        {tab === "seat" ? <SeatTab replay={replay} scene={scene} t={t} seat={seat} onBeat={openBeat} /> : null}
        {tab === "slice" ? <SliceTab replay={replay} t={t} id={slice} onRun={openBeat} /> : null}
        {tab === "mail" ? <MailTab requests={requests} onReply={onReply} /> : null}
        {tab === "talk" ? <TalkTab replay={replay} t={t} current={scene.beat?.kind === "talk" ? scene.beat.msg : undefined} /> : null}
      </div>
    </aside>
  );
}
