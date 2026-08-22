// LumaFlow v1.0 (2026-08-07)
// Sélecteur de couleur complet (teinte/saturation en disque + luminosité + hex) utilisé par les
// Préférences pour les couleurs de guidage (limite/overlay) et la couleur d'accentuation.

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { hexToHsl, hslToHex } from "../lib/color";
import "./PreferenceColorPicker.css";

// Same "compass" hue+saturation disc as ColorWheel.tsx (angle = hue, distance from center =
// saturation), extended with a lightness slider for the Préférences color pickers (guide
// limit/overlay colors, 2026-08-06). ColorWheel.tsx itself is left untouched -- it's used as-is
// by 3 addons' réglages manuels with a deliberately fixed reference lightness (not a real color
// picker there, see its own header comment) -- so this is a sibling component, not a shared one.
// Unlike ColorWheel.tsx, the value here is the full hex string: white/black/gray (unreachable on
// ColorWheel's fixed L=50 disc) must stay selectable, since the current "overlay" guide color is
// itself near-white.

const MAX_RADIUS_PCT = 46;

function polarPoint(radius: number, angleDeg: number): { x: number; y: number } {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: 50 + radius * Math.sin(rad), y: 50 - radius * Math.cos(rad) };
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

type PreferenceColorPickerProps = {
  label: string;
  value: string;
  onChange: (hex: string) => void;
};

export function PreferenceColorPicker({ label, value, onChange }: PreferenceColorPickerProps) {
  const wheelRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const [isDragging, setIsDragging] = useState(false);
  const [hexDraft, setHexDraft] = useState<string | null>(null);

  const parsed = hexToHsl(value) ?? { hue: 0, saturation: 0, lightness: 50 };
  const { hue, saturation, lightness } = parsed;

  function commit(nextHue: number, nextSaturation: number, nextLightness: number) {
    onChange(hslToHex(nextHue, nextSaturation, nextLightness));
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    const rect = wheelRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragging.current = true;
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    const { hue: h, saturation: s } = valuesFromPointer(event, rect);
    commit(h, s, lightness);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragging.current) return;
    const rect = wheelRef.current?.getBoundingClientRect();
    if (!rect) return;
    const { hue: h, saturation: s } = valuesFromPointer(event, rect);
    commit(h, s, lightness);
  }

  function handlePointerUp() {
    dragging.current = false;
    setIsDragging(false);
  }

  function commitHexDraft() {
    if (hexDraft !== null) {
      const draftParsed = hexToHsl(hexDraft);
      if (draftParsed) onChange(hslToHex(draftParsed.hue, draftParsed.saturation, draftParsed.lightness));
    }
    setHexDraft(null);
  }

  const radiusPct = (saturation / 100) * MAX_RADIUS_PCT;
  const knob = polarPoint(radiusPct, hue);
  const displayHex = hexDraft ?? value.toUpperCase();

  return (
    <div className="pref-color-picker">
      <span className="pref-color-picker__label">{label}</span>
      <div className="pref-color-picker__body">
        <div
          ref={wheelRef}
          className="pref-color-picker__wheel"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
          <div
            className={`pref-color-picker__knob${isDragging ? " pref-color-picker__knob--dragging" : ""}`}
            style={{ left: `${knob.x}%`, top: `${knob.y}%` }}
          />
        </div>
        <div className="pref-color-picker__controls">
          <label className="pref-color-picker__lightness-row">
            <span>Luminosité</span>
            <input
              type="range"
              min={0}
              max={100}
              value={Math.round(lightness)}
              onChange={(event) => commit(hue, saturation, Number(event.target.value))}
            />
          </label>
          <div className="pref-color-picker__hex-row">
            <span className="pref-color-picker__hex-swatch" style={{ backgroundColor: displayHex }} />
            <input
              type="text"
              className="pref-color-picker__hex-input"
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
      </div>
    </div>
  );
}
