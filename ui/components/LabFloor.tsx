"use client";

import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import {
  COFFEE,
  DESK_W,
  DESKS,
  LOOKS,
  MAILBOX,
  MEETING_TABLE,
  ROOMS,
  SCENE,
  seatSpot,
  VAULT,
  WHITEBOARD,
  WORKSTATION_W,
  WORKSTATIONS,
} from "@/lib/layout";
import { campaignOf, type Scene, stageAt, type Tone } from "@/lib/scene";
import type { Replay } from "@/lib/types";

import { Armchair, Cabinet, Character, Coffee, Desk, Mailbox, MeetingTable, Plant, Rack, Shelf, Sofa, VaultDoor, Workstation } from "./sprites";

const TONE: Record<Tone, string> = {
  think: "bg-[#F4F6FA] text-[#10162B] border-[#53648E]",
  talk: "bg-[#F4F6FA] text-[#10162B] border-[#FFD05A]",
  listen: "bg-[#F4F6FA] text-[#10162B] border-[#53648E]",
  queue: "bg-[#FFD05A] text-[#10162B] border-[#8A6A1A]",
  compute: "bg-[#0E2F2C] text-[#C9F5EF] border-[#63D6CC]",
  lock: "bg-[#241F45] text-[#E3DDFF] border-[#B4A7FF]",
  refuse: "bg-[#3A1820] text-[#FFD0D0] border-[#FF8585]",
};

export interface FloorProps {
  replay: Replay;
  scene: Scene;
  t: number;
  selectedSeat: string | null;
  onSeat: (seat: string) => void;
  onComputer: (key: string) => void;
  onSlice: (id: string) => void;
  onBubble: (seat: string) => void;
  onMailbox: () => void;
}

function useFit(ref: React.RefObject<HTMLDivElement | null>) {
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      setScale(Math.min(width / SCENE.w, height / SCENE.h));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return scale;
}

function RoomLabel({ label, status, tone }: { label: string; status: string; tone: string }) {
  return (
    <div className="absolute left-3 top-3 flex items-center gap-3">
      <span className="font-pixel text-[11px] tracking-wide text-[#E8EDF7]">{label}</span>
      <span className="flex items-center gap-1.5 font-pixel text-[9px]" style={{ color: tone }}>
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: tone }} />
        {status}
      </span>
    </div>
  );
}

export function LabFloor({ replay, scene, t, selectedSeat, onSeat, onComputer, onSlice, onBubble, onMailbox }: FloorProps) {
  const ref = useRef<HTMLDivElement>(null);
  const scale = useFit(ref);
  const [moving, setMoving] = useState<Record<string, boolean>>({});

  const b = scene.beat;
  const roomStatus = (id: string): [string, string] => {
    if (id === "vault") return ["LOCKED", "#B4A7FF"];
    if (id === "compute") return b?.kind === "compute" ? ["RUNNING", "#63D6CC"] : ["IDLE", "#AAB4CA"];
    const members = id === "pi" ? ["pi"] : ["methodologist", "critic", "writer"];
    return b && members.includes(b.actor) ? ["ACTIVE", "#65D39A"] : ["IDLE", "#AAB4CA"];
  };
  const campaignSlices = replay.slices.filter((s) => campaignOf(s.id) === scene.campaign && stageAt(s, t) !== null);

  return (
    <div ref={ref} className="relative h-full w-full overflow-hidden">
      <div
        className="absolute left-1/2 top-1/2 origin-center"
        style={{ width: SCENE.w, height: SCENE.h, transform: `translate(-50%, -50%) scale(${scale})` }}
      >
        <div className="floor-tiles absolute inset-0 border-4 border-[#53648E]" />
        <div className="absolute left-0 right-0 top-0 flex h-7 items-center gap-16 border-b-4 border-[#263255] bg-[#1B2444] px-16">
          {Array.from({ length: 10 }, (_, k) => (
            <div key={k} className="relative h-4 w-14 border-2 border-[#53648E] bg-[#060A18]">
              <span className="absolute left-3 top-1 h-0.5 w-0.5 bg-white" />
              <span className="absolute left-9 top-2 h-0.5 w-0.5 bg-white opacity-70" />
            </div>
          ))}
        </div>

        {ROOMS.map((r) => {
          const [status, tone] = roomStatus(r.id);
          return (
            <div
              key={r.id}
              className={`absolute border-4 ${r.id === "pi" ? "border-[#7F95C9] bg-[#1A2446]/60" : "border-[#53648E] bg-[#121935]/55"}`}
              style={{ left: r.x, top: r.y, width: r.w, height: r.h }}
            >
              <RoomLabel label={r.label} status={status} tone={tone} />
            </div>
          );
        })}

        {/* PI office */}
        <div className="absolute" style={{ left: 30, top: 80 }}>
          <Shelf />
        </div>
        <div className="absolute rounded-sm bg-[#3A2F55]/70" style={{ left: 60, top: 236, width: 150, height: 44 }} />
        <div className="absolute" style={{ left: 232, top: 234 }}>
          <Armchair />
        </div>
        <div className="absolute" style={{ left: 240, top: 72 }}>
          <Plant />
        </div>
        <button
          type="button"
          onClick={onMailbox}
          aria-label={scene.mail ? `Mailbox: ${scene.mail} open request${scene.mail > 1 ? "s" : ""} from the PI` : "Mailbox: no open requests"}
          className={`absolute rounded-sm hover:outline hover:outline-2 hover:outline-[#FFD05A] ${scene.mail ? "drop-shadow-[0_0_8px_#FFD05A]" : ""}`}
          style={{ left: MAILBOX.x, top: MAILBOX.y, zIndex: 25 }}
        >
          <Mailbox lit={scene.mail > 0} />
          {scene.mail ? (
            <span className="absolute -right-2 -top-2 flex h-5 min-w-5 items-center justify-center rounded-full border-2 border-[#10162B] bg-[#FF8585] px-1 font-pixel text-[9px] text-[#10162B]">
              {scene.mail}
            </span>
          ) : null}
        </button>

        {/* Research bay whiteboard: the campaign's slices */}
        <div
          className="absolute flex flex-col gap-1.5 border-4 border-[#AAB4CA] bg-[#E9E6DC] p-2"
          style={{ left: WHITEBOARD.x, top: WHITEBOARD.y, width: WHITEBOARD.w, height: WHITEBOARD.h }}
        >
          <span className="font-pixel text-[9px] text-[#10162B]">SLICES</span>
          {campaignSlices.slice(0, 4).map((s) => {
            const st = stageAt(s, t) ?? "";
            const parked = st === "parked";
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => onSlice(s.id)}
                className={`flex w-full min-w-0 flex-col items-start rounded-sm px-1.5 py-1 text-left shadow-[2px_2px_0_rgba(0,0,0,0.25)] ${parked ? "bg-[#FFD0D0]" : "bg-[#FFF3B8]"}`}
              >
                <span className="font-mono text-[10px] leading-tight text-[#10162B]">{s.id.split("-").slice(0, 2).join("-")}</span>
                <span title={s.key} className="block w-full truncate text-[10px] font-semibold leading-tight text-[#10162B]">
                  {s.key}
                </span>
              </button>
            );
          })}
        </div>
        <div className="absolute" style={{ left: 724, top: 244 }}>
          <Plant />
        </div>

        {/* Experiment bay */}
        {Array.from({ length: 6 }, (_, k) => (
          <div key={k} className="absolute" style={{ left: 800 + k * 48, top: 72 }}>
            <Rack busy={b?.kind === "compute"} />
          </div>
        ))}

        {/* Lower bay and lounge */}
        <div className="absolute" style={{ left: 790, top: 440 }}>
          <Cabinet />
        </div>
        <div className="absolute" style={{ left: COFFEE.x, top: COFFEE.y }}>
          <Coffee />
        </div>
        <div className="absolute" style={{ left: 90, top: 560 }}>
          <Sofa />
        </div>
        <div className="absolute" style={{ left: 30, top: 560 }}>
          <Plant />
        </div>
        <div className="absolute" style={{ left: 214, top: 548 }}>
          <Plant />
        </div>
        <div className="absolute" style={{ left: 300, top: 340 }}>
          <Plant />
        </div>
        <div className="absolute" style={{ left: MEETING_TABLE.x, top: MEETING_TABLE.y - 20 }}>
          <MeetingTable />
        </div>
        <span className="absolute font-pixel text-[9px] text-[#AAB4CA]" style={{ left: MEETING_TABLE.x + 50, top: 620 }}>
          MEETING TABLE
        </span>

        {/* Vault */}
        <div className="absolute" style={{ left: VAULT.x, top: VAULT.y }}>
          <VaultDoor />
        </div>

        {/* Characters: behind their desk when home (sitting), in front while walking or standing elsewhere */}
        {scene.seats.map((s) => {
          const home = seatSpot(s.seat);
          const atHome = s.x === home.x && s.y === home.y;
          const look = LOOKS[s.seat];
          const selected = selectedSeat === s.seat;
          return (
            <motion.div
              key={s.seat}
              className="absolute"
              style={{ zIndex: atHome ? 10 : 30 }}
              initial={false}
              animate={{ left: s.x, top: s.y }}
              transition={{ duration: 1.1, ease: "linear" }}
              onAnimationStart={() => setMoving((m) => ({ ...m, [s.seat]: true }))}
              onAnimationComplete={() => setMoving((m) => ({ ...m, [s.seat]: false }))}
            >
              <button
                type="button"
                onClick={() => onSeat(s.seat)}
                aria-label={`Inspect ${s.seat}`}
                className={`block rounded-sm border-2 ${selected ? "border-[#FFD05A]" : "border-transparent"} ${s.current ? "bob" : ""}`}
              >
                <Character look={look} action={s.action} moving={!!moving[s.seat]} />
              </button>
            </motion.div>
          );
        })}

        {/* Desks and workstations above sitting characters; their monitors are buttons */}
        {Object.entries(DESKS).map(([seat, d]) => (
          <div key={seat} className="absolute" style={{ left: d.x, top: d.y, zIndex: 20 }}>
            <Desk lit={!!scene.monitors[seat]} />
            <button
              type="button"
              onClick={() => onComputer(`desk:${seat}`)}
              aria-label={`Watch ${seat}'s screen`}
              className="absolute left-[28px] top-0 h-[18px] w-[40px] rounded-sm hover:outline hover:outline-2 hover:outline-[#FFD05A]"
            />
            <span
              className="absolute left-1/2 top-[46px] -translate-x-1/2 whitespace-nowrap rounded-sm bg-[#10162B]/85 px-1.5 py-0.5 text-[11px] text-[#E8EDF7]"
              style={{ minWidth: DESK_W - 20, textAlign: "center" }}
            >
              {seat}
            </span>
          </div>
        ))}
        {Object.entries(WORKSTATIONS).map(([gpu, w]) => (
          <div key={gpu} className="absolute" style={{ left: w.x, top: w.y, zIndex: 20 }}>
            <Workstation lit={!!scene.monitors[gpu]} />
            <button
              type="button"
              onClick={() => onComputer(gpu)}
              aria-label={`Watch ${gpu}`}
              className="absolute left-0 top-0 h-[26px] rounded-sm hover:outline hover:outline-2 hover:outline-[#63D6CC]"
              style={{ width: WORKSTATION_W }}
            />
            <span className="absolute left-1/2 top-[52px] -translate-x-1/2 font-pixel text-[9px] text-[#63D6CC]">{gpu.toUpperCase()}</span>
          </div>
        ))}

        {/* Bubbles */}
        {scene.bubbles.map((bb) => (
          <button
            key={`${bb.seat}-${bb.strong}`}
            type="button"
            onClick={() => onBubble(bb.seat)}
            className={`absolute border-2 px-2 py-1 text-left text-[11px] leading-snug shadow-[3px_3px_0_#050814] transition ${TONE[bb.tone]} ${bb.strong ? "" : "brightness-[0.7] saturate-50"}`}
            style={{ left: bb.x, top: bb.y, width: bb.w, minHeight: bb.h, zIndex: bb.strong ? 50 : 45 }}
          >
            {bb.title ? (
              <>
                <span className="block truncate text-[10px] font-semibold uppercase tracking-wide text-[#53648E]">{bb.title}</span>
                <span className="line-clamp-3 font-mono text-[10.5px] italic leading-snug text-[#263255]">{bb.text}</span>
              </>
            ) : (
              <span className="line-clamp-2">{bb.text}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
