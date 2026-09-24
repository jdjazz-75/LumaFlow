// LumaFlow v1.0 (2026-09-23)
// État remonté (lifted state) des zones de suppression -- partagé entre RemovalToolStage (la
// scène de dessin) et RemovalZoneControls (le panneau : liste de zones, Marge/Fondu/Proposition),
// comme maskPoints/maskFeather/maskInvert le sont déjà pour le masque sujet dans ZoomOverlay.tsx.

import { useState } from "react";
import {
  MAX_MASK_VERTICES,
  MAX_REMOVAL_ZONES,
  type MaskPoint,
  type RemovalValues,
  insertMidpoint,
  removalValuesFromById,
  removalValuesToUpdates,
  removeVertex,
  seedZone,
} from "./removalZones";

const EMPTY_VALUES: RemovalValues = {
  zones: Array.from({ length: MAX_REMOVAL_ZONES }, () => [] as MaskPoint[]),
  dilation: 0.5,
  feather: 0.3,
  variant: 0,
};

export type UseRemovalZones = {
  values: RemovalValues;
  activeZoneIndex: number | null;
  /** Replaces the whole record from a fresh GET .../zoom/auxiliary/removal response -- no network
  write of its own. */
  load: (byId: Record<string, number>) => void;
  /** Toggles ONE fixed zone slot on/off (ergonomics revision, 2026-09-24 -- replaces the old
  "add to the first free slot" button/"delete" pair now that there are only MAX_REMOVAL_ZONES=4
  always-visible slots in the panel): enabling an empty slot seeds it with a default rectangle and
  selects it for on-canvas editing; disabling a slot clears its points and deselects it if it was
  the active one. Re-enabling an already-non-empty slot just (re)selects it, a no-op commit-wise. */
  setZoneEnabled: (index: number, enabled: boolean) => void;
  selectZone: (index: number | null) => void;
  /** Local-only update while a vertex is being dragged -- mirrors ZoomOverlay's own
  handleMaskPointerMove (no network call per pointermove tick). */
  setZonePointsLive: (index: number, points: MaskPoint[]) => void;
  commitZonePoints: (index: number, points: MaskPoint[]) => void;
  /** Inserts a vertex at an edge's midpoint (local only, matches handleMaskMidpointPointerDown's
  own "insert then keep dragging" gesture) -- returns the inserted vertex's index, or the given
  `edgeIndex` unchanged if the zone is already at MAX_MASK_VERTICES. */
  insertZoneMidpoint: (index: number, edgeIndex: number) => number;
  /** Removes one vertex and commits immediately (a double-click, not a drag) -- a no-op below the
  minimum vertex count. */
  removeZoneVertex: (index: number, vertexIndex: number) => void;
  setDilation: (value: number) => void;
  setFeather: (value: number) => void;
  nextVariant: () => void;
  resetAll: () => void;
};

export function useRemovalZones(commit: (updates: Array<{ identifier: string; value: number }>) => void): UseRemovalZones {
  const [values, setValues] = useState<RemovalValues>(EMPTY_VALUES);
  const [activeZoneIndex, setActiveZoneIndex] = useState<number | null>(null);

  function commitAll(next: RemovalValues) {
    setValues(next);
    commit(removalValuesToUpdates(next));
  }

  return {
    values,
    activeZoneIndex,

    load(byId) {
      setValues(removalValuesFromById(byId));
    },

    setZoneEnabled(index, enabled) {
      const hasPoints = (values.zones[index]?.length ?? 0) > 0;
      if (enabled) {
        setActiveZoneIndex(index);
        if (hasPoints) return; // already on -- just (re)select it, nothing to commit
        const zones = values.zones.map((z, i) => (i === index ? seedZone(index) : z));
        commitAll({ ...values, zones });
        return;
      }
      if (!hasPoints) return; // already off
      const zones = values.zones.map((z, i) => (i === index ? [] : z));
      setActiveZoneIndex((current) => (current === index ? null : current));
      commitAll({ ...values, zones });
    },

    selectZone(index) {
      setActiveZoneIndex(index);
    },

    setZonePointsLive(index, points) {
      setValues((prev) => ({ ...prev, zones: prev.zones.map((z, i) => (i === index ? points : z)) }));
    },

    commitZonePoints(index, points) {
      const zones = values.zones.map((z, i) => (i === index ? points : z));
      commitAll({ ...values, zones });
    },

    insertZoneMidpoint(index, edgeIndex) {
      const points = values.zones[index] ?? [];
      if (points.length === 0 || points.length >= MAX_MASK_VERTICES) return edgeIndex;
      const { points: next, insertedIndex } = insertMidpoint(points, edgeIndex);
      setValues((prev) => ({ ...prev, zones: prev.zones.map((z, i) => (i === index ? next : z)) }));
      return insertedIndex;
    },

    removeZoneVertex(index, vertexIndex) {
      const points = values.zones[index] ?? [];
      const next = removeVertex(points, vertexIndex);
      if (next === points) return; // refused -- already at the minimum
      const zones = values.zones.map((z, i) => (i === index ? next : z));
      commitAll({ ...values, zones });
    },

    setDilation(value) {
      commitAll({ ...values, dilation: value });
    },

    setFeather(value) {
      commitAll({ ...values, feather: value });
    },

    nextVariant() {
      commitAll({ ...values, variant: (values.variant + 1) % 1000 });
    },

    resetAll() {
      setActiveZoneIndex(null);
      commitAll(EMPTY_VALUES);
    },
  };
}
