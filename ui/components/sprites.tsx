// Pixel-art sprites, drawn as crisp SVG rects in the Nightshift palette (assets/nightshift-assets). Frames animate
// with CSS (globals.css: .fa / .fb alternate), so a character types, walks or talks without JS timers.

import type { Action } from "@/lib/scene";

type Look = { shirt: string; hair: string; skin: string; robot?: boolean };

const INK = "#080D1C";
const TROUSERS = "#171F38";

function R({ x, y, w = 1, h = 1, f }: { x: number; y: number; w?: number; h?: number; f: string }) {
  return <rect x={x} y={y} width={w} height={h} fill={f} />;
}

// 12 x 16 grid, drawn at 4x (48 x 64).
export function Character({ look, action, moving }: { look: Look; action: Action; moving: boolean }) {
  const typing = action === "type" || action === "compute";
  const talking = action === "talk";
  const head = look.robot ? (
    <g>
      <R x={5} y={0} w={2} f="#FFD05A" />
      <R x={3} y={1} w={6} h={5} f="#B9C4D8" />
      <R x={4} y={3} f="#63D6CC" />
      <R x={7} y={3} f="#63D6CC" />
      <R x={4} y={5} w={4} f="#53648E" />
    </g>
  ) : (
    <g>
      <R x={3} y={0} w={6} h={2} f={look.hair} />
      <R x={2} y={1} h={3} f={look.hair} />
      <R x={9} y={1} h={3} f={look.hair} />
      <R x={3} y={2} w={6} h={4} f={look.skin} />
      <R x={4} y={3} f={INK} />
      <R x={7} y={3} f={INK} />
      {talking ? (
        <g>
          <g className="fa">
            <R x={5} y={5} w={2} f="#7A2E2E" />
          </g>
          <g className="fb">
            <R x={5} y={5} w={2} f={look.skin} />
          </g>
        </g>
      ) : null}
      <R x={5} y={6} w={2} f={look.skin} />
    </g>
  );
  const body = look.robot ? (
    <g>
      <R x={2} y={7} w={8} h={6} f="#6B7390" />
      <R x={4} y={8} w={4} h={2} f="#63D6CC" />
    </g>
  ) : (
    <R x={2} y={7} w={8} h={5} f={look.shirt} />
  );
  const armColor = look.robot ? "#B9C4D8" : look.shirt;
  const hand = look.robot ? "#B9C4D8" : look.skin;
  const armsStill = (
    <g>
      <R x={1} y={8} h={4} f={armColor} />
      <R x={10} y={8} h={4} f={armColor} />
      <R x={1} y={12} f={hand} />
      <R x={10} y={12} f={hand} />
    </g>
  );
  const arms = typing ? (
    <g>
      <g className="fa">
        <R x={1} y={8} h={3} f={armColor} />
        <R x={10} y={8} h={4} f={armColor} />
        <R x={1} y={11} f={hand} />
        <R x={10} y={12} f={hand} />
      </g>
      <g className="fb">
        <R x={1} y={8} h={4} f={armColor} />
        <R x={10} y={8} h={3} f={armColor} />
        <R x={1} y={12} f={hand} />
        <R x={10} y={11} f={hand} />
      </g>
    </g>
  ) : (
    armsStill
  );
  const legY = look.robot ? 13 : 12;
  const legH = look.robot ? 3 : 4;
  const legs = moving ? (
    <g>
      <g className="fa">
        <R x={3} y={legY} w={2} h={legH} f={TROUSERS} />
        <R x={7} y={legY} w={2} h={legH - 1} f={TROUSERS} />
      </g>
      <g className="fb">
        <R x={3} y={legY} w={2} h={legH - 1} f={TROUSERS} />
        <R x={7} y={legY} w={2} h={legH} f={TROUSERS} />
      </g>
    </g>
  ) : (
    <g>
      <R x={3} y={legY} w={2} h={legH} f={TROUSERS} />
      <R x={7} y={legY} w={2} h={legH} f={TROUSERS} />
    </g>
  );
  return (
    <svg width={48} height={64} viewBox="0 0 12 16" shapeRendering="crispEdges" aria-hidden="true">
      <ellipse cx={6} cy={15.6} rx={4} ry={0.6} fill="#000" opacity={0.35} />
      {legs}
      {body}
      {arms}
      {head}
    </svg>
  );
}

function Screen({ lit, w, h }: { lit: boolean; w: number; h: number }) {
  return (
    <g>
      <rect x={0} y={0} width={w} height={h} fill={lit ? "#0E3A36" : "#151D3A"} />
      {lit ? (
        <g className="scanlines">
          {Array.from({ length: Math.floor(h / 4) }, (_, k) => (
            <rect key={k} x={2} y={2 + k * 4} width={Math.max(4, ((k * 7) % (w - 6)) + 4)} height={2} fill="#63D6CC" />
          ))}
        </g>
      ) : null}
    </g>
  );
}

// A research desk: 96 x 44, the monitor is the click target drawn by the floor on top.
export function Desk({ lit }: { lit: boolean }) {
  return (
    <svg width={96} height={44} viewBox="0 0 96 44" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={0} y={16} width={96} height={12} fill="#684A31" />
      <rect x={0} y={28} width={96} height={4} fill="#4A3425" />
      <rect x={6} y={32} width={6} height={12} fill="#4A3425" />
      <rect x={84} y={32} width={6} height={12} fill="#4A3425" />
      <rect x={30} y={0} width={36} height={16} fill={INK} stroke="#53648E" strokeWidth={2} />
      <g transform="translate(33,3)">
        <Screen lit={lit} w={30} h={10} />
      </g>
      <rect x={36} y={19} width={24} height={4} fill="#263255" />
      <rect x={70} y={18} width={8} height={6} fill="#AAB4CA" />
    </svg>
  );
}

export function Workstation({ lit }: { lit: boolean }) {
  return (
    <svg width={88} height={48} viewBox="0 0 88 48" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={0} y={24} width={88} height={10} fill="#53648E" />
      <rect x={0} y={34} width={88} height={4} fill="#263255" />
      <rect x={6} y={38} width={6} height={10} fill="#263255" />
      <rect x={76} y={38} width={6} height={10} fill="#263255" />
      {[6, 46].map((x) => (
        <g key={x}>
          <rect x={x} y={2} width={36} height={22} fill={INK} stroke="#53648E" strokeWidth={2} />
          <g transform={`translate(${x + 3},5)`}>
            <Screen lit={lit} w={30} h={16} />
          </g>
        </g>
      ))}
      <rect x={30} y={40} width={28} height={4} fill={lit ? "#63D6CC" : "#263255"} />
    </svg>
  );
}

export function Rack({ busy }: { busy: boolean }) {
  return (
    <svg width={40} height={96} viewBox="0 0 40 96" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={1} y={1} width={38} height={94} fill="#171F38" stroke="#53648E" strokeWidth={2} />
      {[6, 28, 50, 72].map((y) => (
        <g key={y}>
          <rect x={5} y={y} width={30} height={18} fill="#10162B" stroke="#263255" strokeWidth={1} />
          <rect x={9} y={y + 7} width={4} height={4} fill="#63D6CC" className={busy ? "led" : undefined} />
          <rect x={16} y={y + 7} width={4} height={4} fill={y % 44 === 6 ? "#65D39A" : "#63D6CC"} className={busy ? "led2" : undefined} />
          <rect x={23} y={y + 7} width={4} height={4} fill="#FFD05A" className={busy ? "led" : undefined} opacity={0.8} />
        </g>
      ))}
    </svg>
  );
}

export function VaultDoor() {
  return (
    <svg width={140} height={124} viewBox="0 0 140 124" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={2} y={2} width={136} height={120} fill="#171F38" stroke="#53648E" strokeWidth={4} />
      {Array.from({ length: 9 }, (_, k) => (
        <rect key={k} x={6 + k * 15} y={6} width={8} height={5} fill="#FFD05A" />
      ))}
      {Array.from({ length: 9 }, (_, k) => (
        <rect key={`b${k}`} x={6 + k * 15} y={113} width={8} height={5} fill="#FFD05A" />
      ))}
      <rect x={18} y={16} width={104} height={92} fill="#10162B" stroke="#263255" strokeWidth={4} />
      <circle cx={70} cy={62} r={30} fill="#263255" stroke="#53648E" strokeWidth={4} />
      <rect x={60} y={58} width={20} height={20} fill="#B4A7FF" />
      <rect x={64} y={48} width={12} height={12} fill="none" stroke="#B4A7FF" strokeWidth={3} />
      <rect x={68} y={64} width={4} height={6} fill="#10162B" />
    </svg>
  );
}

export function Plant({ size = 1 }: { size?: number }) {
  return (
    <svg width={28 * size} height={40 * size} viewBox="0 0 28 40" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={8} y={26} width={12} height={14} fill="#684A31" />
      <rect x={6} y={24} width={16} height={4} fill="#4A3425" />
      <rect x={4} y={12} width={6} height={12} fill="#3F9E6B" />
      <rect x={11} y={2} width={6} height={22} fill="#65D39A" />
      <rect x={18} y={10} width={6} height={14} fill="#3F9E6B" />
      <rect x={8} y={6} width={4} height={6} fill="#65D39A" />
    </svg>
  );
}

export function Coffee() {
  return (
    <svg width={44} height={64} viewBox="0 0 44 64" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={2} y={2} width={40} height={60} fill="#53648E" />
      <rect x={6} y={8} width={32} height={16} fill="#FF8585" />
      <rect x={10} y={12} width={10} height={4} fill="#FFD05A" />
      <rect x={10} y={30} width={24} height={16} fill="#151D3A" />
      <rect x={18} y={38} width={8} height={8} fill="#E8EDF7" />
      <rect x={6} y={52} width={32} height={6} fill="#263255" />
    </svg>
  );
}

export function Sofa() {
  return (
    <svg width={100} height={44} viewBox="0 0 100 44" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={0} y={8} width={100} height={28} fill="#3A4570" />
      <rect x={0} y={0} width={100} height={12} fill="#465384" />
      <rect x={0} y={8} width={10} height={30} fill="#465384" />
      <rect x={90} y={8} width={10} height={30} fill="#465384" />
      <rect x={14} y={16} width={34} height={14} fill="#53648E" />
      <rect x={52} y={16} width={34} height={14} fill="#53648E" />
      <rect x={4} y={38} width={6} height={6} fill="#263255" />
      <rect x={90} y={38} width={6} height={6} fill="#263255" />
    </svg>
  );
}

export function Shelf() {
  const books = ["#B4A7FF", "#63D6CC", "#FFD05A", "#FF8585", "#65D39A", "#7FB2FF"];
  return (
    <svg width={64} height={90} viewBox="0 0 64 90" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={0} y={0} width={64} height={90} fill="#4A3425" />
      {[4, 32, 60].map((y, r) => (
        <g key={y}>
          <rect x={4} y={y} width={56} height={24} fill="#2B1F17" />
          {books.map((c, k) => (
            <rect key={k} x={6 + k * 9} y={y + 4 + ((k + r) % 3) * 2} width={7} height={20 - ((k + r) % 3) * 2} fill={c} opacity={0.85} />
          ))}
        </g>
      ))}
    </svg>
  );
}

export function MeetingTable() {
  return (
    <svg width={210} height={96} viewBox="0 0 210 96" shapeRendering="crispEdges" aria-hidden="true">
      {[24, 64, 104, 144].map((x) => (
        <g key={x}>
          <rect x={x} y={0} width={26} height={16} fill="#53648E" />
          <rect x={x} y={80} width={26} height={16} fill="#53648E" />
        </g>
      ))}
      <rect x={0} y={34} width={10} height={28} fill="#53648E" />
      <rect x={200} y={34} width={10} height={28} fill="#53648E" />
      <rect x={10} y={18} width={190} height={60} rx={26} fill="#684A31" stroke="#4A3425" strokeWidth={6} />
      <rect x={40} y={38} width={130} height={20} rx={10} fill="#5A3F2A" />
    </svg>
  );
}

export function Cabinet() {
  return (
    <svg width={40} height={60} viewBox="0 0 40 60" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={0} y={0} width={40} height={60} fill="#3A4570" stroke="#53648E" strokeWidth={2} />
      {[4, 22, 40].map((y) => (
        <g key={y}>
          <rect x={4} y={y} width={32} height={15} fill="#465384" />
          <rect x={16} y={y + 6} width={8} height={3} fill="#AAB4CA" />
        </g>
      ))}
    </svg>
  );
}

export function Armchair() {
  return (
    <svg width={40} height={40} viewBox="0 0 40 40" shapeRendering="crispEdges" aria-hidden="true">
      <rect x={4} y={0} width={32} height={14} fill="#7A4A3A" />
      <rect x={0} y={10} width={40} height={22} fill="#8A5A45" />
      <rect x={8} y={14} width={24} height={12} fill="#9A6A52" />
      <rect x={2} y={32} width={6} height={8} fill="#4A3425" />
      <rect x={32} y={32} width={6} height={8} fill="#4A3425" />
    </svg>
  );
}
