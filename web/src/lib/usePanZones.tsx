// LumaFlow v1.0 (2026-08-07)
// Hook React fournissant les 8 zones de pan cliquer-maintenir (bords + coins) autour d'un
// viewport zoomable, réutilisé par les stages Geometry/Cadrage/Masque Sujet.
import { useRef, type CSSProperties, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

// Mirrors ZoomOverlay.tsx's own pan-zone constants exactly (feature 038 zoom optique, 2026-07-24).
const PAN_ZONE_TICK_FRACTION = 0.1;
const PAN_ZONE_THICKNESS_PX = 4;
const PAN_SPEED_PX_PER_FRAME = 14;

/**
 * 8 amber click-and-hold tick marks (4 edges + 4 L-bracket corners) around a scrollable viewport --
 * a click-and-hold alternative to scroll-to-pan, added after a user reported being unable to use
 * the scroll gesture (2026-07-24). Extracted from ZoomOverlay.tsx (2026-07-31) so Geometry/Cadrage's
 * newly-added zoomable stages reuse this exact, already-proven mechanism -- chosen specifically
 * because it doesn't compete with Geometry's/Cadrage's own click-drag corner/handle gestures (the
 * ticks sit outside the photo, at the viewport's own edges), unlike a generic click-drag-to-pan
 * would. See memory zoom-optical-pan-zones. ZoomOverlay.tsx's own main-compare-pane pan zones keep
 * their original, separate implementation (not migrated to this hook) to avoid touching
 * already-verified-working code while fixing this bug class -- see plan v2's rationale.
 */
export function usePanZones(
  scrollRef: RefObject<HTMLElement | null>,
  viewportSize: { width: number; height: number } | null,
  overflowsX: boolean,
  overflowsY: boolean,
) {
  const panDirectionRef = useRef<{ dx: number; dy: number } | null>(null);
  const panFrameRef = useRef<number | null>(null);

  function panStep() {
    const el = scrollRef.current;
    const direction = panDirectionRef.current;
    if (!el || !direction) {
      panFrameRef.current = null;
      return;
    }
    el.scrollLeft += direction.dx * PAN_SPEED_PX_PER_FRAME;
    el.scrollTop += direction.dy * PAN_SPEED_PX_PER_FRAME;
    panFrameRef.current = requestAnimationFrame(panStep);
  }

  function handlePanZonePointerDown(event: ReactPointerEvent<HTMLDivElement>, dx: number, dy: number) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panDirectionRef.current = { dx, dy };
    if (panFrameRef.current === null) panFrameRef.current = requestAnimationFrame(panStep);
  }

  function stopPanZone() {
    panDirectionRef.current = null;
    if (panFrameRef.current !== null) {
      cancelAnimationFrame(panFrameRef.current);
      panFrameRef.current = null;
    }
  }

  function renderPanZones() {
    if (!viewportSize || (!overflowsX && !overflowsY)) return null;
    const len = viewportSize.height * PAN_ZONE_TICK_FRACTION;
    const t = PAN_ZONE_THICKNESS_PX;
    const zones: Array<{
      key: string;
      dx: number;
      dy: number;
      cursor: string;
      visible: boolean;
      ticks: Array<CSSProperties>;
    }> = [
      { key: "up", dx: 0, dy: -1, cursor: "n-resize", visible: overflowsY,
        ticks: [{ top: 0, left: "50%", transform: "translateX(-50%)", width: len, height: t }] },
      { key: "down", dx: 0, dy: 1, cursor: "s-resize", visible: overflowsY,
        ticks: [{ bottom: 0, left: "50%", transform: "translateX(-50%)", width: len, height: t }] },
      { key: "left", dx: -1, dy: 0, cursor: "w-resize", visible: overflowsX,
        ticks: [{ left: 0, top: "50%", transform: "translateY(-50%)", width: t, height: len }] },
      { key: "right", dx: 1, dy: 0, cursor: "e-resize", visible: overflowsX,
        ticks: [{ right: 0, top: "50%", transform: "translateY(-50%)", width: t, height: len }] },
      { key: "up-left", dx: -1, dy: -1, cursor: "nw-resize", visible: overflowsX && overflowsY,
        ticks: [{ top: 0, left: 0, width: len, height: t }, { top: 0, left: 0, width: t, height: len }] },
      { key: "up-right", dx: 1, dy: -1, cursor: "ne-resize", visible: overflowsX && overflowsY,
        ticks: [{ top: 0, right: 0, width: len, height: t }, { top: 0, right: 0, width: t, height: len }] },
      { key: "down-left", dx: -1, dy: 1, cursor: "sw-resize", visible: overflowsX && overflowsY,
        ticks: [{ bottom: 0, left: 0, width: len, height: t }, { bottom: 0, left: 0, width: t, height: len }] },
      { key: "down-right", dx: 1, dy: 1, cursor: "se-resize", visible: overflowsX && overflowsY,
        ticks: [{ bottom: 0, right: 0, width: len, height: t }, { bottom: 0, right: 0, width: t, height: len }] },
    ];
    return zones
      .filter((zone) => zone.visible)
      .flatMap((zone) =>
        zone.ticks.map((tickStyle, index) => (
          <div
            key={`${zone.key}-${index}`}
            className="zoom-overlay__pan-zone"
            style={{ ...tickStyle, cursor: zone.cursor }}
            onPointerDown={(event) => handlePanZonePointerDown(event, zone.dx, zone.dy)}
            onPointerUp={stopPanZone}
            onPointerLeave={stopPanZone}
            onPointerCancel={stopPanZone}
          />
        )),
      );
  }

  return { renderPanZones };
}
