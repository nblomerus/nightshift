// Geometry of the lab, in logical scene pixels (the floor scales to fit its container).

export const SCENE = { w: 1120, h: 640 };
export const SPRITE = { w: 48, h: 64 };

export interface Room {
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export const ROOMS: Room[] = [
  { id: "pi", label: "PI OFFICE", x: 16, y: 36, w: 280, h: 262 },
  { id: "research", label: "RESEARCH BAY", x: 312, y: 36, w: 452, h: 262 },
  { id: "compute", label: "EXPERIMENT BAY", x: 780, y: 36, w: 324, h: 262 },
  { id: "vault", label: "FROZEN JUDGE", x: 836, y: 330, w: 268, h: 196 },
];

// Where each seat works. The character stands behind the desk: sprite top-left = desk.x + 20, desk.y - 50.
export const DESKS: Record<string, { x: number; y: number }> = {
  pi: { x: 92, y: 190 },
  methodologist: { x: 470, y: 180 },
  critic: { x: 580, y: 180 },
  writer: { x: 690, y: 180 },
  replicator: { x: 332, y: 420 },
  statistician: { x: 488, y: 420 },
  experimenter: { x: 644, y: 420 },
};

export const WORKSTATIONS: Record<string, { x: number; y: number }> = {
  gpu1: { x: 800, y: 226 },
  gpu2: { x: 902, y: 226 },
  gpu3: { x: 1004, y: 226 },
};

export const VAULT = { x: 900, y: 372, w: 140, h: 124 };
export const VAULT_SPOT = { x: 856, y: 404 };
export const WHITEBOARD = { x: 330, y: 70, w: 110, h: 206 };
export const MEETING_TABLE = { x: 468, y: 540, w: 210, h: 58 };
export const COFFEE = { x: 34, y: 452 };

export const DESK_W = 96;
export const WORKSTATION_W = 88;

export function seatSpot(seat: string): { x: number; y: number } {
  const d = DESKS[seat];
  return d ? { x: d.x + 24, y: d.y - 50 } : { x: 60, y: 520 };
}

export function workstationSpot(place: string): { x: number; y: number } {
  const w = WORKSTATIONS[place];
  return w ? { x: w.x + 20, y: w.y - 50 } : VAULT_SPOT;
}

// Standing in front of someone's desk to talk to them (desks sit side by side, so "beside" would be the neighbour's).
export function besideSpot(seat: string): { x: number; y: number } {
  const d = DESKS[seat];
  return d ? { x: d.x + DESK_W / 2 - 24, y: d.y + 34 } : { x: 60, y: 520 };
}

export const LOOKS: Record<string, { shirt: string; hair: string; skin: string; robot?: boolean }> = {
  pi: { shirt: "#B4A7FF", hair: "#3A2A1E", skin: "#E8B894" },
  methodologist: { shirt: "#63D6CC", hair: "#2B1B19", skin: "#E8B88B" },
  critic: { shirt: "#FF8585", hair: "#20242F", skin: "#F0C7A3" },
  writer: { shirt: "#FFD05A", hair: "#8A5A2B", skin: "#E3B08C" },
  experimenter: { shirt: "#7FB2FF", hair: "#2A1D14", skin: "#B87A55" },
  replicator: { shirt: "#65D39A", hair: "#4A4038", skin: "#F2D0B0" },
  statistician: { shirt: "#53648E", hair: "#B9C4D8", skin: "#D9A878", robot: true },
};

export const SEAT_ORDER = ["pi", "methodologist", "critic", "writer", "replicator", "statistician", "experimenter"];
