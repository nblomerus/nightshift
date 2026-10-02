"use client";

import { useEffect, useMemo, useState } from "react";

import { type ScreenTarget, Inspector, type Tab } from "@/components/Inspector";
import { LabFloor } from "@/components/LabFloor";
import { QuickHelp } from "@/components/QuickHelp";
import { SliceStrip } from "@/components/SliceStrip";
import { TopBar } from "@/components/TopBar";
import { Transport } from "@/components/Transport";
import { sceneAt } from "@/lib/scene";
import type { Replay } from "@/lib/types";
import { useReplay } from "@/lib/useReplay";
import { useRequests } from "@/lib/useRequests";
import { type Mode, useRun, useRuns } from "@/lib/useRun";

const EMPTY: Replay = { rig: "", mission: "", seats: {}, stages: [], standards: {}, beats: [], total: 0, calls: {}, msgs: [], slices: [], ledger: {} };

// Deep links: ?run=latest&t=312&tab=seat&seat=critic opens that moment, paused. Rendered client-only (app/page.tsx),
// so the URL can be read once, at startup.
function linkParams() {
  const q = new URLSearchParams(window.location.search);
  const tab = q.get("tab");
  const t = q.get("t");
  return {
    run: q.get("run"),
    tab: (tab && ["screen", "seat", "slice", "talk", "mail"].includes(tab) ? tab : "screen") as Tab,
    seat: q.get("seat") ?? "pi",
    t: t !== null && !Number.isNaN(Number(t)) ? Number(t) : null,
  };
}

export default function LabApp() {
  const [link] = useState(linkParams);
  const runs = useRuns();
  const [run, setRun] = useState<string | null>(link.run);
  const [mode, setMode] = useState<Mode>("replay");
  const { replay, error, connected } = useRun(run ?? runs[0]?.name ?? null, mode);
  const data = replay ?? EMPTY;
  const player = useReplay(data.beats, data.total, mode === "live", link.t);
  const mail = useRequests(data.rig || runs[0]?.rig || "");
  const scene = useMemo(() => sceneAt(data, player.t, mail.open), [data, player.t, mail.open]);

  const [tab, setTab] = useState<Tab>(link.tab);
  const [seat, setSeat] = useState(link.seat);
  const [slice, setSlice] = useState<string | null>(null);
  const [screen, setScreen] = useState<ScreenTarget>("follow");
  const [allCampaigns, setAllCampaigns] = useState(false);
  const [help, setHelp] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setHelp((h) => !h);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const campaigns = Math.max(1, ...data.beats.map((b) => b.campaign));
  const b = scene.beat;
  const caption = b ? (
    <>
      <span className="font-semibold text-[#FFD05A]">{b.actor}</span>
      {b.target ? <span className="text-[#AAB4CA]"> → {b.target}</span> : null}
      <span className="text-[#AAB4CA]"> · </span>
      {b.text}
    </>
  ) : (
    "Waiting for the first beat…"
  );

  return (
    <div className="flex h-screen min-h-[760px] flex-col bg-[#080D1C] text-[#E8EDF7]">
      <TopBar
        campaign={scene.campaign}
        campaigns={campaigns}
        activeSlice={scene.activeSlice}
        beat={scene.index + 1}
        beats={data.beats.length}
        runs={runs}
        run={run ?? runs[0]?.name ?? null}
        onRun={(r) => setRun(r)}
        mode={mode}
        onMode={setMode}
        connected={connected}
        onHelp={() => setHelp(true)}
      />
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col gap-3 p-3">
          <div className="min-h-0 flex-1 rounded-md border border-[#1B2444] bg-[#050914]">
            {replay ? (
              <LabFloor
                replay={data}
                scene={scene}
                t={player.t}
                selectedSeat={tab === "seat" ? seat : null}
                onSeat={(s) => {
                  setSeat(s);
                  setTab("seat");
                }}
                onComputer={(k) => {
                  setScreen(k as ScreenTarget);
                  setTab("screen");
                }}
                onSlice={(id) => {
                  setSlice(id);
                  setTab("slice");
                }}
                onMailbox={() => setTab("mail")}
                onBubble={(s) => {
                  if (b?.kind === "talk" && (b.actor === s || b.target === s)) setTab("talk");
                  else {
                    setScreen(`desk:${s}`);
                    setTab("screen");
                  }
                }}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-[14px] text-[#AAB4CA]">
                {error ? `Could not load the run (${error}). Is the floor server running? make floor` : runs.length ? "Loading the run…" : "Looking for runs…"}
              </div>
            )}
          </div>
          <div className="max-h-[236px] shrink-0">
            <SliceStrip
              replay={data}
              t={player.t}
              campaign={scene.campaign}
              allCampaigns={allCampaigns}
              onToggleAll={() => setAllCampaigns((a) => !a)}
              selected={tab === "slice" ? slice : null}
              onSlice={(id) => {
                setSlice(id);
                setTab("slice");
              }}
            />
          </div>
          <Transport player={player} total={data.total} live={mode === "live"} caption={caption} />
        </main>
        <Inspector replay={data} scene={scene} t={player.t} tab={tab} onTab={setTab} seat={seat} slice={slice} screen={screen} onScreen={setScreen} requests={mail.requests} onReply={mail.reply} />
      </div>
      <QuickHelp open={help} onClose={() => setHelp(false)} />
    </div>
  );
}
