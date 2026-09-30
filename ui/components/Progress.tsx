"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------- data (GET /api/progress)
interface Idea {
  n: number;
  change: string;
  seat_written: boolean;
  run: string;
  campaign: number;
  day: string | null;
  decision: string;
  point: number | null;
  lo: number | null;
  hi: number | null;
  grade: string | null;
  against_current: boolean;
  reason: string;
}

export interface ProgressData {
  rig: string;
  champion: { desc: string; promoted: boolean };
  goal: { point: number; lo: number; hi: number; goal: number; met: boolean } | null;
  best: Idea | null;
  ideas: Idea[];
  counts: { tested: number; seat_written: number; stopped: number; candidates: number; runs: number };
  per_day: { day: string; runs: number; tests: number }[];
  supervisor: { runs: number; idle: number; last_run: string | null; last_start: number | null; every: number | null; next_run: number | null; status: string | null };
  lessons: string[];
  requests: string[];
  alerts: { t: string; kind: string; message: string }[];
}

export function useProgress(rig?: string, every = 30_000) {
  const [data, setData] = useState<ProgressData | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(`/api/progress${rig ? `?rig=${encodeURIComponent(rig)}` : ""}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => alive && d && setData(d))
        .catch(() => {});
    load();
    const id = setInterval(load, every);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [rig, every]);
  return data;
}

// ---------------------------------------------------------------------------- decisions are state: colour + icon + label
const DECISION: Record<string, { color: string; icon: string; label: string }> = {
  supported: { color: "#0ca30c", icon: "▲", label: "supported" },
  inconclusive: { color: "#fab219", icon: "◆", label: "inconclusive" },
  no_effect: { color: "#8B95AD", icon: "●", label: "no effect ≥ SESOI" },
  harmful: { color: "#d03b3b", icon: "▼", label: "harmful" },
};
const pc = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "–" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
const name = (c: string) => c.replace(/^code:/, "");

export function labStatus(p: ProgressData | null, now = Date.now() / 1000) {
  if (!p) return { text: "Lab status unknown", tone: "#AAB4CA" };
  const s = p.supervisor;
  if (!s.last_start) return { text: "Lab not started", tone: "#AAB4CA" };
  if (s.status === "goal reached") return { text: "Goal reached · lab stopped", tone: "#0ca30c" };
  const late = s.next_run && s.every ? now - s.next_run > s.every : false;
  if (late) return { text: "Lab overdue: check the supervisor", tone: "#d03b3b" };
  if (s.status === "running") return { text: `Lab running · run ${s.runs + 1}`, tone: "#0ca30c" };
  const mins = s.next_run ? Math.max(0, Math.round((s.next_run - now) / 60)) : null;
  return { text: `Lab waiting · next run ${mins === null ? "soon" : `in ${mins} min`}`, tone: "#63D6CC" };
}

function Tile({ label, children, sub }: { label: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5 rounded-md border border-[#263255] bg-[#10162B] p-4">
      <span className="text-[12px] uppercase tracking-wider text-[#AAB4CA]">{label}</span>
      <span className="text-[26px] font-semibold leading-none text-[#E8EDF7]">{children}</span>
      {sub ? <span className="text-[13px] text-[#C9D1E4]">{sub}</span> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------- forest plot of every tested idea
const LO = -0.15;
const HI = 0.2;
function Forest({ ideas, sesoi, goal }: { ideas: Idea[]; sesoi: number; goal: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 1000;
  const LEFT = 250;
  const ROW = 30;
  const plotW = W - LEFT - 24;
  const x = (v: number) => LEFT + ((Math.max(LO, Math.min(HI, v)) - LO) / (HI - LO)) * plotW;
  const rows = [...ideas].reverse(); // newest on top
  const H = rows.length * ROW + 44;
  const ticks = [-0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2];
  const refs = [
    { v: 0, label: "0", dash: "", color: "#6B7697" },
    { v: sesoi, label: `promotion ${pc(sesoi, 0)}`, dash: "5 4", color: "#AAB4CA" },
    { v: goal, label: `goal ${pc(goal, 0)}`, dash: "2 3", color: "#FFD05A" },
  ];
  const h = hover !== null ? rows[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Every tested idea: relative WAPE reduction with its confidence interval">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={20} y2={H - 20} stroke="#1B2444" strokeWidth={1} />
            <text x={x(t)} y={H - 4} textAnchor="middle" fontSize={11} fill="#AAB4CA">
              {pc(t, 0)}
            </text>
          </g>
        ))}
        {refs.map((r) => (
          <g key={r.label}>
            <line x1={x(r.v)} x2={x(r.v)} y1={16} y2={H - 20} stroke={r.color} strokeWidth={1.5} strokeDasharray={r.dash} />
            <text x={x(r.v) + 4} y={13} fontSize={11} fill={r.color}>
              {r.label}
            </text>
          </g>
        ))}
        {rows.map((i, k) => {
          const y = 30 + k * ROW;
          const d = DECISION[i.decision];
          return (
            <g key={i.n} onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)} className="cursor-default">
              <rect x={0} y={y - ROW / 2} width={W} height={ROW} fill={hover === k ? "#151D3A" : "transparent"} />
              <text x={8} y={y + 4} fontSize={12.5} fill="#E8EDF7">
                {i.seat_written ? "✎ " : ""}
                {name(i.change).slice(0, 28)}
              </text>
              <text x={LEFT - 10} y={y + 4} fontSize={11} fill="#AAB4CA" textAnchor="end">
                {i.day?.slice(5) ?? ""}
              </text>
              {i.point !== null && i.lo !== null && i.hi !== null && d ? (
                <>
                  <line x1={x(i.lo)} x2={x(i.hi)} y1={y} y2={y} stroke={d.color} strokeWidth={2} strokeLinecap="round" />
                  <circle cx={x(i.point)} cy={y} r={5} fill={d.color} stroke="#0B1122" strokeWidth={2} />
                </>
              ) : (
                <text x={x(0) + 8} y={y + 4} fontSize={11} fill="#AAB4CA">
                  {i.decision.replace(/_/g, " ")}: no decision
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {h ? (
        <div className="pointer-events-none absolute right-2 top-2 w-[340px] rounded-md border border-[#53648E] bg-[#0B1122] p-3 text-[12.5px] shadow-lg">
          <div className="font-semibold text-[#E8EDF7]">{name(h.change)}</div>
          <div className="text-[#AAB4CA]">
            {h.run} · campaign {h.campaign} · {h.day}
          </div>
          {h.point !== null ? (
            <div className="mt-1 font-mono text-[#E8EDF7]">
              {pc(h.point, 2)} [{pc(h.lo, 2)}, {pc(h.hi, 2)}]
            </div>
          ) : null}
          <div className="mt-1 flex items-center gap-1.5">
            <span style={{ color: DECISION[h.decision]?.color ?? "#AAB4CA" }}>{DECISION[h.decision]?.icon ?? "○"}</span>
            <span className="text-[#E8EDF7]">{DECISION[h.decision]?.label ?? h.decision.replace(/_/g, " ")}</span>
            {h.grade ? <span className="text-[#AAB4CA]">· {h.grade}</span> : null}
          </div>
          {h.reason ? <div className="mt-1 text-[#C9D1E4]">{h.reason}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------- the page
export default function Progress() {
  const p = useProgress(undefined);
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 30_000);
    return () => clearInterval(id);
  }, []);
  const st = labStatus(p, now);
  if (!p) return <div className="flex h-screen items-center justify-center text-[#AAB4CA]">Loading the lab&apos;s progress…</div>;
  const g = p.goal;
  const today = new Date().toISOString().slice(0, 10);
  const td = p.per_day.find((d) => d.day === today);
  return (
    <div className="min-h-screen bg-[#080D1C] text-[#E8EDF7]">
      <header className="flex h-16 items-center gap-4 border-b-2 border-[#1B2444] bg-[#0B1122] px-6">
        <span className="font-pixel text-[16px]">NIGHTSHIFT</span>
        <span className="text-[13px] text-[#AAB4CA]">Progress · {p.rig}</span>
        <div className="flex-1" />
        <span className="flex items-center gap-2 rounded-md border border-[#263255] px-3 py-2 text-[13px]" style={{ color: st.tone }}>
          <span className="h-2 w-2 rounded-full" style={{ background: st.tone }} />
          {st.text}
        </span>
        <Link href="/" className="rounded-md border border-[#263255] px-3 py-2 text-[13px] text-[#C9D1E4] hover:text-[#E8EDF7]">
          Lab floor
        </Link>
      </header>
      <main className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6">
        <section className="flex gap-4">
          <Tile
            label="Goal: champion vs baseline"
            sub={
              <>
                <div className="mt-1 h-2 rounded-full bg-[#1B2444]">
                  <div className="h-2 rounded-full bg-[#FFD05A]" style={{ width: `${g ? Math.max(0, Math.min(100, (g.point / g.goal) * 100)) : 0}%` }} />
                </div>
                <span className="mt-1 block">{g ? `CI low ${pc(g.lo)} · goal ${pc(g.goal, 0)}` : "checked after each supervised run"}</span>
              </>
            }
          >
            {g ? pc(g.point) : "–"}
          </Tile>
          <Tile
            label="Best candidate"
            sub={
              p.best ? (
                <>
                  {name(p.best.change)} · [{pc(p.best.lo)}, {pc(p.best.hi)}] · {DECISION[p.best.decision]?.label ?? p.best.decision}
                </>
              ) : (
                "nothing decided yet"
              )
            }
          >
            {p.best ? pc(p.best.point) : "–"}
          </Tile>
          <Tile label="Ideas tested" sub={`${p.counts.seat_written} written by seats · ${p.counts.candidates} with CI above 0 · ${p.counts.stopped} stopped`}>
            {p.counts.tested}
          </Tile>
          <Tile label="Today" sub={`${p.counts.runs} runs in all · idle streak ${p.supervisor.idle}`}>
            {td ? `${td.runs} runs · ${td.tests} tests` : "no runs yet"}
          </Tile>
        </section>
        <section className="rounded-md border border-[#1B2444] bg-[#0B1122] p-4">
          <div className="mb-2 flex flex-wrap items-center gap-4">
            <h2 className="font-pixel text-[12px] text-[#63D6CC]">EVERY TESTED IDEA</h2>
            <span className="text-[12px] text-[#AAB4CA]">relative WAPE reduction vs the champion it was tested against, with its CI · newest on top · ✎ written by a seat</span>
            <div className="flex-1" />
            {Object.entries(DECISION).map(([k, d]) => (
              <span key={k} className="flex items-center gap-1.5 text-[12px] text-[#C9D1E4]">
                <span style={{ color: d.color }}>{d.icon}</span>
                {d.label}
              </span>
            ))}
          </div>
          <Forest ideas={p.ideas} sesoi={0.1} goal={g?.goal ?? 0.15} />
        </section>
        <section className="grid grid-cols-3 gap-4">
          <div className="col-span-2 rounded-md border border-[#1B2444] bg-[#0B1122] p-4">
            <h2 className="mb-2 font-pixel text-[12px] text-[#63D6CC]">TABLE</h2>
            <table className="w-full text-left text-[12.5px]">
              <thead className="text-[#AAB4CA]">
                <tr>
                  <th className="py-1.5 font-normal">#</th>
                  <th className="font-normal">idea</th>
                  <th className="font-normal">day</th>
                  <th className="font-normal">decision</th>
                  <th className="text-right font-normal">estimate</th>
                  <th className="text-right font-normal">CI</th>
                </tr>
              </thead>
              <tbody>
                {[...p.ideas].reverse().map((i) => (
                  <tr key={i.n} className="border-t border-[#1B2444]">
                    <td className="py-1.5 text-[#AAB4CA]">{i.n}</td>
                    <td className="text-[#E8EDF7]">
                      {i.seat_written ? "✎ " : ""}
                      {name(i.change)}
                    </td>
                    <td className="text-[#AAB4CA]">{i.day}</td>
                    <td>
                      <span style={{ color: DECISION[i.decision]?.color ?? "#AAB4CA" }}>{DECISION[i.decision]?.icon ?? "○"}</span>{" "}
                      <span className="text-[#C9D1E4]">{DECISION[i.decision]?.label ?? i.decision.replace(/_/g, " ")}</span>
                    </td>
                    <td className="text-right font-mono text-[#E8EDF7]">{pc(i.point)}</td>
                    <td className="text-right font-mono text-[#AAB4CA]">{i.lo !== null ? `[${pc(i.lo)}, ${pc(i.hi)}]` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-col gap-4">
            <div className="rounded-md border border-[#1B2444] bg-[#0B1122] p-4">
              <h2 className="mb-2 font-pixel text-[12px] text-[#63D6CC]">ALERTS</h2>
              {p.alerts.length ? (
                <ul className="flex flex-col gap-2 text-[12.5px]">
                  {[...p.alerts].reverse().map((a) => (
                    <li key={a.t + a.kind}>
                      <span className="font-semibold text-[#FFD05A]">{a.kind}</span> <span className="text-[#AAB4CA]">{a.t.slice(5, 16).replace("T", " ")}</span>
                      <div className="text-[#C9D1E4]">{a.message}</div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[12.5px] text-[#AAB4CA]">None: nothing has needed you.</p>
              )}
            </div>
            <div className="rounded-md border border-[#1B2444] bg-[#0B1122] p-4">
              <h2 className="mb-2 font-pixel text-[12px] text-[#63D6CC]">WHAT THE LAB LEARNED</h2>
              <ul className="flex flex-col gap-2 text-[12.5px] text-[#C9D1E4]">
                {[...p.lessons].reverse().map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              {p.requests.length ? (
                <>
                  <h3 className="mb-1 mt-3 text-[12px] font-semibold text-[#FFD05A]">Asked for data</h3>
                  <ul className="text-[12.5px] text-[#C9D1E4]">
                    {p.requests.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
