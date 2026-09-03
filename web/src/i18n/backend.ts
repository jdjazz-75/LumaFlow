// LumaFlow v1.0 (2026-09-03)
// Résolveurs des libellés produits par le backend (lignes, paramètres d'addon, presets, overlays) :
// traduction si la clé existe, repli sur le libellé envoyé par le backend sinon.
/* I18N-PLAN.md décision D3 -- the backend stays the DECLARATIVE source, not the LINGUISTIC one.
No addon Python file is modified by the i18n work: each addon keeps declaring its own `label`, and
this module upgrades it to the active locale when it recognizes the identifier. An addon we have
never seen (a third-party one) therefore still renders its declared label, never a raw key.

Parameter lookup is two-tiered on purpose:
  1. `param.<rowIdentifier>.<paramIdentifier>` -- lets one row override a shared term.
  2. `param.<paramIdentifier>` -- the shared photographic vocabulary ("Contraste", "Netteté",
     "Grain"...), which really is the same word for film/bw/monochrome/light and would otherwise be
     copied four times with four chances to drift.
Same two tiers for presets and overlays. */

import type { RowSpec, ZoomHueRange, ZoomOverlay, ZoomSlider } from "../lib/api";
import { NEUTRAL_PRESET_IDENTIFIER } from "../lib/filmstrip";
import { t, tOr } from "./index";

/** A row's display name. `undefined` (an index that no longer exists mid-refresh) yields "". */
export function rowDisplayLabel(row: Pick<RowSpec, "identifier" | "label"> | undefined): string {
  if (!row) return "";
  return tOr(`row.${row.identifier}.label`, row.label);
}

/** A row's caption line under its name. */
export function rowDescription(row: Pick<RowSpec, "identifier" | "short_description">): string {
  return tOr(`row.${row.identifier}.description`, row.short_description);
}

/** Names a step by its backend identifier when no RowSpec is at hand -- feature 048's
parameter_corrections / disabled_vignette_corrections entries carry only `step_identifier`. Prefers
the live row (so a renamed workflow row reads correctly) and degrades to the identifier itself. */
export function rowLabelForIdentifier(
  rows: Pick<RowSpec, "identifier" | "label">[],
  stepIdentifier: string,
): string {
  const row = rows.find((candidate) => candidate.identifier === stepIdentifier);
  if (row) return rowDisplayLabel(row);
  return tOr(`row.${stepIdentifier}.label`, stepIdentifier);
}

/** A Zoom slider / hue-range label. */
export function paramLabel(rowIdentifier: string, param: Pick<ZoomSlider | ZoomHueRange, "identifier" | "label">): string {
  const dynamic = dynamicParamLabel(rowIdentifier, param.identifier);
  if (dynamic !== null) return dynamic;
  return tOr([`param.${rowIdentifier}.${param.identifier}`, `param.${param.identifier}`], param.label);
}

/* Addons that generate one parameter per repeated element declare their labels as Python
f-strings ("Zone 2 — adoucissement du contour", "Sommet 3 (x)", "Intervalle 1"...). Those can't be
enumerated as fixed keys, so they are recognized by identifier SHAPE and rebuilt from a parameterized
key. Patterns are ordered most-specific first; each capture group feeds the interpolation. */
const DYNAMIC_PARAM_PATTERNS: { test: RegExp; key: string; params: (m: RegExpMatchArray) => Record<string, string | number> }[] = [
  // Color Splash, per-range polygon zone (color_splash.py's _mask_parameter_descriptions --
  // identifiers are range-prefixed, the LABELS call them "Zone N")
  { test: /^range_(\d+)_mask_point_count$/, key: "param.dyn.zone_vertex_count", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)_mask_feather$/, key: "param.dyn.zone_feather", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)_mask_invert$/, key: "param.dyn.zone_invert", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)_mask_point_(\d+)_([xy])$/, key: "param.dyn.zone_vertex", params: (m) => ({ index: m[1], vertex: Number(m[2]), axis: m[3] }) },
  // Color Splash, hue ranges and their substitution targets
  { test: /^range_(\d+)_target_enabled$/, key: "param.dyn.replacement_enabled", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)_target_saturation_boost$/, key: "param.dyn.replacement_boost", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)_target$/, key: "param.dyn.replacement", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)_enabled$/, key: "param.dyn.range_enabled", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)_saturation_boost$/, key: "param.dyn.range_boost", params: (m) => ({ index: m[1] }) },
  { test: /^range_(\d+)$/, key: "param.dyn.range", params: (m) => ({ index: m[1] }) },
  // Light, subject/background polygon mask (light.py's _mask_parameters)
  { test: /^mask_point_(\d+)_([xy])$/, key: "param.dyn.vertex", params: (m) => ({ vertex: Number(m[1]), axis: m[2] }) },
];

function dynamicParamLabel(rowIdentifier: string, identifier: string): string | null {
  for (const pattern of DYNAMIC_PARAM_PATTERNS) {
    const match = identifier.match(pattern.test);
    if (match) return t(pattern.key, pattern.params(match));
  }
  // Light v2's region deltas: "subject_highlights" / "background_clarity" -- one label built from
  // the base parameter's own translated name plus the region name (light.py's _REGION_LABELS).
  const region = identifier.match(/^(subject|background)_(.+)$/);
  if (region) {
    const base = tOr([`param.${rowIdentifier}.${region[2]}`, `param.${region[2]}`], region[2]);
    return t("param.dyn.region", { label: base, region: t(`zoom.region.${region[1]}`) });
  }
  return null;
}

/** A vignette caption / preset name. Proper nouns (Velvia, Acros, Kodak Tri-X...) deliberately have
no catalog key and fall through to the identifier itself, unchanged in every locale. */
export function presetLabel(rowIdentifier: string, identifier: string): string {
  if (identifier === NEUTRAL_PRESET_IDENTIFIER) return t("preset.neutral");
  return tOr([`preset.${rowIdentifier}.${identifier}`, `preset.${identifier}`], identifier);
}

/** A composition-guide overlay entry (Framing's thirds/golden_section/...). */
export function overlayLabel(rowIdentifier: string, overlay: Pick<ZoomOverlay, "kind" | "label">): string {
  return tOr([`overlay.${rowIdentifier}.${overlay.kind}`, `overlay.${overlay.kind}`], overlay.label);
}

/** A Zoom accordion group name. `GROUP_ORDER`'s values are stable slugs, never display text. */
export function groupLabel(slug: string): string {
  return t(`group.${slug}`);
}
