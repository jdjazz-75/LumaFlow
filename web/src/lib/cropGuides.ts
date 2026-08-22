// LumaFlow v1.0 (2026-08-07)
// Géométrie pure des guides de composition du cadrage (règle des tiers, nombre d'or, spirale
// dorée, etc.), avec gestion du miroir -- aucune dépendance React ni réseau.

// Pure geometry for the crop-frame composition guides (framing_crop addon's overlay catalog,
// surfaced via ZoomState.overlays -- see lib/api.ts). No React, no network calls: every guide is
// a function of the crop frame's own aspect ratio (and, for the 3 orientable guides, a mirror
// state) alone, computed once per render.
//
// All PUBLIC shapes are emitted in a [0,1] x [0,1] "unit square" coordinate space matching the
// SVG <svg viewBox="0 0 1 1" preserveAspectRatio="none"> CropCanvas overlays on top of the crop
// rectangle -- that SVG stretches non-uniformly to the rectangle's real on-screen width/height, so
// axis-aligned guides (thirds, golden_section, center lines) are unaffected by that stretch, but
// anything that depends on TRUE angles or circular curvature (golden_triangles' perpendiculars,
// golden_spiral's quarter-circle arcs, compound_curve's bend) would be visibly skewed if built
// directly in unit-square space. Those are instead built in "true" space -- x in [0, aspectRatio],
// y in [0, 1], the crop rectangle's own real proportions -- and only normalized to the unit square
// at the very end (dividing x by aspectRatio), which the SVG's later non-uniform stretch exactly
// undoes.

export type GuideLine = { type: "line"; x1: number; y1: number; x2: number; y2: number };
export type GuidePath = { type: "path"; d: string };
export type GuideShape = GuideLine | GuidePath;

export type Mirror = { flipX: boolean; flipY: boolean };

const PHI = (1 + Math.sqrt(5)) / 2;
const INV_PHI = 1 / PHI; // ~0.618
const INV_PHI2 = 1 / (PHI * PHI); // ~0.382

type Point = [number, number];

// Internal shape representation, always in UNIT space, kept structured (not yet serialized to an
// SVG "d" string) so a mirror can be applied generically to every guide kind -- including path-
// based ones -- by transforming raw points/flags rather than reparsing path strings.
type RawLine = { kind: "line"; a: Point; b: Point };
type RawCubic = { kind: "cubic"; p0: Point; c1: Point; c2: Point; p1: Point };
type RawArc = { kind: "arc"; from: Point; to: Point; rx: number; ry: number; sweep: 0 | 1 };
type RawShape = RawLine | RawCubic | RawArc;

function rawLine(a: Point, b: Point): RawLine {
  return { kind: "line", a, b };
}

/** Maps a "true" (aspect-correct) point to unit-square storage coordinates. */
function toUnit([x, y]: Point, aspectRatio: number): Point {
  return [x / aspectRatio, y];
}

function unitLine(a: Point, b: Point, aspectRatio: number): RawLine {
  return rawLine(toUnit(a, aspectRatio), toUnit(b, aspectRatio));
}

function thirds(): RawShape[] {
  return [
    rawLine([0, 1 / 3], [1, 1 / 3]),
    rawLine([0, 2 / 3], [1, 2 / 3]),
    rawLine([1 / 3, 0], [1 / 3, 1]),
    rawLine([2 / 3, 0], [2 / 3, 1]),
  ];
}

function goldenSection(): RawShape[] {
  return [
    rawLine([0, INV_PHI2], [1, INV_PHI2]),
    rawLine([0, INV_PHI], [1, INV_PHI]),
    rawLine([INV_PHI2, 0], [INV_PHI2, 1]),
    rawLine([INV_PHI, 0], [INV_PHI, 1]),
  ];
}

function diagonal(): RawShape[] {
  return [rawLine([0, 0], [1, 1]), rawLine([0, 1], [1, 0])];
}

/** Classic "golden triangles" guide: one main diagonal plus a perpendicular dropped from each of
the other two corners onto it -- computed in true (aspect-correct) space, since "perpendicular"
would otherwise be distorted by the SVG's non-uniform stretch for any non-square crop box. */
function goldenTriangles(aspectRatio: number): RawShape[] {
  const r = aspectRatio;
  const a: Point = [0, 0];
  const b: Point = [r, 1];
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  function footOfPerpendicular(p: Point): Point {
    const t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lengthSquared;
    return [a[0] + t * dx, a[1] + t * dy];
  }
  const topRight: Point = [r, 0];
  const bottomLeft: Point = [0, 1];
  return [
    unitLine(a, b, r),
    unitLine(topRight, footOfPerpendicular(topRight), r),
    unitLine(bottomLeft, footOfPerpendicular(bottomLeft), r),
  ];
}

/** Short converging segments from each EDGE MIDPOINT to the center. */
function centerLines(): RawShape[] {
  const c: Point = [0.5, 0.5];
  return [
    rawLine([0.5, 0], c),
    rawLine([0.5, 1], c),
    rawLine([0, 0.5], c),
    rawLine([1, 0.5], c),
  ];
}

function pyramid(): RawShape[] {
  const apex: Point = [0.5, 0];
  return [rawLine(apex, [0, 1]), rawLine(apex, [1, 1])];
}

/** An S-curve ("line of beauty") sweeping across the frame -- a decorative composition aid, not a
precisely-defined construction like the others; built as a cubic bezier through the frame's
diagonal in true space so its bend reads the same regardless of the crop's aspect ratio. */
function compoundCurve(aspectRatio: number): RawShape[] {
  const r = aspectRatio;
  return [
    {
      kind: "cubic",
      p0: toUnit([0, 0.85], r),
      c1: toUnit([r * 0.65, 1.0], r),
      c2: toUnit([r * 0.35, 0.0], r),
      p1: toUnit([r, 0.15], r),
    },
  ];
}

type Rect = { left: number; top: number; width: number; height: number };
type CornerKey = "TL" | "TR" | "BR" | "BL";
const DIAGONAL_OF: Record<CornerKey, CornerKey> = { TL: "BR", BR: "TL", TR: "BL", BL: "TR" };

function pointsEqual(a: Point, b: Point): boolean {
  return Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
}

function angleOf(center: Point, point: Point): number {
  return Math.atan2(point[1] - center[1], point[0] - center[0]);
}

/** Sweep flag for a 90-degree SVG arc from `from` to `to` around `center`, derived directly from
the actual geometry (not a hand-picked constant) so it's correct regardless of which corner ends
up as center for a given step. */
function sweepFlagFor(center: Point, from: Point, to: Point): 0 | 1 {
  let diff = angleOf(center, to) - angleOf(center, from);
  while (diff <= -Math.PI) diff += 2 * Math.PI;
  while (diff > Math.PI) diff -= 2 * Math.PI;
  return diff > 0 ? 1 : 0;
}

/** "Whirling squares" spiral (the general construction the golden spiral is a special case of --
converges to a true logarithmic spiral only when aspectRatio === PHI, but reads as a reasonable
spiral guide for any rectangle, which is what a crop frame usually is). At each step, the largest
possible square is cut from the current remaining rectangle (side = its shorter dimension), and a
quarter-circle arc is inscribed in it.
Continuity across steps is guaranteed by construction: each arc's start point is literally the
previous arc's end point (`cursor`), and -- this is the part an earlier version of this function
got wrong, producing a single oversized first arc with no visible narrowing after it -- the square
is cut from WHICHEVER side of the current rectangle the cursor actually sits on (left or right for
a vertical cut, top or bottom for a horizontal one), not unconditionally from a fixed side. Always
cutting from a fixed side looks fine for the very first square (nothing to connect to yet) but
strands every arc after the first as soon as the cursor lands on the opposite edge from the
hardcoded one -- the loop still ran, but each subsequent "arc" silently failed its corner match and
was dropped, which is what actually produced the single-huge-arc-only symptom. The arc's center is
derived from which corner of the square borders the leftover region on whichever side it was cut
from, not from a parity guess. */
function goldenSpiral(aspectRatio: number): RawShape[] {
  const r = aspectRatio;
  const arcs: RawShape[] = [];
  let rect: Rect = { left: 0, top: 0, width: r, height: 1 };
  // Arbitrary but consistent starting anchor -- a corner of the very first square. Since it's on
  // the frame's own left edge (x=0), the first cut is naturally "from the left" below, with no
  // special-casing needed for iteration 0.
  let cursor: Point = [0, 1];

  // Threshold is relative to the frame's own reference size (1% of its shorter original
  // dimension), NOT a fixed absolute epsilon -- an earlier 1e-3 absolute threshold looked safe in
  // isolation but broke visibly during live crop-resize drags: for a broad, ordinary range of
  // aspect ratios (not just near-golden-ratio ones), the whirling-squares construction hits a
  // remaining rectangle that's nearly an exact square partway through, after which convergence to
  // zero slows to a crawl -- many more near-identical micro-cuts before the remainder finally drops
  // below threshold. A ratio change as small as 0.06% (an ordinary sub-pixel nudge mid-drag) was
  // enough to flip a clean 3-arc render into that same 3 arcs plus 9 degenerate micro-arcs. Because
  // each arc is drawn with vector-effect="non-scaling-stroke", those micro-arcs don't fade away
  // invisibly like their tiny geometric size would suggest -- they render at full on-screen stroke
  // width, piling into a visible tangled smudge instead of the spiral's clean point. Scaling the
  // threshold to the frame's own size (instead of an absolute constant) and trimming the iteration
  // cap (a composition guide never needs more than ~2 visible turns) cuts the construction off
  // before it enters that resonant tail, confirmed against both the original bug's reproduction and
  // a deliberately near-PHI crop (which still renders a full, cleanly-tapering multi-arc spiral).
  const minVisibleSide = Math.min(r, 1) * 0.01;
  for (let i = 0; i < 8 && rect.width > minVisibleSide && rect.height > minVisibleSide; i += 1) {
    const side = Math.min(rect.width, rect.height);
    const vertical = rect.width >= rect.height; // true => square spans full height; false => full width
    let leftoverSide: "left" | "right" | "top" | "bottom";
    let squareLeft = rect.left;
    let squareTop = rect.top;
    if (vertical) {
      const fromRight = Math.abs(cursor[0] - (rect.left + rect.width)) < 1e-6;
      squareLeft = fromRight ? rect.left + rect.width - side : rect.left;
      leftoverSide = fromRight ? "left" : "right";
    } else {
      const fromBottom = Math.abs(cursor[1] - (rect.top + rect.height)) < 1e-6;
      squareTop = fromBottom ? rect.top + rect.height - side : rect.top;
      leftoverSide = fromBottom ? "top" : "bottom";
    }
    const corners: Record<CornerKey, Point> = {
      TL: [squareLeft, squareTop],
      TR: [squareLeft + side, squareTop],
      BR: [squareLeft + side, squareTop + side],
      BL: [squareLeft, squareTop + side],
    };
    const cursorKey = (Object.keys(corners) as CornerKey[]).find((key) => pointsEqual(corners[key], cursor));
    if (!cursorKey) break; // unreachable by construction, guards against float drift
    const endKey = DIAGONAL_OF[cursorKey];
    const end = corners[endKey];
    const leftoverCorners: Record<typeof leftoverSide, CornerKey[]> = {
      left: ["TL", "BL"], right: ["TR", "BR"], top: ["TL", "TR"], bottom: ["BL", "BR"],
    };
    const candidates = leftoverCorners[leftoverSide];
    const centerKey = candidates.find((key) => key !== cursorKey && key !== endKey) ?? candidates[0];
    const center = corners[centerKey];

    arcs.push({
      kind: "arc",
      from: toUnit(cursor, r),
      to: toUnit(end, r),
      rx: side / r,
      ry: side,
      sweep: sweepFlagFor(center, cursor, end),
    });

    rect =
      leftoverSide === "left" ? { left: rect.left, top: rect.top, width: rect.width - side, height: rect.height }
      : leftoverSide === "right" ? { left: rect.left + side, top: rect.top, width: rect.width - side, height: rect.height }
      : leftoverSide === "top" ? { left: rect.left, top: rect.top, width: rect.width, height: rect.height - side }
      : { left: rect.left, top: rect.top + side, width: rect.width, height: rect.height - side };
    cursor = end;
  }
  return arcs;
}

/** Mirrors a set of raw shapes in unit space. A single-axis flip reverses the arc's rotational
sense (must invert its sweep flag to still render as a valid quarter circle, not a mirrored-but-
wrongly-bulging one); a double flip (both axes = a 180-degree rotation) preserves it. */
function mirrorShapes(shapes: RawShape[], mirror: Mirror): RawShape[] {
  if (!mirror.flipX && !mirror.flipY) return shapes;
  const invertSweep = mirror.flipX !== mirror.flipY;
  function flip([x, y]: Point): Point {
    return [mirror.flipX ? 1 - x : x, mirror.flipY ? 1 - y : y];
  }
  return shapes.map((shape) => {
    if (shape.kind === "line") return { kind: "line", a: flip(shape.a), b: flip(shape.b) };
    if (shape.kind === "cubic") {
      return { kind: "cubic", p0: flip(shape.p0), c1: flip(shape.c1), c2: flip(shape.c2), p1: flip(shape.p1) };
    }
    return {
      kind: "arc", from: flip(shape.from), to: flip(shape.to), rx: shape.rx, ry: shape.ry,
      sweep: invertSweep ? (shape.sweep === 1 ? 0 : 1) : shape.sweep,
    };
  });
}

function serialize(shapes: RawShape[]): GuideShape[] {
  return shapes.map((shape) => {
    if (shape.kind === "line") {
      return { type: "line", x1: shape.a[0], y1: shape.a[1], x2: shape.b[0], y2: shape.b[1] };
    }
    if (shape.kind === "cubic") {
      return {
        type: "path",
        d: `M ${shape.p0[0]} ${shape.p0[1]} C ${shape.c1[0]} ${shape.c1[1]}, ${shape.c2[0]} ${shape.c2[1]}, ${shape.p1[0]} ${shape.p1[1]}`,
      };
    }
    return {
      type: "path",
      d: `M ${shape.from[0]} ${shape.from[1]} A ${shape.rx} ${shape.ry} 0 0 ${shape.sweep} ${shape.to[0]} ${shape.to[1]}`,
    };
  });
}

export type GuideKind =
  | "thirds"
  | "golden_section"
  | "golden_triangles"
  | "golden_spiral"
  | "center_lines"
  | "diagonal"
  | "pyramid"
  | "compound_curve";

/** Guide kinds whose construction is orientation-sensitive -- CropCanvas only shows the mirror
toggles when one of these is the active guide. */
export const MIRROR_CAPABLE_GUIDE_KINDS: readonly string[] = ["golden_triangles", "golden_spiral", "compound_curve"];

const NO_MIRROR: Mirror = { flipX: false, flipY: false };

/** Computes one guide's shapes for a crop frame of the given aspect ratio (frame width / frame
height, in real pixels). `mirror` only affects the kinds in MIRROR_CAPABLE_GUIDE_KINDS; the others
are already symmetric under both flips, so applying it to them would be a visible no-op. */
export function guideShapes(kind: string, aspectRatio: number, mirror: Mirror = NO_MIRROR): GuideShape[] {
  const safeRatio = aspectRatio > 0 && Number.isFinite(aspectRatio) ? aspectRatio : 1;
  let raw: RawShape[];
  switch (kind) {
    case "thirds":
      raw = thirds();
      break;
    case "golden_section":
      raw = goldenSection();
      break;
    case "golden_triangles":
      raw = mirrorShapes(goldenTriangles(safeRatio), mirror);
      break;
    case "golden_spiral":
      raw = mirrorShapes(goldenSpiral(safeRatio), mirror);
      break;
    case "center_lines":
      raw = centerLines();
      break;
    case "diagonal":
      raw = diagonal();
      break;
    case "pyramid":
      raw = pyramid();
      break;
    case "compound_curve":
      raw = mirrorShapes(compoundCurve(safeRatio), mirror);
      break;
    default:
      raw = [];
  }
  return serialize(raw);
}
