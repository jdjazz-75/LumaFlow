// LumaFlow v1.0 (2026-08-07)
// Stage d'édition géométrique : distorsion perspective à 4 coins, rotation via cadran et guides
// d'alignement (verticale/horizontale/grille 3x3) pour la correction Geometry.

import { forwardRef, useImperativeHandle, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import "./ZoomOverlay.css";
import "./GeometryCanvas.css";
import * as api from "../lib/api";
import { applyPerspective, solvePerspectiveCoefficients, type Point } from "../lib/geometryMath";
import { useFittedImageBox } from "../lib/useFittedImageBox";
import { usePanZones } from "../lib/usePanZones";
import type { ZoomBounds } from "../lib/zoomFit";
import { ZoomToolbar } from "./ZoomToolbar";
import {
  DistortionToolIcon,
  HorizontalLineGuideIcon,
  RotationToolIcon,
  ThirdsGuideIcon,
  VerticalLineGuideIcon,
} from "./icons";

// The interactive geometry-correction stage (rotation dial + free-form 4-corner perspective
// frame + alignment guides), extracted from GeometryCanvas.tsx so it can be reused both by
// Geometry's own dedicated Zoom screen (GeometryCanvas.tsx, unchanged from the user's point of
// view) AND embedded directly inside Film/Color Splash's own Zoom (ZoomOverlayGeneric in
// ZoomOverlay.tsx, feature: cross-row corrections) -- in the latter case corner/rotation edits
// are written onto Geometry's OWN pipeline step via the "auxiliary" zoom endpoints
// (api.setAuxiliaryZoomParameter) while the actually-open Zoom session stays on Film/Color
// Splash, which is why every backend write here goes through the generic `onCommitParameter`
// callback instead of calling api.setZoomParameter directly (unlike the pre-extraction version
// of this code).

const FRAME_AREA_FRACTION = 0.75; // must stay synced with lumaflow/addons/builtin/geometry.py's FRAME_AREA_FRACTION
const FRAME_MARGIN = (1 - Math.sqrt(FRAME_AREA_FRACTION)) / 2;
const CORNER_MINIMUM = -0.5; // mirrors geometry.py's _CORNER_MINIMUM
const CORNER_MAXIMUM = 1.5; // mirrors geometry.py's _CORNER_MAXIMUM
const ANGLE_LIMIT = 45; // mirrors geometry.py's _MINIMUM_ANGLE/_MAXIMUM_ANGLE

// PIL's Image.rotate(angle) is counter-clockwise-positive; the natural UI expectation is "drag the
// dial handle clockwise -> the photo visibly rotates clockwise" -- the opposite sense. Negating
// here reconciles the two (verified empirically via a Playwright screenshot check).
const ROTATION_SIGN = -1;

const BOWTIE_EPSILON = 0.02;

type CornerId = "tl" | "tr" | "br" | "bl";
type Quad = Record<CornerId, Point>;
type GuideAxis = "v" | "h";
type GuideId = "v" | "h" | "gv0" | "gv1" | "gh0" | "gh1";
type ToolKind = "rotation" | "distortion" | "v" | "h" | "grid";

const CORNER_ORDER: CornerId[] = ["tl", "tr", "br", "bl"];
const DEFAULT_QUAD: Quad = {
  tl: { x: FRAME_MARGIN, y: FRAME_MARGIN },
  tr: { x: 1 - FRAME_MARGIN, y: FRAME_MARGIN },
  br: { x: 1 - FRAME_MARGIN, y: 1 - FRAME_MARGIN },
  bl: { x: FRAME_MARGIN, y: 1 - FRAME_MARGIN },
};

const X_NEIGHBOR: Record<CornerId, CornerId> = { tl: "tr", tr: "tl", bl: "br", br: "bl" };
const Y_NEIGHBOR: Record<CornerId, CornerId> = { tl: "bl", bl: "tl", tr: "br", br: "tr" };
const IS_LEFT: Record<CornerId, boolean> = { tl: true, bl: true, tr: false, br: false };
const IS_TOP: Record<CornerId, boolean> = { tl: true, tr: true, bl: false, br: false };

const DEFAULT_GUIDE_LINE = 0.5;
const DEFAULT_GRID_DIVIDERS: [number, number] = [1 / 3, 2 / 3];

function clampCorner(id: CornerId, proposed: Point, quad: Quad): Point {
  let x = Math.min(Math.max(proposed.x, CORNER_MINIMUM), CORNER_MAXIMUM);
  let y = Math.min(Math.max(proposed.y, CORNER_MINIMUM), CORNER_MAXIMUM);
  const xNeighbor = quad[X_NEIGHBOR[id]].x;
  const yNeighbor = quad[Y_NEIGHBOR[id]].y;
  x = IS_LEFT[id] ? Math.min(x, xNeighbor - BOWTIE_EPSILON) : Math.max(x, xNeighbor + BOWTIE_EPSILON);
  y = IS_TOP[id] ? Math.min(y, yNeighbor - BOWTIE_EPSILON) : Math.max(y, yNeighbor + BOWTIE_EPSILON);
  return { x, y };
}

function frameLocalToPhoto(u: number, v: number): Point {
  const span = 1 - 2 * FRAME_MARGIN;
  return { x: FRAME_MARGIN + u * span, y: FRAME_MARGIN + v * span };
}

function photoToFrameLocal(point: Point): { u: number; v: number } {
  const span = 1 - 2 * FRAME_MARGIN;
  return { u: (point.x - FRAME_MARGIN) / span, v: (point.y - FRAME_MARGIN) / span };
}

function formatAngle(angle: number): string {
  return `${angle >= 0 ? "+" : ""}${angle.toFixed(1)}°`;
}

type DragTarget =
  | { kind: "corner"; id: CornerId }
  | { kind: "dial" }
  | { kind: "guide"; id: GuideId; axis: GuideAxis };

export type GeometryValues = {
  corner_tl_x: number; corner_tl_y: number;
  corner_tr_x: number; corner_tr_y: number;
  corner_br_x: number; corner_br_y: number;
  corner_bl_x: number; corner_bl_y: number;
  rotation_angle: number;
};

/** Builds a GeometryValues record from a flat {identifier: value} map (a ZoomSlider[]/
AuxiliaryZoomState sliders list reduced by identifier) -- shared by GeometryCanvas.tsx (its own
Zoom row) and ZoomOverlay.tsx's ZoomOverlayGeneric (Geometry read as an auxiliary row from within
Film/Color Splash's Zoom), so both seed GeometryToolStage from the exact same shape. */
export function geometryValuesFromById(byId: Record<string, number>): GeometryValues {
  return {
    corner_tl_x: byId.corner_tl_x ?? 0, corner_tl_y: byId.corner_tl_y ?? 0,
    corner_tr_x: byId.corner_tr_x ?? 1, corner_tr_y: byId.corner_tr_y ?? 0,
    corner_br_x: byId.corner_br_x ?? 1, corner_br_y: byId.corner_br_y ?? 1,
    corner_bl_x: byId.corner_bl_x ?? 0, corner_bl_y: byId.corner_bl_y ?? 1,
    rotation_angle: byId.rotation_angle ?? 0,
  };
}

function quadFromValues(values: GeometryValues): Quad {
  return {
    tl: { x: values.corner_tl_x, y: values.corner_tl_y },
    tr: { x: values.corner_tr_x, y: values.corner_tr_y },
    br: { x: values.corner_br_x, y: values.corner_br_y },
    bl: { x: values.corner_bl_x, y: values.corner_bl_y },
  };
}

export type GeometryToolStageHandle = {
  reset: () => void;
  /** Preloads a fresh full-resolution render (whatever /zoom/after currently resolves to for the
  session's actually-open Zoom row) and swaps it in as the stage's backdrop, WITHOUT closing the
  overlay -- the corner/rotation overlay stays visible on top since a geometric warp never changes
  the image's own pixel dimensions (unlike Cadrage's crop, see CropToolStage). */
  apply: () => Promise<void>;
};

type GeometryToolStageProps = {
  sessionId: string;
  photoSrc: string;
  initialValues: GeometryValues;
  defaultValues: GeometryValues;
  zoomBounds: ZoomBounds;
  onCommitParameter: (identifier: string, value: number) => void;
};

export const GeometryToolStage = forwardRef<GeometryToolStageHandle, GeometryToolStageProps>(
  function GeometryToolStage({ sessionId, photoSrc, initialValues, defaultValues, zoomBounds, onCommitParameter }, ref) {
    const fitted = useFittedImageBox(zoomBounds);
    const { renderPanZones } = usePanZones(fitted.viewportElRef, fitted.viewportSize, fitted.overflowsX, fitted.overflowsY);
    const [quad, setQuad] = useState<Quad>(() => quadFromValues(initialValues));
    const [uiAngleDeg, setUiAngleDeg] = useState(() => ROTATION_SIGN * initialValues.rotation_angle);
    const [displaySrc, setDisplaySrc] = useState(photoSrc);

    // Rotation/distortion auto-show if the seeded values are already non-neutral, so the user
    // immediately sees what's already applied; the 3 alignment aids are always opt-in.
    const [activeTools, setActiveTools] = useState<Set<ToolKind>>(() => {
      const next = new Set<ToolKind>();
      if (initialValues.rotation_angle !== 0) next.add("rotation");
      const quadIsNeutral = CORNER_ORDER.every(
        (id) => quadFromValues(initialValues)[id].x === DEFAULT_QUAD[id].x && quadFromValues(initialValues)[id].y === DEFAULT_QUAD[id].y,
      );
      if (!quadIsNeutral) next.add("distortion");
      return next;
    });
    const [guideV, setGuideV] = useState(DEFAULT_GUIDE_LINE);
    const [guideH, setGuideH] = useState(DEFAULT_GUIDE_LINE);
    const [gridV, setGridV] = useState<[number, number]>(DEFAULT_GRID_DIVIDERS);
    const [gridH, setGridH] = useState<[number, number]>(DEFAULT_GRID_DIVIDERS);

    function toggleTool(kind: ToolKind) {
      setActiveTools((current) => {
        const next = new Set(current);
        if (next.has(kind)) next.delete(kind);
        else next.add(kind);
        return next;
      });
    }

    const photoRef = useRef<HTMLDivElement>(null);
    const dialRef = useRef<HTMLDivElement>(null);
    const dragTarget = useRef<DragTarget | null>(null);
    const dragStartQuad = useRef<Quad>(quad);

    useImperativeHandle(ref, () => ({
      reset() {
        const defaultQuad = quadFromValues(defaultValues);
        setQuad(defaultQuad);
        setUiAngleDeg(ROTATION_SIGN * defaultValues.rotation_angle);
        setGuideV(DEFAULT_GUIDE_LINE);
        setGuideH(DEFAULT_GUIDE_LINE);
        setGridV(DEFAULT_GRID_DIVIDERS);
        setGridH(DEFAULT_GRID_DIVIDERS);
        setDisplaySrc(photoSrc);
        for (const id of CORNER_ORDER) {
          onCommitParameter(`corner_${id}_x`, defaultQuad[id].x);
          onCommitParameter(`corner_${id}_y`, defaultQuad[id].y);
        }
        onCommitParameter("rotation_angle", defaultValues.rotation_angle);
      },
      apply() {
        const url = `${api.zoomAfterUrl(sessionId)}?t=${Date.now()}`;
        return new Promise<void>((resolve, reject) => {
          const preload = new Image();
          preload.onload = () => {
            setDisplaySrc(url);
            resolve();
          };
          preload.onerror = () => reject(new Error("Échec du rendu de l'aperçu"));
          preload.src = url;
        });
      },
    }));

    function fractionFromPointer(event: ReactPointerEvent): Point | null {
      const rect = photoRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0 || rect.height === 0) return null;
      return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
    }

    function forwardCoefficients() {
      return solvePerspectiveCoefficients(
        CORNER_ORDER.map((id) => DEFAULT_QUAD[id]),
        CORNER_ORDER.map((id) => quad[id]),
      );
    }

    function inverseCoefficients() {
      return solvePerspectiveCoefficients(
        CORNER_ORDER.map((id) => quad[id]),
        CORNER_ORDER.map((id) => DEFAULT_QUAD[id]),
      );
    }

    function projectFramePoint(u: number, v: number): Point {
      const coeffs = forwardCoefficients();
      const source = frameLocalToPhoto(u, v);
      return coeffs ? applyPerspective(coeffs, source) : source;
    }

    function handleCornerPointerDown(id: CornerId, event: ReactPointerEvent<HTMLDivElement>) {
      event.stopPropagation();
      dragTarget.current = { kind: "corner", id };
      dragStartQuad.current = quad;
      event.currentTarget.setPointerCapture(event.pointerId);
    }

    function commitCorner(id: CornerId, point: Point) {
      onCommitParameter(`corner_${id}_x`, point.x);
      onCommitParameter(`corner_${id}_y`, point.y);
    }

    function handleDialPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
      event.stopPropagation();
      dragTarget.current = { kind: "dial" };
      event.currentTarget.setPointerCapture(event.pointerId);
    }

    function angleFromPointer(event: ReactPointerEvent): number | null {
      const rect = dialRef.current?.getBoundingClientRect();
      if (!rect) return null;
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const dx = event.clientX - centerX;
      const dy = event.clientY - centerY;
      const degrees = Math.atan2(dx, -dy) * (180 / Math.PI); // 0 = straight up, clockwise positive
      return Math.min(Math.max(degrees, -ANGLE_LIMIT), ANGLE_LIMIT);
    }

    function commitRotation(angle: number) {
      onCommitParameter("rotation_angle", ROTATION_SIGN * angle);
    }

    function handleGuidePointerDown(id: GuideId, axis: GuideAxis, event: ReactPointerEvent<SVGLineElement>) {
      event.stopPropagation();
      dragTarget.current = { kind: "guide", id, axis };
      event.currentTarget.setPointerCapture(event.pointerId);
    }

    function setGuideValue(id: GuideId, t: number) {
      const clamped = Math.min(Math.max(t, 0), 1);
      if (id === "v") setGuideV(clamped);
      else if (id === "h") setGuideH(clamped);
      else if (id === "gv0") setGridV(([, b]) => [clamped, b]);
      else if (id === "gv1") setGridV(([a]) => [a, clamped]);
      else if (id === "gh0") setGridH(([, b]) => [clamped, b]);
      else if (id === "gh1") setGridH(([a]) => [a, clamped]);
    }

    function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
      const target = dragTarget.current;
      if (!target) return;

      if (target.kind === "corner") {
        const point = fractionFromPointer(event);
        if (!point) return;
        const next = clampCorner(target.id, point, dragStartQuad.current);
        setQuad((current) => ({ ...current, [target.id]: next }));
        return;
      }

      if (target.kind === "dial") {
        const angle = angleFromPointer(event);
        if (angle !== null) setUiAngleDeg(angle);
        return;
      }

      const point = fractionFromPointer(event);
      if (!point) return;
      const coeffs = inverseCoefficients();
      if (!coeffs) return;
      const framePoint = applyPerspective(coeffs, point);
      const { u, v } = photoToFrameLocal(framePoint);
      setGuideValue(target.id, target.axis === "v" ? u : v);
    }

    function handlePointerUp() {
      const target = dragTarget.current;
      dragTarget.current = null;
      if (!target) return;
      if (target.kind === "corner") {
        setQuad((current) => {
          commitCorner(target.id, current[target.id]);
          return current;
        });
      } else if (target.kind === "dial") {
        setUiAngleDeg((current) => {
          commitRotation(current);
          return current;
        });
      }
      // guide drags are never committed to the backend -- ephemeral by design.
    }

    const quadPathD =
      `M ${quad.tl.x} ${quad.tl.y} L ${quad.tr.x} ${quad.tr.y} ` +
      `L ${quad.br.x} ${quad.br.y} L ${quad.bl.x} ${quad.bl.y} Z`;

    function guideEndpoints(axis: GuideAxis, t: number): [Point, Point] {
      return axis === "v" ? [projectFramePoint(t, 0), projectFramePoint(t, 1)] : [projectFramePoint(0, t), projectFramePoint(1, t)];
    }

    function renderGuide(id: GuideId, axis: GuideAxis, t: number) {
      const [p0, p1] = guideEndpoints(axis, t);
      return (
        <g key={id}>
          <line
            x1={p0.x} y1={p0.y} x2={p1.x} y2={p1.y}
            className="geometry-canvas__guide-line-hit"
            vectorEffect="non-scaling-stroke"
            onPointerDown={(event) => handleGuidePointerDown(id, axis, event)}
          />
          <line
            x1={p0.x} y1={p0.y} x2={p1.x} y2={p1.y}
            className="geometry-canvas__guide-line"
            vectorEffect="non-scaling-stroke"
            pointerEvents="none"
          />
        </g>
      );
    }

    return (
      <>
      <div className="geometry-canvas__stage">
        <div
          ref={fitted.viewportRef}
          className="geometry-canvas__viewport"
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
        <div
          ref={photoRef}
          className="geometry-canvas__photo-bounds"
          style={fitted.contentSize ? { width: fitted.contentSize.width, height: fitted.contentSize.height } : undefined}
        >
          {displaySrc && (
            <img
              src={displaySrc}
              alt=""
              className="geometry-canvas__photo"
              draggable={false}
              onLoad={fitted.handleImageLoad}
            />
          )}

          <svg className="geometry-canvas__overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
            {activeTools.has("distortion") && (
              <path className="geometry-canvas__quad-outline" d={quadPathD} vectorEffect="non-scaling-stroke" />
            )}
            {activeTools.has("grid") && renderGuide("gv0", "v", gridV[0])}
            {activeTools.has("grid") && renderGuide("gv1", "v", gridV[1])}
            {activeTools.has("grid") && renderGuide("gh0", "h", gridH[0])}
            {activeTools.has("grid") && renderGuide("gh1", "h", gridH[1])}
            {activeTools.has("v") && renderGuide("v", "v", guideV)}
            {activeTools.has("h") && renderGuide("h", "h", guideH)}
          </svg>

          {activeTools.has("distortion") &&
            CORNER_ORDER.map((id) => (
              <div
                key={id}
                className={`geometry-canvas__handle geometry-canvas__handle--${id}`}
                style={{ left: `${quad[id].x * 100}%`, top: `${quad[id].y * 100}%` }}
                onPointerDown={(event) => handleCornerPointerDown(id, event)}
              />
            ))}

          {activeTools.has("rotation") && (
            <div ref={dialRef} className="geometry-canvas__dial">
              <div className="geometry-canvas__dial-pointer" style={{ transform: `rotate(${uiAngleDeg}deg)` }}>
                <div className="geometry-canvas__dial-handle" onPointerDown={handleDialPointerDown} />
                <div
                  className="geometry-canvas__dial-angle-label"
                  style={{ transform: `translate(-50%, -50%) rotate(${-uiAngleDeg}deg)` }}
                >
                  {formatAngle(ROTATION_SIGN * uiAngleDeg)}
                </div>
              </div>
            </div>
          )}
        </div>
        </div>
        {renderPanZones()}

        <div className="geometry-canvas__guide-selector">
          <button
            type="button"
            className={`geometry-canvas__guide-button${activeTools.has("rotation") ? " geometry-canvas__guide-button--selected" : ""}`}
            onClick={() => toggleTool("rotation")}
            title="Rotation"
            aria-label="Rotation"
            aria-pressed={activeTools.has("rotation")}
          >
            <RotationToolIcon size={18} />
          </button>
          <button
            type="button"
            className={`geometry-canvas__guide-button${activeTools.has("distortion") ? " geometry-canvas__guide-button--selected" : ""}`}
            onClick={() => toggleTool("distortion")}
            title="Distorsion"
            aria-label="Distorsion"
            aria-pressed={activeTools.has("distortion")}
          >
            <DistortionToolIcon size={18} />
          </button>
          <div className="geometry-canvas__aid-toggles">
            <button
              type="button"
              className={`geometry-canvas__guide-button${activeTools.has("v") ? " geometry-canvas__guide-button--selected" : ""}`}
              onClick={() => toggleTool("v")}
              title="Ligne verticale"
              aria-label="Ligne verticale"
              aria-pressed={activeTools.has("v")}
            >
              <VerticalLineGuideIcon size={18} />
            </button>
            <button
              type="button"
              className={`geometry-canvas__guide-button${activeTools.has("h") ? " geometry-canvas__guide-button--selected" : ""}`}
              onClick={() => toggleTool("h")}
              title="Ligne horizontale"
              aria-label="Ligne horizontale"
              aria-pressed={activeTools.has("h")}
            >
              <HorizontalLineGuideIcon size={18} />
            </button>
            <button
              type="button"
              className={`geometry-canvas__guide-button${activeTools.has("grid") ? " geometry-canvas__guide-button--selected" : ""}`}
              onClick={() => toggleTool("grid")}
              title="Grille 3×3"
              aria-label="Grille 3×3"
              aria-pressed={activeTools.has("grid")}
            >
              <ThirdsGuideIcon size={18} />
            </button>
          </div>
        </div>
      </div>
      <ZoomToolbar
        zoomPercent={fitted.zoomPercent}
        zoomBounds={zoomBounds}
        onZoomIn={fitted.zoomIn}
        onZoomOut={fitted.zoomOut}
        onZoomChange={fitted.setZoomPercent}
        onFit={fitted.fit}
      />
      </>
    );
  },
);
