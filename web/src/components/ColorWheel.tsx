// LumaFlow v1.0 (2026-08-07)
// Sélecteur teinte+saturation en disque (angle = teinte, distance au centre = saturation),
// utilisé notamment par le Zoom de Monochrome Tone/Color Splash.

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { hexToHsl, hslToHex } from "../lib/color";
import "./ColorWheel.css";

// 2D hue+saturation picker for Monochrome Tone's Zoom (feature 2026-07-27) -- coexists with
// the linear hue/tint_saturation sliders rather than replacing them (user's explicit choice).
// Angle = hue, distance from center = saturation, following the same "compass" convention
// (0 deg = top, clockwise) as HueRing.tsx's angleFromPointer, so the two controls feel
// consistent even though HueRing is an annulus (hue only) and this is a filled disc (hue +
// saturation). The disc itself is two stacked CSS gradients (conic for hue, radial white
// overlay for the saturation falloff toward the center) rather than many SVG segments --
// unlike HueRing's ring, a plain CSS gradient can fill a disc with no seam to worry about.

// Reference lightness used ONLY to display/parse the hex swatch -- never sent to the backend
// and not a real addon parameter. Monochrome Tone's actual pixel lightness always comes from
// the image's own grayscale value, not from this preset's tint color.
const REFERENCE_LIGHTNESS = 50;

const MAX_RADIUS_PCT = 46; // leaves room so the knob isn't clipped at the wheel's edge

// Feather-wedge overlay geometry (Color Splash's Zoom, feature 2026-07-27) -- a thin
// highlighted band near the rim showing the ±feather degree window kept around `hue`,
// same visual role as HueRing.tsx's own wedge (annulusWedgePath/polarToCartesian) but
// duplicated locally rather than imported: this file already keeps its own copy of the
// polar math for `valuesFromPointer` instead of reusing HueRing's (unexported) helpers.
const WEDGE_OUTER_RADIUS = 48;
const WEDGE_INNER_RADIUS = 44;

type ColorWheelProps = {
  hue: number;
  saturation: number;
  onChange: (hue: number, saturation: number) => void;
  /** Degrees; when provided, overlays a highlighted arc band (±feather around `hue`)
  near the rim. Omitted entirely by Monochrome Tone's usage -- no visual change there. */
  feather?: number;
};

function polarPoint(radius: number, angleDeg: number): { x: number; y: number } {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: 50 + radius * Math.sin(rad), y: 50 - radius * Math.cos(rad) };
}

function featherWedgePath(startAngle: number, endAngle: number): string {
  const outerStart = polarPoint(WEDGE_OUTER_RADIUS, startAngle);
  const outerEnd = polarPoint(WEDGE_OUTER_RADIUS, endAngle);
  const innerEnd = polarPoint(WEDGE_INNER_RADIUS, endAngle);
  const innerStart = polarPoint(WEDGE_INNER_RADIUS, startAngle);
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1;
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${WEDGE_OUTER_RADIUS} ${WEDGE_OUTER_RADIUS} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${WEDGE_INNER_RADIUS} ${WEDGE_INNER_RADIUS} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

function valuesFromPointer(
  event: ReactPointerEvent,
  rect: DOMRect,
): { hue: number; saturation: number } {
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const dx = event.clientX - cx;
  const dy = event.clientY - cy;
  const angle = (Math.atan2(dx, -dy) * 180) / Math.PI;
  const hue = ((angle % 360) + 360) % 360;
  const maxRadius = rect.width / 2;
  const distance = Math.sqrt(dx * dx + dy * dy);
  const saturation = Math.max(0, Math.min(1, maxRadius === 0 ? 0 : distance / maxRadius)) * 100;
  return { hue, saturation };
}

export function ColorWheel({ hue, saturation, onChange, feather }: ColorWheelProps) {
  const wheelRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const [isDragging, setIsDragging] = useState(false);
  const [hexDraft, setHexDraft] = useState<string | null>(null);

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    const rect = wheelRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragging.current = true;
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    const { hue: h, saturation: s } = valuesFromPointer(event, rect);
    onChange(h, s);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragging.current) return;
    const rect = wheelRef.current?.getBoundingClientRect();
    if (!rect) return;
    const { hue: h, saturation: s } = valuesFromPointer(event, rect);
    onChange(h, s);
  }

  function handlePointerUp() {
    dragging.current = false;
    setIsDragging(false);
  }

  function commitHexDraft() {
    if (hexDraft !== null) {
      const parsed = hexToHsl(hexDraft);
      if (parsed) onChange(parsed.hue, parsed.saturation);
    }
    setHexDraft(null);
  }

  const radiusPct = (saturation / 100) * MAX_RADIUS_PCT;
  const angleRad = (hue * Math.PI) / 180;
  const knobX = 50 + radiusPct * Math.sin(angleRad);
  const knobY = 50 - radiusPct * Math.cos(angleRad);
  const displayHex = hexDraft ?? hslToHex(hue, saturation, REFERENCE_LIGHTNESS);

  return (
    <div className="color-wheel-container">
      <div
        ref={wheelRef}
        className="color-wheel"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        {feather !== undefined && (
          <svg className="color-wheel__feather-overlay" viewBox="0 0 100 100">
            <path d={featherWedgePath(hue - feather, hue + feather)} />
          </svg>
        )}
        <div
          className={`color-wheel__knob${isDragging ? " color-wheel__knob--dragging" : ""}`}
          style={{ left: `${knobX}%`, top: `${knobY}%` }}
        />
      </div>
      <div className="color-wheel__hex-row">
        <span className="color-wheel__hex-swatch" style={{ backgroundColor: displayHex }} />
        <input
          type="text"
          className="color-wheel__hex-input"
          value={displayHex}
          onFocus={() => setHexDraft(displayHex)}
          onChange={(event) => setHexDraft(event.target.value)}
          onBlur={commitHexDraft}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
      </div>
    </div>
  );
}
