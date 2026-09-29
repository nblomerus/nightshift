"use client";

import { useEffect, useRef } from "react";

const KEYS: [string, string][] = [
  ["Space", "Play / pause"],
  ["← / →", "Previous / next beat"],
  ["1 – 4", "Speed 1× / 2× / 4× / 8×"],
  ["⌘K", "This help"],
  ["Esc", "Close"],
];

const LEGEND: [string, string, string][] = [
  ["#65D39A", "Think", "an LLM call: the seat types at its own computer"],
  ["#63D6CC", "Compute", "code runs the frozen judge at a GPU workstation"],
  ["#FFD05A", "Talk", "a message (send): never changes state"],
  ["#7FB2FF", "Queue", "a task handed to another seat"],
  ["#B4A7FF", "Lock", "the statistician locks a prereg at the vault"],
  ["#FF8585", "Refused", "the rig blocked a move; logged, never silent"],
];

export function QuickHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-[560px] rounded-lg border-2 border-[#53648E] bg-[#0B1122] p-6 text-[#E8EDF7] backdrop:bg-black/60"
    >
      <div className="flex items-center justify-between">
        <h2 className="font-pixel text-[13px]">QUICK HELP</h2>
        <button type="button" onClick={onClose} className="h-9 rounded-md border border-[#263255] px-3 text-[13px] text-[#AAB4CA]">
          Close
        </button>
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-[#C9D1E4]">
        Click a character for its history and every prompt, reasoning and reply. Click a computer to watch its screen, a GPU workstation to watch an
        experiment, a slice card for its pipeline and decision.
      </p>
      <dl className="mt-4 grid grid-cols-[90px_1fr] gap-x-4 gap-y-2 text-[13px]">
        {KEYS.map(([k, v]) => (
          <div key={k} className="contents">
            <dt>
              <kbd className="rounded border border-[#53648E] px-1.5 font-mono text-[12px]">{k}</kbd>
            </dt>
            <dd className="text-[#C9D1E4]">{v}</dd>
          </div>
        ))}
      </dl>
      <ul className="mt-5 flex flex-col gap-2 text-[13px]">
        {LEGEND.map(([c, k, v]) => (
          <li key={k} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            <span className="w-16 font-semibold">{k}</span>
            <span className="text-[#C9D1E4]">{v}</span>
          </li>
        ))}
      </ul>
    </dialog>
  );
}
