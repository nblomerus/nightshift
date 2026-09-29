"use client";

import { campaignOf, decisionVisible, PIPELINE, pct, pipelineReached, stageAt } from "@/lib/scene";
import type { Replay, Slice } from "@/lib/types";

function Node({ state, label, lock }: { state: "done" | "current" | "future" | "parked"; label: string; lock: boolean }) {
  const ring =
    state === "current"
      ? "h-5 w-5 border-[3px] border-[#7FB2FF] bg-[#0B1122] shadow-[0_0_0_3px_rgba(127,178,255,0.25)]"
      : state === "done"
        ? lock
          ? "h-5 w-5 bg-[#B4A7FF]"
          : "h-3.5 w-3.5 bg-[#FFD05A]"
        : state === "parked"
          ? "h-3.5 w-3.5 bg-[#FF8585]"
          : "h-3 w-3 border-2 border-[#53648E] bg-transparent";
  return (
    <div className="flex w-[54px] flex-col items-center gap-1">
      <div className="flex h-6 items-center">
        <span className={`inline-block rounded-full ${ring}`} />
      </div>
      <span className={`text-[11px] ${state === "future" ? "text-[#6B7697]" : "text-[#AAB4CA]"}`}>{label}</span>
    </div>
  );
}

function Row({ slice, t, selected, onSlice }: { slice: Slice; t: number; selected: boolean; onSlice: (id: string) => void }) {
  const stage = stageAt(slice, t) ?? "";
  const { reached, current, parked } = pipelineReached(slice, t);
  const dec = decisionVisible(slice, t) ? slice.decision : null;
  const months = slice.locked?.months.length;
  const stations = slice.run?.stations;
  return (
    <button
      type="button"
      onClick={() => onSlice(slice.id)}
      className={`grid w-full grid-cols-[250px_minmax(0,1fr)_170px] items-center gap-3 border-t border-[#1B2444] px-4 py-2.5 text-left ${selected ? "bg-[#151D3A]" : "hover:bg-[#10162B]"}`}
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${parked ? "bg-[#FF8585]" : "bg-[#FFD05A]"}`} />
          <span className="truncate whitespace-nowrap font-mono text-[14px] font-semibold text-[#E8EDF7]">{slice.id}</span>
        </div>
        <span
          className={`self-start rounded-sm border px-1.5 text-[10px] uppercase tracking-wide ${parked ? "border-[#FF8585] text-[#FF8585]" : "border-[#FFD05A] text-[#FFD05A]"}`}
        >
          {stage.replace(/_/g, " ")}
        </span>
        <span className="truncate text-[12px] text-[#AAB4CA]">
          {slice.title}
          {stations ? ` · ${stations.toLocaleString()} stations` : ""}
          {months ? ` · ${months} months` : ""}
        </span>
      </div>
      <div className="flex items-start">
        {PIPELINE.map((p, k) => {
          const state = parked && k === current ? "parked" : k === current && !dec ? "current" : k <= reached ? "done" : "future";
          return (
            <div key={p.key} className="flex items-start">
              {k > 0 ? <span className={`mt-3 h-0.5 w-2 ${k <= reached ? "bg-[#FFD05A]" : "bg-[#263255]"}`} /> : null}
              <Node state={state} label={p.label} lock={p.key === "locked"} />
            </div>
          );
        })}
      </div>
      <div className="rounded-md border border-[#263255] bg-[#10162B] px-3 py-2">
        {dec ? (
          <div className="flex flex-col">
            <span className="text-[13px] font-semibold capitalize text-[#E8EDF7]">{dec.decision.replace("_", " ")}</span>
            <span className="font-mono text-[12px] text-[#FFD05A]">{pct(dec.point)}</span>
            <span className="font-mono text-[11px] text-[#AAB4CA]">
              CI {pct(dec.lo)} to {pct(dec.hi)}
            </span>
          </div>
        ) : (
          <div className="flex flex-col">
            <span className="text-[13px] font-semibold text-[#E8EDF7]">{parked ? "Parked" : "Pending"}</span>
            <span className="text-[11px] text-[#AAB4CA]">{parked ? "see guarded moves" : "–"}</span>
          </div>
        )}
      </div>
    </button>
  );
}

export function SliceStrip({
  replay,
  t,
  campaign,
  allCampaigns,
  onToggleAll,
  selected,
  onSlice,
}: {
  replay: Replay;
  t: number;
  campaign: number;
  allCampaigns: boolean;
  onToggleAll: () => void;
  selected: string | null;
  onSlice: (id: string) => void;
}) {
  const visible = replay.slices.filter((s) => stageAt(s, t) !== null && (allCampaigns || campaignOf(s.id) === campaign));
  const active = visible.filter((s) => !["written", "parked"].includes(stageAt(s, t) ?? "")).length;
  return (
    <section aria-label="Research slices" className="flex max-h-[236px] min-h-0 flex-col rounded-md border border-[#1B2444] bg-[#0B1122]">
      <div className="flex items-center gap-3 px-4 py-2">
        <span className="font-pixel text-[11px] text-[#63D6CC]">RESEARCH SLICES</span>
        <span className="text-[12px] text-[#AAB4CA]">
          {active} active / {visible.length} shown
        </span>
        <div className="flex-1" />
        <button type="button" onClick={onToggleAll} className="h-8 rounded-sm border border-[#263255] px-2 text-[12px] text-[#AAB4CA] hover:text-[#E8EDF7]">
          {allCampaigns ? `Only campaign ${campaign}` : "All campaigns"}
        </button>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto">
        {visible.length ? (
          visible.map((s) => <Row key={s.id} slice={s} t={t} selected={selected === s.id} onSlice={onSlice} />)
        ) : (
          <p className="px-4 py-3 text-[13px] text-[#AAB4CA]">No slices yet: the PI is planning.</p>
        )}
      </div>
    </section>
  );
}
