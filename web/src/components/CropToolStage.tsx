// LumaFlow v1.0 (2026-08-07)
// Stage d'édition du recadrage libre (Framing) : cadre/poignées déplaçables, guides de composition
// (règle des tiers, spirale d'or, etc.), verrouillage de ratio et aperçu du rendu recadré.

import { forwardRef, useImperativeHandle, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactElement } from "react";
import "./ZoomOverlay.css";
import "./CropCanvas.css";
import * as api from "../lib/api";
import type { ZoomOverlay } from "../lib/api";
import { guideShapes, MIRROR_CAPABLE_GUIDE_KINDS, type Mirror } from "../lib/cropGuides";
import { useFittedImageBox } from "../lib/useFittedImageBox";
import { usePanZones } from "../lib/usePanZones";
import type { ZoomBounds } from "../lib/zoomFit";
import { ZoomToolbar } from "./ZoomToolbar";
import {
  ThirdsGuideIcon,
  GoldenSectionGuideIcon,
  GoldenTrianglesGuideIcon,
  GoldenSpiralGuideIcon,
  CenterLinesGuideIcon,
  DiagonalGuideIcon,
  PyramidGuideIcon,
  CompoundCurveGuideIcon,
  MirrorHorizontalIcon,
  MirrorVerticalIcon,
} from "./icons";

// Free-form crop frame, extracted from CropCanvas.tsx so it can be reused both by Framing's own
// dedicated Zoom screen (CropCanvas.tsx, unchanged from the user's point of view) AND embedded
// directly inside Film/Color Splash's own Zoom (ZoomOverlay.tsx's ZoomOverlayGeneric, feature:
// cross-row corrections) -- in the latter case crop edits are written onto Framing's OWN pipeline
// step via the "auxiliary" zoom endpoints (api.setAuxiliaryZoomParameter) while the actually-open
// Zoom session stays on Film/Color Splash, which is why every backend write here goes through the
// generic `onCommitParameter` callback instead of calling api.setZoomParameter directly (unlike
// the pre-extraction version of this code).

const MINIMUM_SIZE = 0.05; // mirrors lumaflow/addons/builtin/framing.py's _MINIMUM_SIZE

type CropBox = { x: number; y: number; width: number; height: number };
type HandleId = "move" | "n" | "s" | "e" | "w" | "nw" | "ne" | "sw" | "se";

const HANDLES: HandleId[] = ["nw", "n", "ne", "w", "e", "sw", "s", "se"];

const GUIDE_ICONS: Record<string, (props: { size?: number }) => ReactElement> = {
  thirds: ThirdsGuideIcon,
  golden_section: GoldenSectionGuideIcon,
  golden_triangles: GoldenTrianglesGuideIcon,
  golden_spiral: GoldenSpiralGuideIcon,
  center_lines: CenterLinesGuideIcon,
  diagonal: DiagonalGuideIcon,
  pyramid: PyramidGuideIcon,
  compound_curve: CompoundCurveGuideIcon,
};

const NO_MIRROR: Mirror = { flipX: false, flipY: false };

function clampBox(box: CropBox): CropBox {
  let { x, y, width, height } = box;
  width = Math.min(Math.max(width, MINIMUM_SIZE), 1);
  height = Math.min(Math.max(height, MINIMUM_SIZE), 1);
  x = Math.min(Math.max(x, 0), 1 - width);
  y = Math.min(Math.max(y, 0), 1 - height);
  return { x, y, width, height };
}

// Golden Spiral aspect-ratio lock (2026-08-07): the whirling-squares construction cropGuides.ts's
// goldenSpiral() draws only reads as an actual spiral within a narrow band around the golden ratio
// itself -- everywhere else in the crop range it renders a single notched arc or a fan of same-
// size arcs (see the guide's own comments). Rather than tolerate that, the crop box's aspect ratio
// is locked to PHI (or 1/PHI for a portrait crop) for as long as Golden Spiral is the active guide,
// so the drawn guide is always a true spiral -- this section owns that lock's geometry; none of it
// applies to any other guide kind.
const PHI = (1 + Math.sqrt(5)) / 2;

function nativeImageRatio(imageSize: { width: number; height: number } | null): number {
  return imageSize && imageSize.height > 0 ? imageSize.width / imageSize.height : 1;
}

/** The cropBox.width/height fraction that makes the crop's REAL pixel aspect ratio equal
`realRatio`, given the photo's own native pixel dimensions (frameAspectRatio below mixes cropBox
fractions with imageSize the same way, in the other direction). */
function boxRatioForReal(realRatio: number, imageSize: { width: number; height: number } | null): number {
  return realRatio / nativeImageRatio(imageSize);
}

/** Picks whichever of the two golden-ratio orientations (landscape PHI, portrait 1/PHI) is closer
-- compared in log space, since aspect ratios compose multiplicatively -- to the crop box's CURRENT
fractional ratio. Called once, when Golden Spiral is activated, so a landscape crop locks to
landscape golden and a portrait crop locks to portrait golden, instead of always snapping to one
orientation regardless of what the user already had. */
function pickGoldenBoxRatio(currentBoxRatio: number, imageSize: { width: number; height: number } | null): number {
  const landscape = boxRatioForReal(PHI, imageSize);
  const portrait = boxRatioForReal(1 / PHI, imageSize);
  const logCurrent = Math.log(currentBoxRatio);
  return Math.abs(logCurrent - Math.log(landscape)) <= Math.abs(logCurrent - Math.log(portrait)) ? landscape : portrait;
}

/** Clamps `width` (and its ratio-derived height) to [MINIMUM_SIZE, 1] on both axes WITHOUT
breaking `boxRatio` -- unlike clampBox's independent per-axis clamp, which would. Every caller
already has a ratio-consistent (width, height) pair, so only `width` is needed; height is always
re-derived from it via `boxRatio` rather than accepted separately. */
function clampSizeToRatio(width: number, boxRatio: number): { width: number; height: number } {
  let w = Math.min(Math.max(width, MINIMUM_SIZE), 1);
  let h = w / boxRatio;
  if (h < MINIMUM_SIZE) {
    h = MINIMUM_SIZE;
    w = h * boxRatio;
  } else if (h > 1) {
    h = 1;
    w = h * boxRatio;
  }
  w = Math.min(Math.max(w, MINIMUM_SIZE), 1);
  h = w / boxRatio;
  return { width: w, height: h };
}

/** Resizes `box` to exactly `boxRatio`, preserving its area and center as closely as the frame's
bounds allow -- used once, right when Golden Spiral is selected, so the guide is already a correct
spiral before the user touches a handle. */
function snapBoxToRatio(box: CropBox, boxRatio: number): CropBox {
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  const area = box.width * box.height;
  const width = Math.sqrt(area * boxRatio);
  const sized = clampSizeToRatio(width, boxRatio);
  return clampBox({ x: cx - sized.width / 2, y: cy - sized.height / 2, width: sized.width, height: sized.height });
}

/** Of the two raw (unlocked) sizes a corner drag implies -- one driven by how far the pointer
moved horizontally, one by how far it moved vertically -- picks whichever is LARGER once the other
dimension is derived from `boxRatio`, so the box keeps following the pointer's dominant direction
instead of shrinking to whichever axis moved least. */
function sizeFromDominantAxis(rawWidth: number, rawHeight: number, boxRatio: number): { width: number; height: number } {
  const width = rawWidth;
  const height = rawWidth / boxRatio;
  const widthAlt = rawHeight * boxRatio;
  const heightAlt = rawHeight;
  return width >= widthAlt ? { width, height } : { width: widthAlt, height: heightAlt };
}

/** Corner-handle resize under the ratio lock: the corner DIAGONALLY OPPOSITE the dragged one stays
fixed; size is derived from the dominant drag axis and `boxRatio`, then the box is rebuilt growing
from the fixed corner toward the dragged one. */
function ratioLockedCornerResize(
  fixedX: number, fixedY: number,
  rawWidth: number, rawHeight: number,
  growRight: boolean, growDown: boolean,
  boxRatio: number,
): CropBox {
  const dominant = sizeFromDominantAxis(Math.max(rawWidth, MINIMUM_SIZE), Math.max(rawHeight, MINIMUM_SIZE), boxRatio);
  const { width, height } = clampSizeToRatio(dominant.width, boxRatio);
  const x = growRight ? fixedX : fixedX - width;
  const y = growDown ? fixedY : fixedY - height;
  return clampBox({ x, y, width, height });
}

/** Edge-handle resize under the ratio lock: only ONE dimension is user-driven (the axis the
handle sits on); the other is derived from `boxRatio` and the box grows/shrinks symmetrically
around its own current center, since a single-edge handle has no "opposite edge" to anchor the
cross axis to. */
function ratioLockedEdgeResize(
  centerX: number, centerY: number,
  drivenDimension: "width" | "height", drivenValue: number,
  boxRatio: number,
): CropBox {
  const width = drivenDimension === "width" ? drivenValue : drivenValue * boxRatio;
  const sized = clampSizeToRatio(Math.max(width, MINIMUM_SIZE), boxRatio);
  return clampBox({ x: centerX - sized.width / 2, y: centerY - sized.height / 2, width: sized.width, height: sized.height });
}

/** Dispatches a resize-handle drag to the corner or edge variant above. `handle` is never "move"
here (the caller already special-cases that). */
function ratioLockedResize(handle: HandleId, start: CropBox, dx: number, dy: number, boxRatio: number): CropBox {
  const isCorner = handle.length === 2;
  if (isCorner) {
    const growRight = handle.includes("e");
    const growDown = handle.includes("s");
    const fixedX = growRight ? start.x : start.x + start.width;
    const fixedY = growDown ? start.y : start.y + start.height;
    const rawWidth = growRight ? start.width + dx : start.width - dx;
    const rawHeight = growDown ? start.height + dy : start.height - dy;
    return ratioLockedCornerResize(fixedX, fixedY, rawWidth, rawHeight, growRight, growDown, boxRatio);
  }
  const centerX = start.x + start.width / 2;
  const centerY = start.y + start.height / 2;
  if (handle === "n") return ratioLockedEdgeResize(centerX, centerY, "height", start.height - dy, boxRatio);
  if (handle === "s") return ratioLockedEdgeResize(centerX, centerY, "height", start.height + dy, boxRatio);
  if (handle === "w") return ratioLockedEdgeResize(centerX, centerY, "width", start.width - dx, boxRatio);
  return ratioLockedEdgeResize(centerX, centerY, "width", start.width + dx, boxRatio); // "e"
}

export type CropValues = { crop_x: number; crop_y: number; crop_width: number; crop_height: number };

/** Builds a CropValues record from a flat {identifier: value} map -- shared by CropCanvas.tsx
(its own Zoom row) and ZoomOverlay.tsx's ZoomOverlayGeneric (Framing read as an auxiliary row from
within Film/Color Splash's Zoom), so both seed CropToolStage from the exact same shape. */
export function cropValuesFromById(byId: Record<string, number>): CropValues {
  return {
    crop_x: byId.crop_x ?? 0, crop_y: byId.crop_y ?? 0,
    crop_width: byId.crop_width ?? 1, crop_height: byId.crop_height ?? 1,
  };
}

function boxFromValues(values: CropValues): CropBox {
  return clampBox({ x: values.crop_x, y: values.crop_y, width: values.crop_width, height: values.crop_height });
}

export type CropToolStageHandle = {
  reset: () => void;
  /** Preloads a fresh full-resolution render (whatever /zoom/after currently resolves to for the
  session's actually-open Zoom row) and switches to a distraction-free preview of it, hiding the
  edit frame -- unlike GeometryToolStage's apply(), the frame/handle coordinates (fractions of the
  ORIGINAL uncropped photo) would no longer line up once the crop actually shrinks the image, so
  they can't stay overlaid on the new render. Clicking the preview resumes editing. */
  apply: () => Promise<void>;
};

type CropToolStageProps = {
  sessionId: string;
  photoSrc: string;
  imageSize: { width: number; height: number } | null;
  initialValues: CropValues;
  defaultValues: CropValues;
  overlays: ZoomOverlay[];
  zoomBounds: ZoomBounds;
  onCommitParameter: (identifier: string, value: number) => void;
};

export const CropToolStage = forwardRef<CropToolStageHandle, CropToolStageProps>(function CropToolStage(
  { sessionId, photoSrc, imageSize, initialValues, defaultValues, overlays, zoomBounds, onCommitParameter },
  ref,
) {
  const fitted = useFittedImageBox(zoomBounds);
  const { renderPanZones } = usePanZones(fitted.viewportElRef, fitted.viewportSize, fitted.overflowsX, fitted.overflowsY);
  const [cropBox, setCropBox] = useState<CropBox>(() => boxFromValues(initialValues));
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [activeGuideKind, setActiveGuideKind] = useState<string | null>(
    () => overlays.find((o) => o.default_active)?.kind ?? null,
  );
  // Shared by the 3 orientation-sensitive guides (Golden Triangles/Spiral/Compound Curve) rather
  // than remembered per-guide -- switching between them keeps whatever mirror is currently set.
  const [mirror, setMirror] = useState<Mirror>(NO_MIRROR);
  // Golden Spiral's crop-ratio lock (see the geometry helpers above `clampBox`) -- non-null only
  // while activeGuideKind === "golden_spiral", set once at activation (not derived from cropBox on
  // every render) so it stays stable across a drag instead of drifting with cropBox's momentary
  // ratio.
  const [lockedBoxRatio, setLockedBoxRatio] = useState<number | null>(null);

  const stageRef = useRef<HTMLDivElement>(null);
  // The stage letterboxes the photo (it rarely matches the stage's own box aspect ratio) --
  // cropBox fractions, drag math, and guide geometry must all be relative to the photo's own
  // rendered bounds, not the stage's.
  const photoRef = useRef<HTMLDivElement>(null);
  const dragHandle = useRef<HandleId | null>(null);
  const dragStart = useRef<{ pointerX: number; pointerY: number; box: CropBox } | null>(null);

  useImperativeHandle(ref, () => ({
    reset() {
      const base = boxFromValues(defaultValues);
      // Keeps re-applying the already-chosen golden-ratio lock (orientation included) if Golden
      // Spiral is still the active guide -- otherwise Réinitialiser would silently hand back a
      // non-golden-ratio crop and break the guide again, the same class of bug this whole lock
      // exists to prevent.
      const next = lockedBoxRatio !== null ? snapBoxToRatio(base, lockedBoxRatio) : base;
      setCropBox(next);
      setPreviewSrc(null);
      onCommitParameter("crop_x", next.x);
      onCommitParameter("crop_y", next.y);
      onCommitParameter("crop_width", next.width);
      onCommitParameter("crop_height", next.height);
    },
    apply() {
      const url = `${api.zoomAfterUrl(sessionId)}?t=${Date.now()}`;
      return new Promise<void>((resolve, reject) => {
        const preload = new Image();
        preload.onload = () => {
          setPreviewSrc(url);
          resolve();
        };
        preload.onerror = () => reject(new Error("Échec du rendu de l'aperçu"));
        preload.src = url;
      });
    },
  }));

  function fractionFromPointer(event: ReactPointerEvent): { fx: number; fy: number } | null {
    const rect = photoRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    return { fx: (event.clientX - rect.left) / rect.width, fy: (event.clientY - rect.top) / rect.height };
  }

  function handlePointerDown(handle: HandleId, event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    const point = fractionFromPointer(event);
    if (!point) return;
    dragHandle.current = handle;
    dragStart.current = { pointerX: point.fx, pointerY: point.fy, box: cropBox };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const handle = dragHandle.current;
    const start = dragStart.current;
    if (!handle || !start) return;
    const point = fractionFromPointer(event);
    if (!point) return;
    const dx = point.fx - start.pointerX;
    const dy = point.fy - start.pointerY;

    if (handle === "move") {
      const x = Math.min(Math.max(start.box.x + dx, 0), 1 - start.box.width);
      const y = Math.min(Math.max(start.box.y + dy, 0), 1 - start.box.height);
      setCropBox({ ...start.box, x, y });
      return;
    }

    if (lockedBoxRatio !== null) {
      setCropBox(ratioLockedResize(handle, start.box, dx, dy, lockedBoxRatio));
      return;
    }

    const next: CropBox = { ...start.box };
    if (handle.includes("w")) {
      next.x = start.box.x + dx;
      next.width = start.box.width - dx;
    }
    if (handle.includes("e")) {
      next.width = start.box.width + dx;
    }
    if (handle.includes("n")) {
      next.y = start.box.y + dy;
      next.height = start.box.height - dy;
    }
    if (handle.includes("s")) {
      next.height = start.box.height + dy;
    }
    setCropBox(clampBox(next));
  }

  function commitCropBox(box: CropBox) {
    onCommitParameter("crop_x", box.x);
    onCommitParameter("crop_y", box.y);
    onCommitParameter("crop_width", box.width);
    onCommitParameter("crop_height", box.height);
  }

  function handlePointerUp() {
    if (!dragHandle.current) return;
    dragHandle.current = null;
    dragStart.current = null;
    commitCropBox(cropBox);
  }

  function toggleGuide(kind: string) {
    const next = activeGuideKind === kind ? null : kind;
    if (next === "golden_spiral") {
      // Snap-and-commit immediately (not just a visual preview) so the drawn spiral always matches
      // an actually-applied crop, even before the user touches a handle -- same principle as
      // reset() above committing right away instead of waiting for a drag.
      const boxRatio = pickGoldenBoxRatio(cropBox.width / cropBox.height, imageSize);
      const snapped = snapBoxToRatio(cropBox, boxRatio);
      setLockedBoxRatio(boxRatio);
      setCropBox(snapped);
      commitCropBox(snapped);
    } else {
      setLockedBoxRatio(null);
    }
    setActiveGuideKind(next);
  }

  const frameAspectRatio =
    imageSize && cropBox.height > 0
      ? (cropBox.width * imageSize.width) / (cropBox.height * imageSize.height)
      : 1;
  const maskPath =
    `M0 0H1V1H0Z ` +
    `M${cropBox.x} ${cropBox.y}H${cropBox.x + cropBox.width}V${cropBox.y + cropBox.height}H${cropBox.x}Z`;

  if (previewSrc) {
    return (
      <div className="crop-canvas__stage crop-canvas__stage--preview" onClick={() => setPreviewSrc(null)}>
        <img src={previewSrc} alt="" className="crop-canvas__preview-photo" draggable={false} />
        <div className="crop-canvas__preview-badge">Aperçu du recadrage · cliquer pour reprendre l'édition</div>
      </div>
    );
  }

  return (
    <>
    <div ref={stageRef} className="crop-canvas__stage">
      <div
        ref={fitted.viewportRef}
        className="crop-canvas__viewport"
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
      <div
        ref={photoRef}
        className="crop-canvas__photo-bounds"
        style={fitted.contentSize ? { width: fitted.contentSize.width, height: fitted.contentSize.height } : undefined}
      >
        {photoSrc && (
          <img
            src={photoSrc}
            alt=""
            className="crop-canvas__photo"
            draggable={false}
            onLoad={fitted.handleImageLoad}
          />
        )}
        <svg className="crop-canvas__mask" viewBox="0 0 1 1" preserveAspectRatio="none">
          <path fillRule="evenodd" d={maskPath} />
        </svg>
        <div
          className="crop-canvas__frame"
          style={{
            left: `${cropBox.x * 100}%`, top: `${cropBox.y * 100}%`,
            width: `${cropBox.width * 100}%`, height: `${cropBox.height * 100}%`,
          }}
          onPointerDown={(event) => handlePointerDown("move", event)}
        >
          {activeGuideKind && (
            <svg className="crop-canvas__guides" viewBox="0 0 1 1" preserveAspectRatio="none">
              {guideShapes(activeGuideKind, frameAspectRatio, mirror).map((shape, index) =>
                shape.type === "line" ? (
                  <line
                    key={index} x1={shape.x1} y1={shape.y1} x2={shape.x2} y2={shape.y2}
                    vectorEffect="non-scaling-stroke"
                  />
                ) : (
                  <path key={index} d={shape.d} fill="none" vectorEffect="non-scaling-stroke" />
                ),
              )}
            </svg>
          )}
          {HANDLES.map((handle) => (
            <div
              key={handle}
              className={`crop-canvas__handle crop-canvas__handle--${handle}`}
              onPointerDown={(event) => handlePointerDown(handle, event)}
            />
          ))}
        </div>
      </div>
      </div>
      {renderPanZones()}
      <div className="crop-canvas__guide-selector">
        {overlays.map((overlay) => {
          const Icon = GUIDE_ICONS[overlay.kind];
          if (!Icon) return null;
          const selected = activeGuideKind === overlay.kind;
          return (
            <button
              key={overlay.kind}
              type="button"
              className={`crop-canvas__guide-button${selected ? " crop-canvas__guide-button--selected" : ""}`}
              onClick={() => toggleGuide(overlay.kind)}
              title={overlay.label}
              aria-label={overlay.label}
            >
              <Icon size={18} />
            </button>
          );
        })}
        {activeGuideKind && MIRROR_CAPABLE_GUIDE_KINDS.includes(activeGuideKind) && (
          <div className="crop-canvas__mirror-toggles">
            <button
              type="button"
              className={`crop-canvas__guide-button${mirror.flipX ? " crop-canvas__guide-button--selected" : ""}`}
              onClick={() => setMirror((m) => ({ ...m, flipX: !m.flipX }))}
              aria-label="Miroir horizontal"
              title="Miroir horizontal"
              aria-pressed={mirror.flipX}
            >
              <MirrorHorizontalIcon size={14} />
            </button>
            <button
              type="button"
              className={`crop-canvas__guide-button${mirror.flipY ? " crop-canvas__guide-button--selected" : ""}`}
              onClick={() => setMirror((m) => ({ ...m, flipY: !m.flipY }))}
              aria-label="Miroir vertical"
              title="Miroir vertical"
              aria-pressed={mirror.flipY}
            >
              <MirrorVerticalIcon size={14} />
            </button>
          </div>
        )}
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
});
