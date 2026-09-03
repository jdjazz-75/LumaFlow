// LumaFlow v1.0 (2026-08-07)
// Helpers purs du filmstrip : fenêtre glissante de 3 lignes visibles, lignes masquées
// (Geometry/Framing) et libellé d'affichage d'une vignette.

/* Historically ported 1:1 from the now-deleted Qt app's filmstrip_view.py
pure helpers (visible_row_indices, vignette_display_text,
NEUTRAL_PRESET_IDENTIFIER) -- this file has been the sole source of truth
for this screen's behavior since the Qt UI's removal (2026-07-29). */

export const NEUTRAL_PRESET_IDENTIFIER = "neutral";

/** Geometry/Cadrage are no longer shown as standalone filmstrip rows (2026-07-24) -- both are now
edited exclusively via the "Réglages manuels" > Geometry/Cadrage toggle inside Film's and Color
Splash's own Zoom (the auxiliary zoom parameter mechanism). They remain real, indexed pipeline
steps on the backend (config_workflow.json is untouched) -- only the web editing UI hides them.

Matched on `RowSpec.identifier` since 2026-09-03 (i18n phase 1). It used to match on `label`, a
convention this file itself called "fragile-but-established" -- and one that stopped working the
moment "Geometry" became "Géométrie", silently un-hiding both rows. */
export const HIDDEN_ROW_IDENTIFIERS = new Set(["geometry", "framing"]);

/** True for a row the web UI never lists as a standalone filmstrip row. */
export function isHiddenRow(row: { identifier: string }): boolean {
  return HIDDEN_ROW_IDENTIFIERS.has(row.identifier);
}

/** Real row indices (matching the backend's positional stepIndex, used by activateStep/
thumbnailUrl/zoomTarget.stepIndex) with HIDDEN_ROW_IDENTIFIERS excluded -- NOT renumbered, since
downstream API calls are positional against the full 7-row pipeline. Any component that lists or
navigates rows (Filmstrip, StatusBar) should iterate this instead of `rows` directly. */
export function visibleRowRealIndices(rows: { identifier: string }[]): number[] {
  return rows.map((_, i) => i).filter((i) => !isHiddenRow(rows[i]));
}

/** The always-3-wide row window (ergonomics correction, 2026-07-13):
centered on activeIndex in the general case, but pinned to the same side at
either boundary. Below 3 total rows, every real index is returned. Mirrors
filmstrip_view.py's visible_row_indices exactly. */
export function visibleRowIndices(activeIndex: number, total: number): number[] {
  let windowStart: number;
  if (total <= 3) {
    windowStart = 0;
  } else if (activeIndex === 0) {
    windowStart = 0;
  } else if (activeIndex === total - 1) {
    windowStart = total - 3;
  } else {
    windowStart = activeIndex - 1;
  }
  const end = Math.min(windowStart + 3, total);
  const indices: number[] = [];
  for (let i = windowStart; i < end; i++) indices.push(i);
  return indices;
}

/** ancien (jusqu'au 2026-09-03) : le libellé d'affichage d'une vignette était calculé ici, et
renvoyait la chaîne ANGLAISE "Neutral" alors que les 7 addons déclarent tous `label="Neutre"` --
le `ThumbnailPreset.label` n'étant jamais lu par le frontend (voir CLAUDE.md), c'est cet anglais-là
qui s'affichait sur chaque ligne. Remplacé par i18n/backend.ts's `presetLabel(rowIdentifier,
identifier)`, qui traduit ET reste indexé sur l'identifiant persisté (jamais réécrit, cf. D5).

export function vignetteDisplayText(identifier: string): string {
  return identifier === NEUTRAL_PRESET_IDENTIFIER ? "Neutral" : identifier;
}
*/
