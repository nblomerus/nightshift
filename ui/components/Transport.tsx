"use client";

import { mmss } from "@/lib/scene";
import { type Player, SPEEDS } from "@/lib/useReplay";

const BTN = "flex h-12 w-12 items-center justify-center rounded-md border border-[#263255] bg-[#10162B] text-[#E8EDF7] hover:border-[#53648E]";

export function Transport({ player, total, live, caption }: { player: Player; total: number; live: boolean; caption: React.ReactNode }) {
  return (
    <section aria-label="Replay controls" className="flex flex-col gap-2 rounded-md border border-[#1B2444] bg-[#0B1122] px-4 py-3">
      <div className="flex items-center gap-2">
        <button type="button" className={BTN} onClick={player.restart} aria-label="Back to the start">
          ⏮
        </button>
        <button type="button" className={BTN} onClick={player.prev} aria-label="Previous beat">
          ◀◀
        </button>
        <button
          type="button"
          onClick={player.toggle}
          aria-label={player.playing ? "Pause" : "Play"}
          className="flex h-14 w-16 items-center justify-center rounded-md border-2 border-[#10162B] bg-[#FFD05A] text-[20px] text-[#10162B]"
        >
          {player.playing ? "❚❚" : "▶"}
        </button>
        <button type="button" className={BTN} onClick={player.next} aria-label="Next beat">
          ▶▶
        </button>
        <div className="mx-2 flex gap-1.5" role="radiogroup" aria-label="Speed">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={player.speed === s}
              onClick={() => player.setSpeed(s)}
              className={`h-11 w-12 rounded-md text-[14px] font-semibold ${player.speed === s ? "bg-[#FFD05A] text-[#10162B]" : "border border-[#263255] bg-[#10162B] text-[#AAB4CA]"}`}
            >
              {s}x
            </button>
          ))}
        </div>
        <label htmlFor="scrub" className="sr-only">
          Time
        </label>
        <input
          id="scrub"
          type="range"
          min={0}
          max={total || 1}
          step={0.5}
          value={player.t}
          onChange={(e) => player.setT(Number(e.target.value))}
          className="mx-2 flex-1 accent-[#FFD05A]"
        />
        <span className="w-28 text-right font-mono text-[14px] text-[#AAB4CA]">
          {mmss(player.t)} / {mmss(total)}
        </span>
        {live ? (
          <button
            type="button"
            onClick={player.goLive}
            className={`h-11 rounded-md px-3 text-[13px] font-semibold ${player.follow ? "bg-[#1B3A2E] text-[#65D39A]" : "border border-[#263255] text-[#AAB4CA]"}`}
          >
            {player.follow ? "● Live" : "Go live"}
          </button>
        ) : null}
      </div>
      <div className="truncate text-[13px] text-[#C9D1E4]">{caption}</div>
    </section>
  );
}
