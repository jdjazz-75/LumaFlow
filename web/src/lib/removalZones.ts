// LumaFlow v1.0 (2026-09-23)
// Fonctions pures pour l'addon Suppression d'objets (feature 100) : jusqu'à 8 zones (polygones),
// conversion vers/depuis les clés à plat de l'addon, création/insertion/suppression de sommets,
// aire d'un polygone.

/* Reuses SubjectMaskStage.tsx's own pure helpers (MaskPoint, clampMaskFraction,
maskValuesFromById, MAX_MASK_VERTICES/MIN_MASK_VERTICES) for the per-vertex plumbing -- a normal
TS import, unlike the Python addon files' "no cross-addon import" constraint. Only the
per-ZONE bookkeeping (up to 8 independent polygons instead of one, no per-zone feather/invert --
those two are GLOBAL sliders shared by every zone) is new here. */
import { MAX_MASK_VERTICES, MIN_MASK_VERTICES, clampMaskFraction, maskValuesFromById, type MaskPoint } from "../components/SubjectMaskStage";

export { MAX_MASK_VERTICES, MIN_MASK_VERTICES, clampMaskFraction };
export type { MaskPoint };

// Lowered from 8 to 4 (ergonomics revision, 2026-09-24): each zone is now toggled on/off from a
// fixed-size list in the Zoom panel rather than dynamically added, so a small, always-visible list
// reads better than a scrollable "up to 8" one -- see useRemovalZones.ts's `enableZone`.
export const MAX_REMOVAL_ZONES = 4;

export type RemovalValues = {
  /** Fixed-length (MAX_REMOVAL_ZONES) array, one slot per `zone_{n}_` prefix -- an empty array
  means that slot is unused, mirroring the backend's own "count < 3 -> no zone" convention
  (object_removal.py's `_read_zone`). Never compacted/renumbered: slot `n` always round-trips to
  `zone_{n}_mask_point_*`, which is what lets "select zone 3, delete zone 1" leave zone 3's own
  identifier keys untouched. */
  zones: MaskPoint[][];
  dilation: number;
  feather: number;
  variant: number;
};

const DEFAULT_DILATION = 0.5;
const DEFAULT_FEATHER = 0.3;
const DEFAULT_VARIANT = 0;

/** Builds a RemovalValues record from zoomState's own flat {identifier: value} map -- mirrors
CropToolStage.tsx's cropValuesFromById / SubjectMaskStage.tsx's maskValuesFromById. A zone slot
with fewer than 3 vertices (missing entirely, or explicitly below 3) resolves to an empty array,
same "no shape at all" convention the backend uses. */
export function removalValuesFromById(byId: Record<string, number>): RemovalValues {
  const zones: MaskPoint[][] = [];
  for (let n = 0; n < MAX_REMOVAL_ZONES; n++) {
    const { points } = maskValuesFromById(byId, `zone_${n}_`);
    zones.push(points.length >= MIN_MASK_VERTICES ? points : []);
  }
  return {
    zones,
    dilation: byId["dilation"] ?? DEFAULT_DILATION,
    feather: byId["feather"] ?? DEFAULT_FEATHER,
    variant: byId["variant"] ?? DEFAULT_VARIANT,
  };
}

/** Flattens a RemovalValues back into the addon's own flat scalar keys -- the inverse of
removalValuesFromById, used to build the batched commit payload. Always emits all 8 zone counts
(0 for an unused slot) plus the points of every zone that has any -- a full snapshot each commit
(same convention `maskValuesToUpdates` already uses for a single mask), not an incremental diff. */
export function removalValuesToUpdates(values: RemovalValues): Array<{ identifier: string; value: number }> {
  const updates: Array<{ identifier: string; value: number }> = [
    { identifier: "dilation", value: values.dilation },
    { identifier: "feather", value: values.feather },
    { identifier: "variant", value: values.variant },
  ];
  for (let n = 0; n < MAX_REMOVAL_ZONES; n++) {
    const points = values.zones[n] ?? [];
    const prefix = `zone_${n}_`;
    updates.push({ identifier: `${prefix}mask_point_count`, value: points.length });
    points.forEach((point, i) => {
      const idx = String(i).padStart(2, "0");
      updates.push({ identifier: `${prefix}mask_point_${idx}_x`, value: point.x });
      updates.push({ identifier: `${prefix}mask_point_${idx}_y`, value: point.y });
    });
  }
  return updates;
}

/** The rectangle a newly-added zone starts as -- 40%..60% of the frame, shifted a little per slot
index (mod 4) so several zones added in a row don't stack exactly on top of each other. */
export function seedZone(slotIndex: number): MaskPoint[] {
  const shift = 0.03 * (slotIndex % 4);
  const lo = 0.4 + shift;
  const hi = 0.6 + shift;
  return [
    { x: lo, y: lo },
    { x: hi, y: lo },
    { x: hi, y: hi },
    { x: lo, y: hi },
  ];
}

/** Same subdivision rule as ZoomOverlay.tsx's handleMaskMidpointPointerDown -- inserts a vertex at
the midpoint of the edge between `points[edgeIndex]` and its successor (wrapping), returning the
new array and the inserted vertex's index. Caller decides what to do at MAX_MASK_VERTICES (this
function itself has no ceiling -- ZoomOverlay.tsx already guards the call site the same way
SubjectMaskStage's own editor does). */
export function insertMidpoint(points: MaskPoint[], edgeIndex: number): { points: MaskPoint[]; insertedIndex: number } {
  const a = points[edgeIndex];
  const b = points[(edgeIndex + 1) % points.length];
  const midpoint: MaskPoint = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const next = [...points.slice(0, edgeIndex + 1), midpoint, ...points.slice(edgeIndex + 1)];
  return { points: next, insertedIndex: edgeIndex + 1 };
}

/** Removes one vertex -- refuses (returns `points` unchanged) below MIN_MASK_VERTICES, same rule
ZoomOverlay.tsx's handleMaskVertexDoubleClick already enforces for the subject mask. */
export function removeVertex(points: MaskPoint[], index: number): MaskPoint[] {
  if (points.length <= MIN_MASK_VERTICES) return points;
  return points.filter((_, i) => i !== index);
}

/** Shoelace formula, as a fraction of the unit square (0..1) -- `points` are already fractional
(0..1) image coordinates, so this needs no image dimensions. Used for the "large zone" hint (a
zone approaching the whole frame is far more likely to fall back to the plain diffusion repair,
FR-011 -- see RemovalZoneControls). */
export function polygonArea(points: MaskPoint[]): number {
  if (points.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    sum += a.x * b.y - b.x * a.y;
  }
  return Math.abs(sum) / 2;
}

/** How many zone slots currently hold a real (3+ vertex) polygon. */
export function zoneCount(zones: MaskPoint[][]): number {
  return zones.filter((points) => points.length >= MIN_MASK_VERTICES).length;
}
