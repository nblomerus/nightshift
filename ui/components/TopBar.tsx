"use client";

import type { Mode } from "@/lib/useRun";
import type { RunInfo } from "@/lib/types";

function Moon() {
  return (
    <svg width={36} height={36} viewBox="0 0 12 12" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={4} y={1} width={4} height={1} fill="#B4A7FF" />
      <rect x={2} y={2} width={3} height={1} fill="#B4A7FF" />
      <rect x={1} y={3} width={3} height={5} fill="#B4A7FF" />
      <rect x={2} y={8} width={3} height={1} fill="#B4A7FF" />
      <rect x={3} y={9} width={6} height={1} fill="#B4A7FF" />
      <rect x={8} y={8} width={2} height={1} fill="#B4A7FF" />
      <rect x={9} y={3} width={1} height={1} fill="#FFD05A" />
    </svg>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-[112px] flex-col gap-1 rounded-md border border-[#263255] bg-[#10162B] px-3 py-1.5">
      <span className="text-[11px] uppercase tracking-wider text-[#AAB4CA]">{label}</span>
      <span className="text-[15px] font-semibold text-[#E8EDF7]">{children}</span>
    </div>
  );
}

export function TopBar(props: {
  campaign: number;
  campaigns: number;
  activeSlice: string;
  beat: number;
  beats: number;
  runs: RunInfo[];
  run: string | null;
  onRun: (name: string) => void;
  mode: Mode;
  onMode: (m: Mode) => void;
  connected: boolean;
  onHelp: () => void;
}) {
  const { campaign, campaigns, activeSlice, beat, beats, runs, run, onRun, mode, onMode, connected, onHelp } = props;
  return (
    <header className="flex h-16 shrink-0 items-center gap-4 border-b-2 border-[#1B2444] bg-[#0B1122] px-5">
      <Moon />
      <div className="flex flex-col">
        <span className="font-pixel text-[16px] tracking-wide text-[#E8EDF7]">NIGHTSHIFT</span>
        <span className="text-[12px] text-[#AAB4CA]">Autonomous ML Research Lab</span>
      </div>
      <div className="flex-1" />
      <Stat label="Campaign">
        {campaign} <span className="text-[#AAB4CA]">/ {campaigns}</span>
      </Stat>
      <Stat label="Active slice">
        <span className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-[#65D39A]" />
          <span className="font-mono text-[13px]">{activeSlice || "–"}</span>
        </span>
      </Stat>
      <Stat label="Beat">
        {beat} <span className="text-[#AAB4CA]">/ {beats}</span>
      </Stat>
      <label className="flex flex-col gap-1 rounded-md border border-[#263255] bg-[#10162B] px-3 py-1.5">
        <span className="text-[11px] uppercase tracking-wider text-[#AAB4CA]">Run</span>
        <select
          value={run ?? ""}
          onChange={(e) => onRun(e.target.value)}
          className="bg-transparent text-[14px] font-semibold text-[#E8EDF7] outline-none"
        >
          {runs.map((r) => (
            <option key={r.name} value={r.name} className="bg-[#10162B]">
              {r.name} {r.rig ? `· ${r.rig}` : ""}
            </option>
          ))}
        </select>
      </label>
      <div role="radiogroup" aria-label="Mode" className="flex overflow-hidden rounded-md border border-[#263255]">
        {(["replay", "live"] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mode === m}
            onClick={() => onMode(m)}
            className={`flex h-11 items-center gap-2 px-3 text-[13px] font-semibold ${mode === m ? "bg-[#FFD05A] text-[#10162B]" : "bg-[#10162B] text-[#AAB4CA]"}`}
          >
            {m === "live" ? <span className={`h-2 w-2 rounded-full ${connected ? "blink bg-[#65D39A]" : "bg-[#AAB4CA]"}`} /> : null}
            {m === "replay" ? "Replay" : "Live"}
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={onHelp}
        className="flex h-11 items-center gap-2 rounded-md border border-[#263255] bg-[#10162B] px-3 text-[13px] text-[#AAB4CA]"
      >
        <kbd className="rounded border border-[#53648E] px-1 font-mono text-[11px]">⌘K</kbd> Help
      </button>
    </header>
  );
}
