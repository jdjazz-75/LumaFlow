// LumaFlow v1.0 (2026-08-07)
// Éditeur de contour polygonal Masque Sujet/Arrière-plan : couche de dessin (sommets, milieux
// d'arête, halo de plume) et barre de contrôles (adoucissement/inversion) pour l'addon Light.

import type { RefObject, PointerEvent as ReactPointerEvent } from "react";
import "./CropCanvas.css";
import "./SubjectMaskStage.css";
import { t } from "../i18n";

// Subject/background boundary editor (feature 047, User Stories 3/4). Modeled directly on
// CropToolStage.tsx: same fractionFromPointer math (photo-rect-relative, letterboxing-aware), same
// SVG even-odd dimming-outside-the-shape pattern (crop-canvas__mask, reused verbatim via
// CropCanvas.css), same commit-on-pointer-up convention.
//
// Split into two controlled, stateless components (2026-07-28 bug-fix pass) so the parent
// (ZoomOverlayGeneric) can render the drawing layer INSIDE its zoomable/pannable compare viewport
// and the floating control bar as a sibling of it, both driven by state that now lives in the
// parent (mirrors sliderValues/hueRangeValues) -- this is what lets optical zoom/pan (and its 8
// pan-zone ticks) keep working while the mask is being edited, instead of the editor replacing the
// whole compare viewport with its own unzoomed, unpannable tree as it did originally.

export const MAX_MASK_VERTICES = 32; // mirrors light.py's _MAX_MASK_VERTICES (Decision 5's scalar-wire cap)
export const MIN_MASK_VERTICES = 3;

/** The polygon a freshly opened editor is seeded with when no zone exists yet -- mirrors
color_splash.py's `_FULL_FRAME_POINTS`. With a 0% feather it is exactly equivalent to "no zone",
so opening the editor never alters the render on its own. */
export const FULL_FRAME_POINTS: MaskPoint[] = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 1 },
  { x: 0, y: 1 },
];

export type MaskPoint = { x: number; y: number };
export type MaskValues = { points: MaskPoint[]; feather: number; invert: boolean };

/** Every addon parameter belonging to a polygon mask, whatever its `prefix` -- light.py's
unprefixed `mask_*` keys as well as color_splash.py's per-range `range_N_mask_*` ones. These are
edited through the polygon overlay, never as plain sliders, so the "Réglages manuels" accordion
filters them out with this predicate. Light additionally escapes them via LIGHT_SLIDER_GROUPS'
allow-list; Color Splash has no such allow-list (it renders every ungrouped slider), which makes
this filter the ONLY thing keeping its 201 zone parameters out of "Réglages globaux". */
export function isMaskParameter(identifier: string): boolean {
  return /(^|_)mask_(point_count|point_\d{2}_[xy]|feather|invert)$/.test(identifier);
}

/** Builds a MaskValues record from a flat {identifier: value} map (zoomState.sliders reduced to
an id->value dict) -- mirrors CropToolStage.tsx's cropValuesFromById. `prefix` selects WHICH mask
when an addon declares several (Color Splash's "range_1_"/"range_2_"/"range_3_"); Light's single
mask uses the default empty prefix. Note the per-addon default divergence carried by the fallbacks
below: absent keys mean "Light's default rectangle" for the unprefixed mask, and "no zone at all"
for a prefixed one -- which is why those fallbacks are only ever reached for Light in practice
(Color Splash always ships an explicit value for every key via resolve_zoom_values). */
export function maskValuesFromById(byId: Record<string, number>, prefix = ""): MaskValues {
  const isPrefixed = prefix !== "";
  const count = Math.max(
    0,
    Math.min(MAX_MASK_VERTICES, Math.round(byId[`${prefix}mask_point_count`] ?? (isPrefixed ? 0 : 4))),
  );
  const points: MaskPoint[] = [];
  for (let i = 0; i < count; i++) {
    const idx = String(i).padStart(2, "0");
    points.push({
      x: byId[`${prefix}mask_point_${idx}_x`] ?? 0.5,
      y: byId[`${prefix}mask_point_${idx}_y`] ?? 0.5,
    });
  }
  return {
    points,
    feather: byId[`${prefix}mask_feather`] ?? (isPrefixed ? 0 : 2.0),
    invert: (byId[`${prefix}mask_invert`] ?? 0) >= 0.5,
  };
}

/** Flattens a MaskValues back into the addon's own flat scalar keys -- the inverse of
maskValuesFromById, used to build the batched commit payload. Only emits coordinates for the
CURRENT vertex count: stale `mask_point_NN_*` keys of removed vertices stay in the session dict,
harmlessly, since the backend reads exactly `count` of them. */
export function maskValuesToUpdates(
  values: MaskValues,
  prefix = "",
): Array<{ identifier: string; value: number }> {
  const updates: Array<{ identifier: string; value: number }> = [
    { identifier: `${prefix}mask_point_count`, value: values.points.length },
    { identifier: `${prefix}mask_feather`, value: values.feather },
    { identifier: `${prefix}mask_invert`, value: values.invert ? 1 : 0 },
  ];
  values.points.forEach((point, i) => {
    const idx = String(i).padStart(2, "0");
    updates.push({ identifier: `${prefix}mask_point_${idx}_x`, value: point.x });
    updates.push({ identifier: `${prefix}mask_point_${idx}_y`, value: point.y });
  });
  return updates;
}

export function clampMaskFraction(value: number): number {
  return Math.min(1, Math.max(0, value));
}

type SubjectMaskLayerProps = {
  photoSrc: string;
  points: MaskPoint[];
  /** Feathering zone width in current on-screen render pixels -- mirrors light.py's
  `_polygon_mask` radius (feather_pct/100 * min(source height, width)) applied to the RENDERED
  photo size instead, so it tracks optical zoom automatically without this component needing to
  know the zoom level itself. 0 means no feather to show. */
  featherRadiusPx: number;
  photoRef: RefObject<HTMLDivElement | null>;
  onVertexPointerDown: (index: number, event: ReactPointerEvent<HTMLDivElement>) => void;
  onVertexDoubleClick: (index: number) => void;
  onMidpointPointerDown: (edgeIndex: number, event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp: () => void;
};

/** The drawing surface only -- photo, dimming mask, outline, vertex/midpoint handles. Meant to be
placed inside the parent's own zoomable/scrollable content box (sized externally to the photo's
natural size × current zoom%), not a self-sized stage -- fractionFromPointer-style math in the
parent already accounts for this via photoRef's own live bounding rect, so no coordinate change is
needed regardless of the current zoom/pan state. */
export function SubjectMaskLayer({
  photoSrc,
  points,
  featherRadiusPx,
  photoRef,
  onVertexPointerDown,
  onVertexDoubleClick,
  onMidpointPointerDown,
  onPointerMove,
  onPointerUp,
}: SubjectMaskLayerProps) {
  const outlinePath = points.length > 0 ? `M ${points.map((p) => `${p.x} ${p.y}`).join(" L ")} Z` : "";
  const maskPath = `M0 0H1V1H0Z ${outlinePath}`;
  const canSubdivide = points.length < MAX_MASK_VERTICES;

  return (
    <div
      ref={photoRef}
      className="crop-canvas__photo-bounds"
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      {photoSrc && <img src={photoSrc} alt="" className="crop-canvas__photo" draggable={false} />}
      <svg className="crop-canvas__mask" viewBox="0 0 1 1" preserveAspectRatio="none">
        <path fillRule="evenodd" d={maskPath} />
      </svg>
      {featherRadiusPx > 0 && (
        <svg
          className="subject-mask-stage__feather-halo"
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          style={{ filter: `blur(${featherRadiusPx / 4}px)` }}
        >
          <path d={outlinePath} fill="none" vectorEffect="non-scaling-stroke" strokeWidth={featherRadiusPx} strokeLinejoin="round" />
        </svg>
      )}
      <svg className="subject-mask-stage__outline" viewBox="0 0 1 1" preserveAspectRatio="none">
        <path d={outlinePath} fill="none" vectorEffect="non-scaling-stroke" />
      </svg>
      {points.map((point, index) => (
        <div
          key={index}
          className="subject-mask-stage__vertex"
          style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }}
          onPointerDown={(event) => onVertexPointerDown(index, event)}
          onDoubleClick={() => onVertexDoubleClick(index)}
        />
      ))}
      {canSubdivide &&
        points.map((point, index) => {
          const next = points[(index + 1) % points.length];
          const mx = (point.x + next.x) / 2;
          const my = (point.y + next.y) / 2;
          return (
            <div
              key={`mid-${index}`}
              className="subject-mask-stage__midpoint"
              style={{ left: `${mx * 100}%`, top: `${my * 100}%` }}
              onPointerDown={(event) => onMidpointPointerDown(index, event)}
            >
              +
            </div>
          );
        })}
    </div>
  );
}

type SubjectMaskControlsProps = {
  feather: number;
  invert: boolean;
  onFeatherChange: (value: number) => void;
  onInvertToggle: () => void;
  /** Color Splash only: clears the zone (vertex count back to 0), returning that range to the
  whole image. Light has no equivalent -- its mask has no "no mask" resting state to go back to,
  and vertices can only be removed one by one down to MIN_MASK_VERTICES. Omitted => no button. */
  onClearZone?: () => void;
};

/** Floating control bar (Adoucissement/Inverser) -- rendered as a sibling of the zoomable compare
viewport (not inside it), so it stays fixed on screen while panning, exactly like the optical-zoom
pan-zone ticks it sits alongside. Exiting mask-edit mode is handled by the shared bottom-panel
"Appliquer" button (ZoomOverlay.tsx's handleCorrectionApply), not by a button here -- every
point/feather/invert edit is already committed to the server as it happens via onCommit, so there
is nothing left to save on exit either way. */
export function SubjectMaskControls({
  feather,
  invert,
  onFeatherChange,
  onInvertToggle,
  onClearZone,
}: SubjectMaskControlsProps) {
  return (
    <div className="subject-mask-stage__controls">
      <div className="subject-mask-stage__control-row">
        <span className="subject-mask-stage__control-label">{t("ui.mask.feather")}</span>
        <input
          type="range"
          min={0}
          max={20}
          step={0.5}
          value={feather}
          onChange={(event) => onFeatherChange(Number(event.target.value))}
        />
        <span className="subject-mask-stage__control-value">{feather.toFixed(1)}</span>
      </div>
      <button
        type="button"
        className={`subject-mask-stage__invert-button${invert ? " subject-mask-stage__invert-button--on" : ""}`}
        onClick={onInvertToggle}
      >
        {t("ui.mask.invert")}
      </button>
      {onClearZone && (
        <button type="button" className="subject-mask-stage__invert-button" onClick={onClearZone}>
          {t("ui.mask.whole_image")}
        </button>
      )}
    </div>
  );
}
