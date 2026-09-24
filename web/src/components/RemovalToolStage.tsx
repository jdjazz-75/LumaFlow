// LumaFlow v1.1 (2026-09-24)
// Scène d'édition Suppression d'objets (feature 100) : jusqu'à 4 zones (polygones) dessinées sur
// la photo SOURCE. Le panneau de contrôles (liste de zones à bascule, Marge, Fondu, Autre
// proposition) a été déplacé dans le panneau "Réglages manuels" de ZoomOverlay.tsx (revue
// d'ergonomie du 2026-09-24 -- il flottait auparavant par-dessus la photo et gênait le dessin des
// zones ; voir la mémoire object-removal-addon-planned) : cette scène ne rend plus que la photo et
// le contour de la zone active.

import { forwardRef, useImperativeHandle, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import "./ZoomOverlay.css";
import "./CropCanvas.css";
import "./SubjectMaskStage.css";
import "./RemovalToolStage.css";
import * as api from "../lib/api";
import { useFittedImageBox } from "../lib/useFittedImageBox";
import { usePanZones } from "../lib/usePanZones";
import type { ZoomBounds } from "../lib/zoomFit";
import { ZoomToolbar } from "./ZoomToolbar";
import { t } from "../i18n";
import { MAX_MASK_VERTICES, MIN_MASK_VERTICES, clampMaskFraction, type MaskPoint } from "../lib/removalZones";
import type { UseRemovalZones } from "../lib/useRemovalZones";

// Extracted from ZoomOverlay.tsx's embedded-correction pattern (GeometryToolStage/CropToolStage):
// same forwardRef {reset, apply} shape, same useFittedImageBox/usePanZones/ZoomToolbar primitives
// for JS-computed image fitting (wrapper == image pixel equality is an established invariant --
// never attempt a CSS-only fit here, see zoom-fitted-image-box-shared-hook). Unlike Crop/Geometry,
// commits go through the BATCHED auxiliary endpoint (up to 4 zones x 65 keys), so this stage talks
// to `useRemovalZones`'s own commit-shaped actions rather than a per-field `onCommitParameter`.
//
// The background photo is the SOURCE (removal runs first in the pipeline, before Geometry/Framing)
// -- deliberate, not a bug; zones are defined in source coordinates so a later crop/rotation never
// shifts them. ZoomOverlay.tsx's panel surfaces that as a plain hint.

export type RemovalToolStageHandle = {
  reset: () => void;
  apply: () => Promise<void>;
};

type RemovalToolStageProps = {
  sessionId: string;
  photoSrc: string;
  imageSize: { width: number; height: number } | null;
  zoomBounds: ZoomBounds;
  zones: UseRemovalZones;
  busy: boolean;
};

export const RemovalToolStage = forwardRef<RemovalToolStageHandle, RemovalToolStageProps>(function RemovalToolStage(
  // `imageSize` is accepted (mirrors CropToolStage's own prop shape) but not currently read here --
  // Marge/Fondu are previewed only via the zone's own outline/fill for now, not yet as a
  // real-pixel-accurate stroke width; kept in the type for API parity and a future enhancement.
  { sessionId, photoSrc, zoomBounds, zones, busy },
  ref,
) {
  const fitted = useFittedImageBox(zoomBounds);
  const { renderPanZones } = usePanZones(fitted.viewportElRef, fitted.viewportSize, fitted.overflowsX, fitted.overflowsY);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const photoRef = useRef<HTMLDivElement>(null);
  const dragVertex = useRef<{ zoneIndex: number; vertexIndex: number } | null>(null);

  function runApply(): Promise<void> {
    const url = `${api.auxiliaryZoomAfterUrl(sessionId, "removal")}?t=${Date.now()}`;
    return new Promise<void>((resolve, reject) => {
      const preload = new Image();
      preload.onload = () => {
        setPreviewSrc(url);
        resolve();
      };
      preload.onerror = () => reject(new Error(t("error.preview_render_failed")));
      preload.src = url;
    });
  }

  useImperativeHandle(ref, () => ({
    reset() {
      setPreviewSrc(null);
      zones.resetAll();
    },
    apply: runApply,
  }));

  function fractionFromPointer(event: ReactPointerEvent): MaskPoint | null {
    const rect = photoRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    return {
      x: clampMaskFraction((event.clientX - rect.left) / rect.width),
      y: clampMaskFraction((event.clientY - rect.top) / rect.height),
    };
  }

  function handleVertexPointerDown(zoneIndex: number, vertexIndex: number, event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    zones.selectZone(zoneIndex);
    dragVertex.current = { zoneIndex, vertexIndex };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleMidpointPointerDown(zoneIndex: number, edgeIndex: number, event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    zones.selectZone(zoneIndex);
    const insertedIndex = zones.insertZoneMidpoint(zoneIndex, edgeIndex);
    dragVertex.current = { zoneIndex, vertexIndex: insertedIndex };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragVertex.current;
    if (!drag) return;
    const point = fractionFromPointer(event);
    if (!point) return;
    const points = zones.values.zones[drag.zoneIndex] ?? [];
    const next = points.map((p, i) => (i === drag.vertexIndex ? point : p));
    zones.setZonePointsLive(drag.zoneIndex, next);
  }

  function handlePointerUp() {
    const drag = dragVertex.current;
    if (!drag) return;
    dragVertex.current = null;
    zones.commitZonePoints(drag.zoneIndex, zones.values.zones[drag.zoneIndex] ?? []);
  }

  function handleVertexDoubleClick(zoneIndex: number, vertexIndex: number) {
    zones.removeZoneVertex(zoneIndex, vertexIndex);
  }

  function handleZoneFillClick(zoneIndex: number) {
    zones.selectZone(zoneIndex);
  }

  if (previewSrc) {
    return (
      <div className="crop-canvas__stage crop-canvas__stage--preview" onClick={() => setPreviewSrc(null)}>
        <img src={previewSrc} alt="" className="crop-canvas__preview-photo" draggable={false} />
        <div className="crop-canvas__preview-badge">{t("ui.removal.preview_badge")}</div>
      </div>
    );
  }

  const hasAnyZone = zones.values.zones.some((points) => points.length >= MIN_MASK_VERTICES);

  return (
    <>
      <div className="crop-canvas__stage removal-stage">
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
              <img src={photoSrc} alt="" className="crop-canvas__photo" draggable={false} onLoad={fitted.handleImageLoad} />
            )}
            {zones.values.zones.map((points, zoneIndex) => {
              if (points.length < MIN_MASK_VERTICES) return null;
              const active = zones.activeZoneIndex === zoneIndex;
              const path = `M ${points.map((p) => `${p.x} ${p.y}`).join(" L ")} Z`;
              return (
                <svg
                  key={zoneIndex}
                  className={`removal-stage__zone${active ? " removal-stage__zone--active" : ""}`}
                  viewBox="0 0 1 1"
                  preserveAspectRatio="none"
                  onPointerDown={() => handleZoneFillClick(zoneIndex)}
                >
                  <path d={path} vectorEffect="non-scaling-stroke" />
                </svg>
              );
            })}
            {zones.activeZoneIndex !== null && (zones.values.zones[zones.activeZoneIndex]?.length ?? 0) >= MIN_MASK_VERTICES && (
              <>
                {zones.values.zones[zones.activeZoneIndex].map((point, vertexIndex) => (
                  <div
                    key={vertexIndex}
                    className="subject-mask-stage__vertex removal-stage__vertex"
                    style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }}
                    onPointerDown={(event) => handleVertexPointerDown(zones.activeZoneIndex as number, vertexIndex, event)}
                    onDoubleClick={() => handleVertexDoubleClick(zones.activeZoneIndex as number, vertexIndex)}
                  />
                ))}
                {zones.values.zones[zones.activeZoneIndex].length < MAX_MASK_VERTICES &&
                  zones.values.zones[zones.activeZoneIndex].map((point, edgeIndex) => {
                    const activePoints = zones.values.zones[zones.activeZoneIndex as number];
                    const next = activePoints[(edgeIndex + 1) % activePoints.length];
                    const mx = (point.x + next.x) / 2;
                    const my = (point.y + next.y) / 2;
                    return (
                      <div
                        key={`mid-${edgeIndex}`}
                        className="subject-mask-stage__midpoint"
                        style={{ left: `${mx * 100}%`, top: `${my * 100}%` }}
                        onPointerDown={(event) => handleMidpointPointerDown(zones.activeZoneIndex as number, edgeIndex, event)}
                      >
                        +
                      </div>
                    );
                  })}
              </>
            )}
          </div>
        </div>
        {renderPanZones()}
        {!hasAnyZone && <div className="removal-stage__hint">{t("ui.removal.empty_hint")}</div>}
        {busy && (
          <div className="removal-stage__busy">
            <span>{t("ui.removal.computing")}</span>
          </div>
        )}
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
