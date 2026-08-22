// LumaFlow v1.0 (2026-08-07)
// Éditeur de forme interactif de l'addon Vignettage : géométrie et rendu de l'ellipse (Round
// Central) ou de la bande (Linear Top+Bottom), avec déplacement/rotation/redimensionnement.

import type { RefObject, PointerEvent as ReactPointerEvent } from "react";
import "./VignetteShapeStage.css";
import { MoveToolIcon, RotationToolIcon, ShapeToolIcon } from "./icons";

// Interactive shape editor for the Vignetting addon's "dynamic aids" pass (on top of feature
// 044's fixed-geometry presets): an ellipse (Round Central) or a line-band (Linear Top+Bottom),
// both with a draggable/rotatable center, reusing Geometry's rotation-dial widget (recentered on
// the shape's own center instead of the image's) and Masque Sujet's stroke+blur halo technique.
//
// Unlike GeometryToolStage/CropToolStage (each a self-contained stage owning its own <img>), this
// is rendered INSIDE ZoomOverlay.tsx's existing shared zoomable/pannable compare viewport
// (.zoom-overlay__compare-content), alongside the before/after split rather than replacing it --
// comparing against the original stays useful for a darkening effect. All state (values, active
// tool, drag target) therefore lives in ZoomOverlay.tsx itself (same reasoning as Masque Sujet's
// SubjectMaskLayer/Controls split, feature 047) -- this file only exports pure geometry helpers
// and stateless presentational components.

export type VignetteShapeValues = {
  center_x: number; center_y: number;
  radius_x: number; radius_y: number;
  top_offset: number; bottom_offset: number;
  rotation_angle: number; feather_width: number;
};

export type VignetteActiveTool = "move" | "rotation" | "resize";
export type EllipseHandleId = "n" | "s" | "e" | "w";
export type LineBorderId = "top" | "bottom";

function formatAngle(angle: number): string {
  return `${angle >= 0 ? "+" : ""}${angle.toFixed(1)}°`;
}

/** Builds a VignetteShapeValues record from a flat {identifier: value} map (zoomState.sliders
reduced by identifier) -- mirrors geometryValuesFromById/maskValuesFromById. */
export function vignetteValuesFromById(byId: Record<string, number>): VignetteShapeValues {
  return {
    center_x: byId.center_x ?? 0.5, center_y: byId.center_y ?? 0.5,
    radius_x: byId.radius_x ?? 0.85, radius_y: byId.radius_y ?? 0.85,
    top_offset: byId.top_offset ?? 0.6, bottom_offset: byId.bottom_offset ?? 0.6,
    rotation_angle: byId.rotation_angle ?? 0, feather_width: byId.feather_width ?? 12,
  };
}

/** Flattens a VignetteShapeValues back into the addon's own flat scalar keys -- the inverse of
vignetteValuesFromById, used to build the batched commit payload (api.setZoomParameters). */
export function vignetteValuesToUpdates(values: VignetteShapeValues): Array<{ identifier: string; value: number }> {
  return (Object.keys(values) as Array<keyof VignetteShapeValues>).map((identifier) => ({
    identifier,
    value: values[identifier],
  }));
}

/** Forward transform (image offset -> the shape's own local/rotated frame) -- mirrors
lumaflow/addons/builtin/vignetting.py's `_rotated_offsets` exactly (dx/dy are in the SAME
per-axis-normalized units, where 1.0 = half the image's own width/height). `aspect` (the image's
own width/height in real pixels) rescales the rotation terms so it happens in an isotropic unit --
without it, rotating this anisotropically-normalized (dx,dy) pair directly shears rather than
rotates the shape for any non-square image (see _rotated_offsets's docstring for the derivation;
this must stay an exact algebraic mirror of that backend fix). */
export function imageOffsetToLocal(
  dx: number, dy: number, rotationAngleDeg: number, aspect: number,
): { rx: number; ry: number } {
  const angle = (rotationAngleDeg * Math.PI) / 180;
  const cosA = Math.cos(angle);
  const sinA = Math.sin(angle);
  return { rx: dx * cosA + (dy / aspect) * sinA, ry: -dx * aspect * sinA + dy * cosA };
}

/** Inverse of imageOffsetToLocal -- the shape's own local coordinates back to image offset, used
to draw geometry defined in local space (ellipse radii, line offsets) onto the image. */
export function localOffsetToImage(
  rx: number, ry: number, rotationAngleDeg: number, aspect: number,
): { dx: number; dy: number } {
  const angle = (rotationAngleDeg * Math.PI) / 180;
  const cosA = Math.cos(angle);
  const sinA = Math.sin(angle);
  return { dx: rx * cosA - (ry / aspect) * sinA, dy: rx * aspect * sinA + ry * cosA };
}

/** Backend units (dx/dy, 1.0 = half the image's own width/height) <-> image-fraction [0,1]
coordinates -- dx = (x - center_x) * 2, so x = center_x + dx / 2. */
export function offsetToFraction(dx: number, dy: number, centerX: number, centerY: number): { x: number; y: number } {
  return { x: centerX + dx / 2, y: centerY + dy / 2 };
}
export function fractionToOffset(x: number, y: number, centerX: number, centerY: number): { dx: number; dy: number } {
  return { dx: (x - centerX) * 2, dy: (y - centerY) * 2 };
}

const ELLIPSE_OUTLINE_SEGMENTS = 64;

export function ellipseOutlinePath(values: VignetteShapeValues, aspect: number): string {
  const points: string[] = [];
  for (let i = 0; i <= ELLIPSE_OUTLINE_SEGMENTS; i++) {
    const theta = (i / ELLIPSE_OUTLINE_SEGMENTS) * 2 * Math.PI;
    const rx = values.radius_x * Math.cos(theta);
    const ry = values.radius_y * Math.sin(theta);
    const { dx, dy } = localOffsetToImage(rx, ry, values.rotation_angle, aspect);
    const { x, y } = offsetToFraction(dx, dy, values.center_x, values.center_y);
    points.push(`${x} ${y}`);
  }
  return `M ${points.join(" L ")} Z`;
}

// Vertex (E/W, controls radius_x) and co-vertex (N/S, controls radius_y) handles, at their own
// local axis position -- dragging either side of an axis changes ONE shared radius (symmetric
// resize about the center, by construction: there's only one radius_x/radius_y field).
const ELLIPSE_HANDLE_LOCAL: Record<EllipseHandleId, (values: VignetteShapeValues) => { rx: number; ry: number }> = {
  e: (v) => ({ rx: v.radius_x, ry: 0 }),
  w: (v) => ({ rx: -v.radius_x, ry: 0 }),
  s: (v) => ({ rx: 0, ry: v.radius_y }),
  n: (v) => ({ rx: 0, ry: -v.radius_y }),
};

export function ellipseHandlePosition(
  id: EllipseHandleId, values: VignetteShapeValues, aspect: number,
): { x: number; y: number } {
  const { rx, ry } = ELLIPSE_HANDLE_LOCAL[id](values);
  const { dx, dy } = localOffsetToImage(rx, ry, values.rotation_angle, aspect);
  return offsetToFraction(dx, dy, values.center_x, values.center_y);
}

// Local rx half-length used to draw the center/border lines -- generous enough that the line
// always crosses the visible 0..1 viewBox regardless of rotation or an off-canvas center.
const LINE_EXTENT = 3;

function lineSegment(
  localRy: number, values: VignetteShapeValues, aspect: number,
): { x1: number; y1: number; x2: number; y2: number } {
  const a = localOffsetToImage(-LINE_EXTENT, localRy, values.rotation_angle, aspect);
  const b = localOffsetToImage(LINE_EXTENT, localRy, values.rotation_angle, aspect);
  const p1 = offsetToFraction(a.dx, a.dy, values.center_x, values.center_y);
  const p2 = offsetToFraction(b.dx, b.dy, values.center_x, values.center_y);
  return { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
}

export function centerLineSegment(values: VignetteShapeValues, aspect: number) {
  return lineSegment(0, values, aspect);
}

// Image y=0 is the top, y=1 is the bottom -- matches vignetting.py's own _line_band_inside
// convention (top_offset bounds the negative/top side, bottom_offset the positive/bottom side).
export function borderLineSegment(id: LineBorderId, values: VignetteShapeValues, aspect: number) {
  return lineSegment(id === "top" ? -values.top_offset : values.bottom_offset, values, aspect);
}

type VignetteShapeOverlayProps = {
  shape: "round_central" | "linear_top_bottom";
  values: VignetteShapeValues;
  /** The image's own width/height in real pixels -- required to rotate the shape rigidly (see
  imageOffsetToLocal/localOffsetToImage's docstrings); falls back to 1 (square) for the brief
  window before the photo's naturalSize is known. */
  aspect: number;
  /** Feathering zone width in current on-screen render pixels -- same formula as Masque Sujet's
  featherRadiusPx (feather_width/100 * min(rendered width, rendered height)), computed by the
  parent so this component doesn't need to know the current zoom level. 0 hides the halo. */
  featherRadiusPx: number;
  activeTool: VignetteActiveTool | null;
  dialRef: RefObject<HTMLDivElement | null>;
  onCenterPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onDialPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onVertexPointerDown: (id: EllipseHandleId, event: ReactPointerEvent<HTMLDivElement>) => void;
  onBorderPointerDown: (id: LineBorderId, event: ReactPointerEvent<SVGLineElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp: () => void;
};

/** The drawing surface only (outline, halo, handles, center, rotation dial) -- meant to sit
inside the parent's own zoomable/pannable content box, sized externally to the photo's own
rendered size, exactly like SubjectMaskLayer. */
export function VignetteShapeOverlay({
  shape, values, aspect, featherRadiusPx, activeTool, dialRef,
  onCenterPointerDown, onDialPointerDown, onVertexPointerDown, onBorderPointerDown,
  onPointerMove, onPointerUp,
}: VignetteShapeOverlayProps) {
  const centerStyle = { left: `${values.center_x * 100}%`, top: `${values.center_y * 100}%` };
  const resizeActive = activeTool === "resize";

  return (
    <div
      className="vignette-shape-stage__root"
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      {shape === "round_central" ? (
        <>
          {featherRadiusPx > 0 && (
            <svg
              className="vignette-shape-stage__feather-halo"
              viewBox="0 0 1 1" preserveAspectRatio="none"
              style={{ filter: `blur(${featherRadiusPx / 4}px)` }}
            >
              <path
                d={ellipseOutlinePath(values, aspect)} fill="none" vectorEffect="non-scaling-stroke"
                strokeWidth={featherRadiusPx} strokeLinejoin="round"
              />
            </svg>
          )}
          <svg className="vignette-shape-stage__outline" viewBox="0 0 1 1" preserveAspectRatio="none">
            <path d={ellipseOutlinePath(values, aspect)} fill="none" vectorEffect="non-scaling-stroke" />
          </svg>
          {resizeActive &&
            (["n", "s", "e", "w"] as const).map((id) => {
              const pos = ellipseHandlePosition(id, values, aspect);
              return (
                <div
                  key={id}
                  className="vignette-shape-stage__vertex"
                  style={{ left: `${pos.x * 100}%`, top: `${pos.y * 100}%` }}
                  onPointerDown={(event) => onVertexPointerDown(id, event)}
                />
              );
            })}
        </>
      ) : (
        <>
          {(["top", "bottom"] as const).map((id) => {
            if (featherRadiusPx <= 0) return null;
            const seg = borderLineSegment(id, values, aspect);
            return (
              <svg
                key={`halo-${id}`} className="vignette-shape-stage__feather-halo"
                viewBox="0 0 1 1" preserveAspectRatio="none"
                style={{ filter: `blur(${featherRadiusPx / 4}px)` }}
              >
                <line
                  x1={seg.x1} y1={seg.y1} x2={seg.x2} y2={seg.y2} vectorEffect="non-scaling-stroke"
                  strokeWidth={featherRadiusPx} strokeLinecap="round"
                />
              </svg>
            );
          })}
          <svg className="vignette-shape-stage__outline" viewBox="0 0 1 1" preserveAspectRatio="none">
            {(() => {
              const c = centerLineSegment(values, aspect);
              return (
                <line
                  x1={c.x1} y1={c.y1} x2={c.x2} y2={c.y2}
                  className="vignette-shape-stage__center-line" vectorEffect="non-scaling-stroke"
                  strokeDasharray="5 4"
                />
              );
            })()}
          </svg>
          {(["top", "bottom"] as const).map((id) => {
            const seg = borderLineSegment(id, values, aspect);
            return (
              <svg key={id} className="vignette-shape-stage__outline" viewBox="0 0 1 1" preserveAspectRatio="none">
                {resizeActive && (
                  <line
                    x1={seg.x1} y1={seg.y1} x2={seg.x2} y2={seg.y2}
                    className="vignette-shape-stage__border-hit" vectorEffect="non-scaling-stroke"
                    onPointerDown={(event) => onBorderPointerDown(id, event)}
                  />
                )}
                <line
                  x1={seg.x1} y1={seg.y1} x2={seg.x2} y2={seg.y2}
                  className="vignette-shape-stage__border-line" vectorEffect="non-scaling-stroke"
                  pointerEvents="none"
                />
              </svg>
            );
          })}
        </>
      )}
      {activeTool === "rotation" && (
        <div ref={dialRef} className="vignette-shape-stage__dial" style={centerStyle}>
          <div className="vignette-shape-stage__dial-pointer" style={{ transform: `rotate(${values.rotation_angle}deg)` }}>
            <div className="vignette-shape-stage__dial-handle" onPointerDown={onDialPointerDown} />
            <div
              className="vignette-shape-stage__dial-angle-label"
              style={{ transform: `translate(-50%, -50%) rotate(${-values.rotation_angle}deg)` }}
            >
              {formatAngle(values.rotation_angle)}
            </div>
          </div>
        </div>
      )}
      <div
        className={`vignette-shape-stage__center${activeTool === "move" ? " vignette-shape-stage__center--active" : ""}`}
        style={centerStyle}
        onPointerDown={activeTool === "move" ? onCenterPointerDown : undefined}
      />
    </div>
  );
}

type VignetteShapeControlsProps = {
  activeTool: VignetteActiveTool | null;
  onToggleTool: (tool: VignetteActiveTool) => void;
};

/** Floating toolbar (Déplacer/Rotation/Redimensionner) -- a sibling of the zoomable viewport (not
inside it), so it stays fixed on screen while panning, same convention as SubjectMaskControls.
Mirrors Geometry's own toggle pattern (move/rotate/distort), but at most one tool active at a time
here (a single center handle can't move and rotate simultaneously) -- clicking the active tool
again turns it off. Resize (vertex/border) handles only show/respond while "resize" is selected,
same gating as Geometry's own distortion tool over its corner handles. */
export function VignetteShapeControls({ activeTool, onToggleTool }: VignetteShapeControlsProps) {
  return (
    <div className="vignette-shape-stage__controls">
      <button
        type="button"
        className={`vignette-shape-stage__tool-button${activeTool === "move" ? " vignette-shape-stage__tool-button--selected" : ""}`}
        onClick={() => onToggleTool("move")}
        title="Déplacer" aria-label="Déplacer" aria-pressed={activeTool === "move"}
      >
        <MoveToolIcon size={18} />
      </button>
      <button
        type="button"
        className={`vignette-shape-stage__tool-button${activeTool === "rotation" ? " vignette-shape-stage__tool-button--selected" : ""}`}
        onClick={() => onToggleTool("rotation")}
        title="Rotation" aria-label="Rotation" aria-pressed={activeTool === "rotation"}
      >
        <RotationToolIcon size={18} />
      </button>
      <button
        type="button"
        className={`vignette-shape-stage__tool-button${activeTool === "resize" ? " vignette-shape-stage__tool-button--selected" : ""}`}
        onClick={() => onToggleTool("resize")}
        title="Redimensionner" aria-label="Redimensionner" aria-pressed={activeTool === "resize"}
      >
        <ShapeToolIcon size={18} />
      </button>
    </div>
  );
}
