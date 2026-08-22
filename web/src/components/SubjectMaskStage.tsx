// LumaFlow v1.0 (2026-08-07)
// Éditeur de contour polygonal Masque Sujet/Arrière-plan : couche de dessin (sommets, milieux
// d'arête, halo de plume) et barre de contrôles (adoucissement/inversion) pour l'addon Light.

import type { RefObject, PointerEvent as ReactPointerEvent } from "react";
import "./CropCanvas.css";
import "./SubjectMaskStage.css";

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

export type MaskPoint = { x: number; y: number };
export type MaskValues = { points: MaskPoint[]; feather: number; invert: boolean };

/** Builds a MaskValues record from a flat {identifier: value} map (zoomState.sliders reduced to
an id->value dict) -- mirrors CropToolStage.tsx's cropValuesFromById. */
export function maskValuesFromById(byId: Record<string, number>): MaskValues {
  const count = Math.max(0, Math.min(MAX_MASK_VERTICES, Math.round(byId.mask_point_count ?? 4)));
  const points: MaskPoint[] = [];
  for (let i = 0; i < count; i++) {
    const idx = String(i).padStart(2, "0");
    points.push({ x: byId[`mask_point_${idx}_x`] ?? 0.5, y: byId[`mask_point_${idx}_y`] ?? 0.5 });
  }
  return { points, feather: byId.mask_feather ?? 2.0, invert: (byId.mask_invert ?? 0) >= 0.5 };
}

/** Flattens a MaskValues back into the addon's own flat scalar keys -- the inverse of
maskValuesFromById, used to build the batched commit payload. */
export function maskValuesToUpdates(values: MaskValues): Array<{ identifier: string; value: number }> {
  const updates: Array<{ identifier: string; value: number }> = [
    { identifier: "mask_point_count", value: values.points.length },
    { identifier: "mask_feather", value: values.feather },
    { identifier: "mask_invert", value: values.invert ? 1 : 0 },
  ];
  values.points.forEach((point, i) => {
    const idx = String(i).padStart(2, "0");
    updates.push({ identifier: `mask_point_${idx}_x`, value: point.x });
    updates.push({ identifier: `mask_point_${idx}_y`, value: point.y });
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
};

/** Floating control bar (Adoucissement/Inverser) -- rendered as a sibling of the zoomable compare
viewport (not inside it), so it stays fixed on screen while panning, exactly like the optical-zoom
pan-zone ticks it sits alongside. Exiting mask-edit mode is handled by the shared bottom-panel
"Appliquer" button (ZoomOverlay.tsx's handleCorrectionApply), not by a button here -- every
point/feather/invert edit is already committed to the server as it happens via onCommit, so there
is nothing left to save on exit either way. */
export function SubjectMaskControls({ feather, invert, onFeatherChange, onInvertToggle }: SubjectMaskControlsProps) {
  return (
    <div className="subject-mask-stage__controls">
      <div className="subject-mask-stage__control-row">
        <span className="subject-mask-stage__control-label">Adoucissement</span>
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
        Inverser
      </button>
    </div>
  );
}
