// LumaFlow v1.0 (2026-08-07)
// Sélecteur circulaire de plages de teinte (jusqu'à 3 curseurs simultanés), utilisé par le Zoom
// de Color Splash pour définir les intervalles de teinte conservés.

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import "./HueRing.css";

// Circular hue-range selector (feature 046) -- the representation chosen over a linear slider
// because hue is a cyclic quantity (0-360 deg) and red, the most common target, sits right on
// the 0/360 seam; a straight slider would split it into two disjoint ends. Up to 3 handles can
// be shown at once on the SAME ring (one per active Color Splash range), each a draggable knob
// positioned at its hue angle, with a wedge behind it showing its feathered (adoucissement) zone.
//
// Drag math uses a "compass" angle convention (0 deg = top/12 o'clock, increasing clockwise) so
// it lines up directly with the ring's CSS conic-gradient background, which starts at the top by
// the same convention.

export type HueRingHandle = {
  identifier: string;
  hue: number;
  feather: number;
  enabled: boolean;
};

type HueRingProps = {
  handles: HueRingHandle[];
  onHueChange: (identifier: string, hue: number) => void;
};

const VIEWBOX_SIZE = 200;
const CENTER = VIEWBOX_SIZE / 2;
const OUTER_RADIUS = 92;
const INNER_RADIUS = 68;
const KNOB_RADIUS = (OUTER_RADIUS + INNER_RADIUS) / 2;
const SPECTRUM_SEGMENT_COUNT = 60; // 6 deg/segment -- fine enough for a smooth-looking gradient
const SPECTRUM_SEGMENT_DEGREES = 360 / SPECTRUM_SEGMENT_COUNT;
// SVG has no native conic-gradient fill (only linear/radial `<defs>` gradients, which can't
// sweep around a ring) -- the spectrum ring is approximated with this many thin same-technology
// annulus segments instead of compositing an HTML div's CSS conic-gradient behind the SVG.
const SPECTRUM_SEGMENTS = Array.from({ length: SPECTRUM_SEGMENT_COUNT }, (_, i) => i * SPECTRUM_SEGMENT_DEGREES);

function polarToCartesian(radius: number, angleDeg: number): { x: number; y: number } {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CENTER + radius * Math.sin(rad), y: CENTER - radius * Math.cos(rad) };
}

/** SVG path for an annulus wedge between two compass angles -- angles are used as-is (not
normalized to [0, 360)), so a wedge that straddles the 0/360 seam (e.g. hue=0, feather=30 ->
-30..30) draws as one continuous shape instead of needing special-case wraparound handling. */
function annulusWedgePath(innerR: number, outerR: number, startAngle: number, endAngle: number): string {
  const outerStart = polarToCartesian(outerR, startAngle);
  const outerEnd = polarToCartesian(outerR, endAngle);
  const innerEnd = polarToCartesian(innerR, endAngle);
  const innerStart = polarToCartesian(innerR, startAngle);
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1;
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

export function HueRing({ handles, onHueChange }: HueRingProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const draggingId = useRef<string | null>(null);
  const [, forceRerender] = useState(0);

  function angleFromPointer(event: ReactPointerEvent): number | null {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = event.clientX - cx;
    const dy = event.clientY - cy;
    const angle = (Math.atan2(dx, -dy) * 180) / Math.PI;
    return ((angle % 360) + 360) % 360;
  }

  function handlePointerDown(identifier: string, event: ReactPointerEvent<SVGCircleElement>) {
    draggingId.current = identifier;
    event.currentTarget.setPointerCapture(event.pointerId);
    // Re-render so the just-grabbed knob visually reflects `draggingId` (drop shadow) --
    // no state value actually changes here, only the ref used by move/up handlers below.
    forceRerender((n) => n + 1);
  }

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (!draggingId.current) return;
    const angle = angleFromPointer(event);
    if (angle === null) return;
    onHueChange(draggingId.current, angle);
  }

  function handlePointerUp() {
    draggingId.current = null;
    forceRerender((n) => n + 1);
  }

  const activeHandles = handles.filter((h) => h.enabled);

  return (
    <svg
      ref={svgRef}
      className="hue-ring"
      viewBox={`0 0 ${VIEWBOX_SIZE} ${VIEWBOX_SIZE}`}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
    >
      {SPECTRUM_SEGMENTS.map((startAngle) => (
        <path
          key={`spectrum-${startAngle}`}
          d={annulusWedgePath(INNER_RADIUS, OUTER_RADIUS, startAngle, startAngle + SPECTRUM_SEGMENT_DEGREES)}
          fill={`hsl(${startAngle}, 80%, 50%)`}
        />
      ))}
      {activeHandles.map((handle) => (
        <path
          key={`wedge-${handle.identifier}`}
          className="hue-ring__wedge"
          d={annulusWedgePath(INNER_RADIUS, OUTER_RADIUS, handle.hue - handle.feather, handle.hue + handle.feather)}
          fill={`hsl(${handle.hue}, 85%, 60%)`}
        />
      ))}
      {activeHandles.map((handle) => {
        const pos = polarToCartesian(KNOB_RADIUS, handle.hue);
        return (
          <circle
            key={`knob-${handle.identifier}`}
            className={`hue-ring__knob${draggingId.current === handle.identifier ? " hue-ring__knob--dragging" : ""}`}
            cx={pos.x}
            cy={pos.y}
            r={9}
            fill={`hsl(${handle.hue}, 85%, 60%)`}
            onPointerDown={(event) => handlePointerDown(handle.identifier, event)}
          />
        );
      })}
      {activeHandles.length === 0 && (
        <text className="hue-ring__empty" x={CENTER} y={CENTER} textAnchor="middle" dominantBaseline="middle">
          Aucun intervalle actif
        </text>
      )}
    </svg>
  );
}
