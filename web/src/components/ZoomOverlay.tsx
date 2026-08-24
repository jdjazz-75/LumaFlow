// LumaFlow v1.0 (2026-08-07)
// Grand overlay Zoom : comparateur avant/après avec zoom optique/pan, panneau "Réglages manuels"
// (sliders/roues de teinte/groupes par addon) et intégration des stages Cadrage/Geometry/Masque
// Sujet/Forme de vignettage pour l'édition détaillée d'une ligne.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type SyntheticEvent,
} from "react";
import "./ZoomOverlay.css";
import * as api from "../lib/api";
import type { RowSpec, ZoomHueRange, ZoomOverlay as ZoomOverlayDescriptor, ZoomSlider, ZoomState } from "../lib/api";
import { vignetteDisplayText } from "../lib/filmstrip";
import { computeFitPercent } from "../lib/zoomFit";
import { CloseIcon, SplitHandleIcon } from "./icons";
import { HueRing, type HueRingHandle } from "./HueRing";
import { ColorWheel } from "./ColorWheel";
import { CropToolStage, cropValuesFromById, type CropToolStageHandle, type CropValues } from "./CropToolStage";
import { GeometryToolStage, geometryValuesFromById, type GeometryToolStageHandle, type GeometryValues } from "./GeometryToolStage";
import {
  SubjectMaskLayer,
  SubjectMaskControls,
  maskValuesFromById,
  maskValuesToUpdates,
  clampMaskFraction,
  isMaskParameter,
  FULL_FRAME_POINTS,
  MAX_MASK_VERTICES,
  MIN_MASK_VERTICES,
  type MaskPoint,
  type MaskValues,
} from "./SubjectMaskStage";
import {
  VignetteShapeOverlay,
  VignetteShapeControls,
  vignetteValuesFromById,
  imageOffsetToLocal,
  fractionToOffset,
  type VignetteShapeValues,
  type VignetteActiveTool,
  type EllipseHandleId,
  type LineBorderId,
} from "./VignetteShapeStage";
import { CollapsibleSection } from "./CollapsibleSection";

// Vignetting's own row (feature 044 + the "dynamic aids" pass): unlike Geometry/Cadrage, which
// are only ever edited as an "auxiliary correction" from within another row's Zoom, Vignette is
// zoomed DIRECTLY -- its interactive shape editor is a new, independent condition below, not an
// extension of activeCorrection/CORRECTION_ROWS. The 7 fields it drives directly via the shape
// editor (all but feather_width, which stays a plain slider in the panel) are hidden from the
// generic flat slider list so they aren't shown twice.
const VIGNETTE_SHAPE_BY_IDENTIFIER: Record<string, "round_central" | "linear_top_bottom"> = {
  "Round Central": "round_central",
  "Linear Top+Bottom": "linear_top_bottom",
};
const VIGNETTE_SHAPE_GEOMETRY_FIELDS = new Set([
  "center_x", "center_y", "radius_x", "radius_y", "top_offset", "bottom_offset", "rotation_angle",
]);

// Geometry/Cadrage integrated into Film/Color Splash's own Zoom (cross-row corrections): every
// row except Geometry/Framing themselves gets the "Réglages manuels" toggles below. "framing" is
// config_workflow.json's row identifier for Cadrage, matching lumaflow/api/session.py's auxiliary
// endpoints.
type CorrectionKind = "geometry" | "framing";
const CORRECTION_ROWS: Record<string, true> = {
  Film: true,
  "Bleach Bypass": true,
  "Color Splash": true,
  Monochrome: true,
  "B&W": true,
  Light: true,
  Vignettage: true,
};
const CORRECTION_LABELS: Record<CorrectionKind, string> = { geometry: "Geometry", framing: "Cadrage" };

/** A `numeric_slider` declared with exactly these bounds (e.g. Color Splash's
`range_N_enabled`, feature 046) is rendered as an on/off toggle instead of a drag slider --
detected generically by its constraints shape, not by identifier, so any addon following the
same 0/1/1 convention gets the same affordance without ZoomOverlay knowing its name. */
function isBinaryToggle(slider: ZoomSlider): boolean {
  return slider.minimum === 0 && slider.maximum === 1 && slider.step === 1;
}

/** filter_color's 4 non-zero values (see film.py's _FILTER_WEIGHTS_TABLE), rendered as labeled
on/off buttons instead of a plain numeric slider (user feedback, 2026-08-04: "1"/"2"/"3"/"4" on a
drag slider didn't identify which color was which). English labels match the existing "Acros +
Yellow" etc. preset identifiers, not translated. */
const FILTER_COLOR_OPTIONS: { value: number; label: string }[] = [
  { value: 1, label: "Yellow" },
  { value: 2, label: "Red" },
  { value: 3, label: "Green" },
  { value: 4, label: "Blue" },
];

/** filter_intensity's 3 steps (0/1/2), labeled instead of shown as a bare number (user feedback,
2026-08-05: "0" read as "no filter" even though it actually means "Léger", the lightest of the 3
non-zero-filter intensities -- filter_color, not filter_intensity, is what carries the "off"
state). Keeps the drag-slider interaction the user already liked, just relabels the displayed
value. */
const FILTER_INTENSITY_LABELS = ["Léger", "Modéré", "Foncé"];

function formatSliderValue(slider: ZoomSlider, value: number): string {
  if (slider.identifier === "filter_intensity") {
    return FILTER_INTENSITY_LABELS[Math.round(value)] ?? value.toFixed(0);
  }
  return value.toFixed(slider.step < 1 ? 3 : 0);
}

/** Light's subject_/background_ prefix (feature 047, User Story 3) -- strips it so
LIGHT_SLIDER_GROUPS (keyed by the plain base identifier) can group `subject_exposure`/
`background_exposure`/... alongside `exposure` with zero addon-specific casing; `regionOf`
classifies which of the 3 region tabs (Global · Sujet · Fond) a slider belongs to. Both are
identity/`"global"` for every non-prefixed identifier (every other addon), so they're safe to call
unconditionally on any row's sliders. */
function regionOf(identifier: string): "subject" | "background" | "global" {
  if (identifier.startsWith("subject_")) return "subject";
  if (identifier.startsWith("background_")) return "background";
  return "global";
}
function baseIdOf(identifier: string): string {
  if (identifier.startsWith("subject_")) return identifier.slice("subject_".length);
  if (identifier.startsWith("background_")) return identifier.slice("background_".length);
  return identifier;
}

/** Groups a hue_range with its `${identifier}_enabled`/`${identifier}_saturation_boost`
siblings from `sliders`, by naming convention -- lets the ring, its feather control, and its
enable toggle render together without ZoomOverlay hardcoding "color_splash" or "range_N". */
function groupHueRanges(hueRanges: ZoomHueRange[], sliders: ZoomSlider[]) {
  return hueRanges.map((hueRange) => ({
    hueRange,
    enabledSlider: sliders.find((s) => s.identifier === `${hueRange.identifier}_enabled`) ?? null,
    boostSlider: sliders.find((s) => s.identifier === `${hueRange.identifier}_saturation_boost`) ?? null,
  }));
}

/** Presentation-only grouping metadata for the "Réglages manuels" accordion, keyed by
`rowLabel` (same fragile-but-established signal as the Framing/Geometry dispatch above). Addons
absent from this map (Light, Vignette) fall back to the original flat slider list -- adding an
addon here doesn't affect any other row. Color Splash isn't listed here: its hue-range
groups (+ a "Réglages globaux" group for its 2 plain sliders) are handled by a dedicated branch
below, since its shape (ranges, not a flat identifier list) doesn't fit this map. */
const FILM_SLIDER_GROUPS: Record<string, string> = {
  intensity: "Intensité",
  contrast: "Tonalité",
  highlights: "Tonalité",
  shadows: "Tonalité",
  black_clip: "Tonalité",
  global_saturation: "Couleur",
  hsl_saturation_scale: "Couleur",
  hsl_luminance_scale: "Couleur",
  temperature: "Couleur",
  tint: "Couleur",
  split_tone_scale: "Couleur",
  clarity: "Texture & Grain",
  sharpness: "Texture & Grain",
  grain_std: "Texture & Grain",
  // Added 2026-07-25 for the Summer Story/Inky Depths recipes -- each a
  // discrete Off/Weak/Strong (or DR100/200/400) 3-level dial, rendered as
  // an ordinary slider (no frontend kind change needed, see film.py).
  dynamic_range: "Tonalité",
  color_chrome_effect: "Couleur",
  color_chrome_blue: "Couleur",
  // Added 2026-07-26 for the "Monochrome" workflow row's recipes -- Fuji's
  // "Mono Colour" WC/MG dial pair, silently inert on color looks (see
  // film.py's _apply_monochrome_grade), same grouping as the other
  // toning/cast sliders above.
  mono_color_wc: "Couleur",
  mono_color_mg: "Couleur",
};

// B&W (2026-08-04): a single colored-filter selector + intensity dial (Yellow/Red/Green/Blue,
// Léger/Modéré/Foncé -- see film.py's _resolve_filter_weights), exclusive to this row. Spreads
// FILM_SLIDER_GROUPS (every other slider is identical/shared) but must NOT reuse that same object:
// filter_color/filter_intensity are meaningless on Film/Bleach Bypass's own color-look presets
// (monochrome_weights starts at None there -- see film.py's own note on why the backend override
// still technically applies, but showing the dial there would only confuse), so they're declared
// in this dedicated map instead, under a new "Filtre" group (see GROUP_ORDER below).
const BW_SLIDER_GROUPS: Record<string, string> = {
  ...FILM_SLIDER_GROUPS,
  filter_color: "Filtre",
  filter_intensity: "Filtre",
};

// Monochrome (2026-07-27): a dedicated addon (monochrome_tone.py), distinct
// from film_look -- "Monochrome" itself used to share Film's grouping (this
// map) but its earlier film_look-based presets (Monochrome/Underglow/Gilt
// Trip) were retired the same day in favor of this new duotone-colorize
// addon (Ambre/Bleu Nuit/Vert Cactus/Jaune Léger/Sépia Chaud), with its own
// 14 sliders (+ intensity) instead of Film's 19.
const MONOCHROME_TONE_SLIDER_GROUPS: Record<string, string> = {
  intensity: "Intensité",
  force: "Intensité",
  contrast: "Tonalité",
  shadows: "Tonalité",
  highlights: "Tonalité",
  black_point: "Tonalité",
  hue: "Couleur",
  tint_saturation: "Couleur",
  original_saturation: "Couleur",
  temperature_shift: "Couleur",
  tint_magenta: "Couleur",
  clarity: "Texture & Grain",
  sharpness: "Texture & Grain",
  grain: "Texture & Grain",
  vignette: "Texture & Grain",
};

// Light v2 (feature 047) -- the ~31 base-grade fields grouped into 5 buckets (no separate
// "Intensité" bucket unlike Film/Monochrome; `intensity` folds into the first group). Region-delta
// (subject_*/background_*) and mask fields are NOT listed here -- this map is an allow-list, so
// they simply never render as plain sliders (User Story 3's own delta fields render via
// baseIdOf-stripped identifiers matching these same group names, see regionOf/baseIdOf above).
const LIGHT_SLIDER_GROUPS: Record<string, string> = {
  intensity: "Exposition & Tonalité",
  exposure: "Exposition & Tonalité",
  contrast: "Exposition & Tonalité",
  contrast_pivot: "Exposition & Tonalité",
  blacks: "Exposition & Tonalité",
  shadows: "Exposition & Tonalité",
  highlights: "Exposition & Tonalité",
  whites: "Exposition & Tonalité",
  black_point: "Exposition & Tonalité",
  black_floor: "Exposition & Tonalité",
  saturation: "Couleur",
  temperature: "Couleur",
  tint: "Couleur",
  split_shadow_hue: "Couleur",
  split_shadow_strength: "Couleur",
  split_highlight_hue: "Couleur",
  split_highlight_strength: "Couleur",
  hsl_saturation_scale: "Couleur",
  hsl_luminance_scale: "Couleur",
  clarity: "Texture & Netteté",
  texture: "Texture & Netteté",
  sharpness: "Texture & Netteté",
  dehaze: "Texture & Netteté",
  bloom_threshold: "Halo & Douceur",
  bloom_amount: "Halo & Douceur",
  bloom_radius: "Halo & Douceur",
  bloom_warmth: "Halo & Douceur",
  soft_detail_amount: "Halo & Douceur",
  soft_detail_radius: "Halo & Douceur",
  edge_protection: "Halo & Douceur",
  vignette: "Finition",
  grain: "Finition",
};

// "Bleach Bypass" is another workflow row over the SAME film_look addon
// (config_workflow.json: category "film" shared with "Film", just a
// different preset subset -- see lumaflow/api/session.py's category-based
// row/addon resolution) -- same 19 sliders, so it reuses Film's exact
// grouping rather than duplicating it. "B&W" shares those same 19 but adds 2
// more of its own (filter_color/filter_intensity, 2026-08-04) not meaningful
// on Film/Bleach Bypass's color looks, hence its own BW_SLIDER_GROUPS map
// above instead of reusing FILM_SLIDER_GROUPS directly.
const SLIDER_GROUPS: Record<string, Record<string, string>> = {
  Film: FILM_SLIDER_GROUPS,
  "Bleach Bypass": FILM_SLIDER_GROUPS,
  Monochrome: MONOCHROME_TONE_SLIDER_GROUPS,
  "B&W": BW_SLIDER_GROUPS,
  Light: LIGHT_SLIDER_GROUPS,
};

const GROUP_ORDER: Record<string, string[]> = {
  Film: ["Intensité", "Tonalité", "Couleur", "Texture & Grain"],
  "Bleach Bypass": ["Intensité", "Tonalité", "Couleur", "Texture & Grain"],
  Monochrome: ["Intensité", "Tonalité", "Couleur", "Texture & Grain"],
  "B&W": ["Intensité", "Tonalité", "Filtre", "Couleur", "Texture & Grain"],
  Light: ["Exposition & Tonalité", "Couleur", "Texture & Netteté", "Halo & Douceur", "Finition"],
};

// Generalizes the single hardcoded Monochrome hue/tint_saturation ColorWheel wiring (feature
// 2026-07-27) into a per-row table of wheel pairs (feature 047) -- Monochrome's own entry is
// unchanged (satScale: 1, bit-identical behavior: the wheel's 0-100 radius already matches
// tint_saturation's own range 1:1). Light adds two entries for its shadow/highlight split-tone
// (satScale: 5 maps split_*_strength's 0-20% range onto the wheel's 0-100 radius, mirroring Color
// Splash's own boost rescale, handleColorSplashWheelChange above).
type ColorWheelPair = { group: string; hue: string; sat: string; satScale: number; label: string };
const COLOR_WHEEL_PAIRS: Record<string, ColorWheelPair[]> = {
  Monochrome: [{ group: "Couleur", hue: "hue", sat: "tint_saturation", satScale: 1, label: "Teinte" }],
  Light: [
    { group: "Couleur", hue: "split_shadow_hue", sat: "split_shadow_strength", satScale: 5, label: "Virage ombres" },
    { group: "Couleur", hue: "split_highlight_hue", sat: "split_highlight_strength", satScale: 5, label: "Virage hautes lumières" },
  ],
};

// Debounce for the reduced-resolution PREVIEW re-render triggered by a slider edit -- the
// displayed number updates instantly on every input tick, but the network call only fires once
// dragging pauses (PERF-ZOOM-RENDER-PLAN.md étape 2: this used to gate the full-resolution render
// directly; it now gates a fast preview, with FULL_RESOLUTION_SETTLE_MS below firing the real
// full-resolution render after a longer pause).
const PARAMETER_UPDATE_DEBOUNCE_MS = 200;

// Fires PARAMETER_UPDATE_DEBOUNCE_MS after the preview above, i.e. this many ms of no further
// slider/wheel activity -- approximates "the user released the control" without needing a
// pointerup handler on every individual widget. Deliberately a fixed gap AFTER the preview timer
// (not a from-scratch delay) so the preview render has a real window to land and be shown before
// the full-resolution request supersedes it (see requestSeq's own docstring) -- too short a gap
// and the preview response routinely arrives too late to ever be seen.
const FULL_RESOLUTION_SETTLE_MS = PARAMETER_UPDATE_DEBOUNCE_MS + 400;

// Reuses the SAME cap already validated for the interactive Lignes+Vignettes preview path
// (lumaflow/api/session.py's _VIGNETTE_PREVIEW_MAX_DIMENSION_PX) rather than inventing a second,
// untested preview size -- deliberately just one reduced tier, not the 3-tier 480/960/full scheme
// initially proposed (see PERF-ZOOM-RENDER-PLAN.md étape 2's own rationale).
const ZOOM_PREVIEW_MAX_DIMENSION_PX = 480;

// Optical zoom (display-only magnification of the AVANT/APRÈS compare panes, feature 038 in the
// old Qt UI -- see lumaflow/ui/zoom_canvas.py's ZoomableImageView/OpticalZoomToolbar, which this
// mirrors). Purely visual: never touches pixels or parameters. Scoped to ZoomOverlayGeneric's
// plain compare view only (Film/Color Splash/Light/Vignette) here -- Geometry/Cadrage got their
// own zoom+pan added 2026-07-31 (GeometryToolStage.tsx/CropToolStage.tsx, via useFittedImageBox),
// reversing the 2026-07-24 "deliberately out of scope" decision after user feedback that it was
// needed for precision work despite the click-drag-gesture-conflict risk that motivated the
// original exclusion; the 8 pan-zone tick marks (not a second click-drag) sidestep that conflict.
// Real bounds come from Préférences (zoom_min_percent/zoom_max_percent); these two are only the
// fallback used for the brief window before that fetch resolves.
const FALLBACK_ZOOM_MIN_PERCENT = 20;
const FALLBACK_ZOOM_MAX_PERCENT = 400;
const ZOOM_STEP_PERCENT = 25; // mirrors zoom_canvas.py's _ZOOM_STEP_PERCENT

// Pan zones (8 amber tick marks -- 4 edges + 4 L-bracket corners -- around the compare viewport,
// added as a click-and-hold alternative to scroll-to-pan since the user reported being unable to
// use the scroll gesture, 2026-07-24). Purely visual/interaction constants: every tick (horizontal
// or vertical) is 10% of the viewport's own HEIGHT, kept uniform across orientations for a
// consistent look regardless of aspect ratio (user feedback, same day); thickness and speed are
// the two knobs to retune first if the feel is off. Geometry/Cadrage reuse this exact mechanism via
// web/src/lib/usePanZones.tsx (extracted 2026-07-31) rather than a second implementation; this
// plain compare pane's own pan zones were intentionally left as-is (not migrated to that shared
// hook) to avoid touching already-verified-working code while fixing the Geometry/Cadrage/Masque
// Sujet bug class -- see plan v2's rationale.
const PAN_ZONE_TICK_FRACTION = 0.1;
const PAN_ZONE_THICKNESS_PX = 4;
const PAN_SPEED_PX_PER_FRAME = 14;

type ZoomOverlayProps = {
  sessionId: string;
  stepIndex: number;
  rowLabel: string;
  identifier: string;
  onConfirm: (rows: RowSpec[]) => void;
  onCancel: (rows: RowSpec[]) => void;
};

// Geometry/Framing no longer have their own standalone Zoom entry point (2026-07-24, removed from
// the filmstrip) -- their editing now lives exclusively in ZoomOverlayGeneric's own "Réglages
// manuels" > Geometry/Cadrage toggle (Film/Color Splash), so this is a thin passthrough.
export function ZoomOverlay({ sessionId, stepIndex, rowLabel, identifier, onConfirm, onCancel }: ZoomOverlayProps) {
  return <ZoomOverlayGeneric sessionId={sessionId} stepIndex={stepIndex} rowLabel={rowLabel} identifier={identifier} onConfirm={onConfirm} onCancel={onCancel} />;
}

function ZoomOverlayGeneric({ sessionId, stepIndex, rowLabel, identifier, onConfirm, onCancel }: ZoomOverlayProps) {
  const [zoomState, setZoomState] = useState<ZoomState | null>(null);
  const [sliderValues, setSliderValues] = useState<Record<string, number>>({});
  const [hueRangeValues, setHueRangeValues] = useState<Record<string, { hue: number; feather: number }>>({});
  const [beforeSrc, setBeforeSrc] = useState<string>("");
  const [afterSrc, setAfterSrc] = useState<string>("");
  const [split, setSplit] = useState(50);
  const [error, setError] = useState<string | null>(null);

  // Geometry/Cadrage integrated into this Zoom (cross-row corrections, Film/Color Splash only --
  // see CORRECTION_ROWS). At most one active at a time (activating one deactivates the other);
  // `null` means the plain before/after compare + sliders panel below is shown, matching this
  // row's own Zoom behaviour before this feature existed. Off by default on every open -- never
  // auto-activated even if Geometry/Framing already has non-neutral values, so the user always
  // opts in explicitly.
  const [activeCorrection, setActiveCorrection] = useState<CorrectionKind | null>(null);
  const [geometryAux, setGeometryAux] = useState<{ values: GeometryValues; defaults: GeometryValues; photoSrc: string } | null>(null);
  const [framingAux, setFramingAux] = useState<
    | {
        values: CropValues; defaults: CropValues; overlays: ZoomOverlayDescriptor[]; photoSrc: string;
        imageSize: { width: number; height: number } | null;
      }
    | null
  >(null);
  const [correctionApplying, setCorrectionApplying] = useState(false);
  const geometryStageRef = useRef<GeometryToolStageHandle>(null);
  const cropStageRef = useRef<CropToolStageHandle>(null);

  // Polygon-mask editor. Two rows use it, through the SAME state and handlers, distinguished only
  // by which parameter prefix they address (see maskValuesFromById's own `prefix` argument):
  //   - Light (feature 047, User Stories 3/4): its single subject/background boundary, prefix "".
  //   - Color Splash (2026-08-24): one application zone PER hue range, prefix "range_N_" -- the
  //     zone restricting where that range colorizes, everything outside going black and white.
  // Neither is an auxiliary row (both masks live on the row's own step), so no separate aux fetch
  // is needed: the "before" photo already loaded for the plain compare view (beforeSrc, below)
  // doubles as the editor's background. `activeMask` holds which mask is being edited, or null;
  // only ever one at a time, since they all share the single drawing layer below.
  const [activeMask, setActiveMask] = useState<{ prefix: string; label: string } | null>(null);
  // Light only: which of the 3 slider sets (Global · Sujet · Fond) the accordion below shows --
  // independent of whether the mask editor itself is currently active, so a user can adjust
  // Sujet/Fond sliders without the mask overlay covering the compare view.
  const [regionTab, setRegionTab] = useState<"global" | "subject" | "background">("global");
  // Lifted out of the (now purely presentational) SubjectMaskLayer/SubjectMaskControls so the same
  // state can drive two JSX render sites at once -- the drawing layer inside the zoomable compare
  // viewport, and the floating control bar as a sibling of it (see ZoomOverlay.tsx's mask render
  // block below). This is the working copy of the CURRENTLY ACTIVE mask only, (re)loaded from
  // sliderValues on every activation rather than kept per-prefix -- sliderValues is already the
  // synced record of all of them (handleMaskCommit writes both), so one copy is enough regardless
  // of how many masks the row declares.
  const [maskPoints, setMaskPoints] = useState<MaskPoint[]>([]);
  const [maskFeather, setMaskFeather] = useState(2.0);
  const [maskInvert, setMaskInvert] = useState(false);
  const maskPhotoRef = useRef<HTMLDivElement>(null);
  const maskDragIndex = useRef<number | null>(null);

  // Vignetting's interactive shape editor (dynamic-aids pass) -- Vignette row only, active
  // whenever a non-Neutral preset is selected (both Round Central and Linear Top+Bottom declare
  // the same 8 geometry/feather fields). Values are lifted the same way maskPoints/maskFeather
  // are: seeded once per Zoom open (effect below), driving both the drawing layer (inside the
  // zoomable viewport) and the floating toolbar (a sibling of it).
  const vignetteShape = rowLabel === "Vignettage" ? VIGNETTE_SHAPE_BY_IDENTIFIER[identifier] ?? null : null;
  const [vignetteValues, setVignetteValues] = useState<VignetteShapeValues | null>(null);
  const [vignetteActiveTool, setVignetteActiveTool] = useState<VignetteActiveTool | null>(null);
  // Master on/off switch for the shape editor + floating toolbar, surfaced as a "Réglages
  // manuels" toggle row (below Geometry/Cadrage's own toggles) -- defaults to on since this is
  // this row's primary editing surface, not an auxiliary one (unlike Geometry/Cadrage/Masque
  // Sujet, which all default off).
  const [vignetteAidsEnabled, setVignetteAidsEnabled] = useState(true);
  const vignetteDialRef = useRef<HTMLDivElement>(null);
  type VignetteDragTarget =
    | { kind: "center" }
    | { kind: "dial" }
    | { kind: "vertex"; id: EllipseHandleId }
    | { kind: "border"; id: LineBorderId };
  const vignetteDragTarget = useRef<VignetteDragTarget | null>(null);

  const compareRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const draggingSplit = useRef(false);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // PERF-ZOOM-RENDER-PLAN.md étape 2: a second, longer timer layered on top of the existing
  // debounce -- debounceTimer now fires a fast REDUCED-resolution preview render (see
  // ZOOM_PREVIEW_MAX_DIMENSION_PX), fullResSettleTimer fires the real full-resolution render once
  // the slider/wheel has been quiet for longer, approximating "released" without needing a
  // pointerup handler on every individual control (numeric sliders, feather sliders, color
  // wheels, and toggles all already funnel through scheduleParameterUpdate).
  const fullResSettleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSliderUpdate = useRef<Array<[string, number]> | null>(null);
  const afterBlobUrl = useRef<string | null>(null);
  // Monotonic counter, one per issued render_zoom_after request (either tier) -- a response only
  // gets applied if its own captured value still matches this ref at arrival time, i.e. no NEWER
  // request has been issued since. Cheaper and more robust than AbortController here: it discards
  // a stale response as soon as a fresher request is ISSUED, not just once a fresher response
  // arrives, and it covers both tiers with one mechanism instead of per-request cancellation
  // (this codebase has twice shipped a bug from exactly this class of unordered async requests --
  // see memory zoom-overlay-commit-race-condition-fix / appshell-export-race-condition-fix).
  const requestSeq = useRef(0);

  // Whether the AFTER pane's most-recently-applied render response was the reduced-resolution
  // preview tier -- gates handleAfterPaneLoad below so a reduced preview's genuinely-smaller
  // img.naturalWidth/naturalHeight never corrupts naturalSize (and therefore .zoom-overlay__
  // compare-content's inline pixel size), which was shrinking the whole photo to a corner during
  // a drag then snapping back on the full-resolution response (reported 2026-08-07). Always
  // written together with setAfterSrc in applyRenderResponse below, so an onLoad always reads the
  // value matching its own src's provenance.
  const afterImageIsReducedPreview = useRef(false);

  // Tracks the most recent in-flight "commit to backend" write from any of the fire-and-forget
  // gesture-release commits below (Geometry/Cadrage auxiliary corrections, Masque Sujet, Vignette's
  // shape editor) -- these never awaited their own POST before letting the user's next action fire,
  // so switching Geometry<->Cadrage, clicking "Appliquer", or clicking "Valider" right after
  // releasing a drag could race ahead of that drag's own commit and read/finalize the PREVIOUS
  // value instead (found: a 45°+ Geometry rotation immediately followed by a tight Cadrage crop
  // near an edge intermittently applied against the stale, pre-rotation angle). Never rejects
  // itself (each commit function's own promise keeps its own .catch(setError)) so awaiting this
  // never throws.
  const pendingCommit = useRef<Promise<unknown>>(Promise.resolve());
  function trackCommit(promise: Promise<unknown>) {
    pendingCommit.current = promise.then(
      () => undefined,
      () => undefined,
    );
  }

  // --- Optical zoom (display-only magnification, see the constants/computeFitPercent above) ---
  const [zoomBounds, setZoomBounds] = useState({ min: FALLBACK_ZOOM_MIN_PERCENT, max: FALLBACK_ZOOM_MAX_PERCENT });
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [viewportSize, setViewportSize] = useState<{ width: number; height: number } | null>(null);
  // The image's own aspect ratio in real pixels -- required so Vignette's shape rotates rigidly
  // instead of shearing (see VignetteShapeStage.tsx's imageOffsetToLocal docstring); 1 until
  // naturalSize resolves (brief, harmless: only affects the very first paint before the photo
  // loads, and Vignette rows have no shape to draw yet at that point anyway).
  const vignetteAspect = naturalSize ? naturalSize.width / naturalSize.height : 1;
  // null until the first fit-to-screen computation resolves (needs both naturalSize and
  // viewportSize) -- ZoomOverlayGeneric is freshly mounted on every Zoom open (AppShell only
  // renders it while zoomTarget is set, unmounting on confirm/cancel), so this and the two states
  // above always start unset for a new session without any extra reset effect.
  const [zoomPercent, setZoomPercent] = useState<number | null>(null);
  const [zoomInputText, setZoomInputText] = useState("");
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  // --- Pan zones (click-and-hold amber tick marks, alternative to scroll-to-pan) -------------
  const panDirectionRef = useRef<{ dx: number; dy: number } | null>(null);
  const panFrameRef = useRef<number | null>(null);

  useEffect(() => {
    api
      .getPreferences()
      .then((prefs) => setZoomBounds({ min: prefs.zoom_min_percent, max: prefs.zoom_max_percent }))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (zoomPercent !== null || !naturalSize || !viewportSize) return;
    setZoomPercent(computeFitPercent(naturalSize, viewportSize, zoomBounds));
  }, [zoomPercent, naturalSize, viewportSize, zoomBounds]);

  useEffect(() => {
    if (zoomPercent !== null) setZoomInputText(String(zoomPercent));
  }, [zoomPercent]);

  // Callback ref instead of a plain useRef -- the viewport div only exists while the plain
  // compare branch is rendered (not during Geometry/Cadrage/loading), so the ResizeObserver must
  // start/stop as that DOM node is attached/detached rather than being set up once on mount.
  const setCompareRef = useCallback((node: HTMLDivElement | null) => {
    compareRef.current = node;
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (node) {
      const observer = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (entry) setViewportSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      });
      observer.observe(node);
      resizeObserverRef.current = observer;
    }
  }, []);

  function clampZoomPercent(percent: number) {
    return Math.max(zoomBounds.min, Math.min(zoomBounds.max, Math.round(percent)));
  }

  function handleZoomIn() {
    setZoomPercent(clampZoomPercent((zoomPercent ?? 100) + ZOOM_STEP_PERCENT));
  }

  function handleZoomOut() {
    setZoomPercent(clampZoomPercent((zoomPercent ?? 100) - ZOOM_STEP_PERCENT));
  }

  function handleZoomFit() {
    if (naturalSize && viewportSize) setZoomPercent(computeFitPercent(naturalSize, viewportSize, zoomBounds));
  }

  /** Opens (or closes) the polygon editor on ONE mask, identified by its parameter prefix.
  Turning it off closes the editor only -- the polygon stays in effect, exactly as it always has
  for Light's "Masque sujet"; Color Splash's own "Toute l'image" control is what actually clears a
  zone.

  zoomPercent is shared with the plain compare view and is never reset on its own -- entering
  mask-edit mode while already zoomed in there (e.g. 250%) would otherwise silently carry that
  magnification into the mask editor, showing only a fragment of the photo with no indication why
  (bug report 2026-07-31: "la photo est agrandie" for Masque Sujet). Always re-fit on activation so
  mask editing starts from a fully visible frame, matching the "Ajuster" button's own computation. */
  function handleToggleMask(prefix: string, label: string) {
    if (activeMask?.prefix === prefix) {
      setActiveMask(null);
      return;
    }
    if (naturalSize && viewportSize) setZoomPercent(computeFitPercent(naturalSize, viewportSize, zoomBounds));
    // Load THIS mask's working copy; switching straight from another range's zone therefore shows
    // the right polygon instead of the previous one's.
    const values = maskValuesFromById(sliderValues, prefix);
    if (values.points.length < MIN_MASK_VERTICES) {
      // No zone drawn yet: seed the full frame so there is something to drag, and commit it. With
      // the 0% default feather this polygon is bit-identical to "no zone", so merely opening the
      // editor never changes the render (color_splash.py's _FULL_FRAME_POINTS carries the same
      // note on the backend side).
      const seeded = { points: FULL_FRAME_POINTS, feather: values.feather, invert: values.invert };
      setMaskPoints(seeded.points);
      setMaskFeather(seeded.feather);
      setMaskInvert(seeded.invert);
      handleMaskCommit(maskValuesToUpdates(seeded, prefix));
    } else {
      setMaskPoints(values.points);
      setMaskFeather(values.feather);
      setMaskInvert(values.invert);
    }
    setActiveCorrection(null);
    setActiveMask({ prefix, label });
  }

  function handleZoomSliderChange(value: number) {
    setZoomPercent(clampZoomPercent(value));
  }

  function commitZoomInput() {
    const value = Number(zoomInputText);
    if (Number.isFinite(value)) setZoomPercent(clampZoomPercent(value));
    else setZoomInputText(String(zoomPercent ?? 100));
  }

  function handleAfterPaneLoad(event: SyntheticEvent<HTMLImageElement>) {
    // A reduced-preview load's own (genuinely smaller) naturalWidth/naturalHeight must never
    // resize the compare box -- see afterImageIsReducedPreview's own docstring.
    if (afterImageIsReducedPreview.current) return;
    const img = event.currentTarget;
    setNaturalSize((current) => {
      if (current && current.width === img.naturalWidth && current.height === img.naturalHeight) return current;
      return { width: img.naturalWidth, height: img.naturalHeight };
    });
  }

  useEffect(() => {
    let cancelled = false;
    api
      .openZoom(sessionId, stepIndex, identifier)
      .then((state) => {
        if (cancelled) return;
        setZoomState(state);
        const byId = Object.fromEntries(state.sliders.map((s) => [s.identifier, s.value]));
        setSliderValues(byId);
        const mask = maskValuesFromById(byId);
        setMaskPoints(mask.points);
        setMaskFeather(mask.feather);
        setMaskInvert(mask.invert);
        setVignetteValues(vignetteValuesFromById(byId));
        setVignetteActiveTool(null);
        setHueRangeValues(
          Object.fromEntries(state.hue_ranges.map((r) => [r.identifier, { hue: r.hue_value, feather: r.feather_value }])),
        );
        setBeforeSrc(`${api.zoomBeforeUrl(sessionId)}?t=${Date.now()}`);
        setAfterSrc(`${api.zoomAfterUrl(sessionId)}?t=${Date.now()}`);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      if (fullResSettleTimer.current) clearTimeout(fullResSettleTimer.current);
      if (afterBlobUrl.current) URL.revokeObjectURL(afterBlobUrl.current);
      if (panFrameRef.current !== null) cancelAnimationFrame(panFrameRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, stepIndex, identifier]);

  // Whether the zoomed content currently overflows the viewport on each axis -- derived from
  // state already tracked for the optical-zoom toolbar, no extra DOM reads. Drives which of the 8
  // pan zones are shown (edges need overflow on their own axis, corners need both).
  const overflowsX = Boolean(
    naturalSize && viewportSize && zoomPercent !== null && (naturalSize.width * zoomPercent) / 100 > viewportSize.width + 0.5,
  );
  const overflowsY = Boolean(
    naturalSize && viewportSize && zoomPercent !== null && (naturalSize.height * zoomPercent) / 100 > viewportSize.height + 0.5,
  );

  function panStep() {
    const el = compareRef.current;
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

  /** One amber tick per array entry -- an edge zone renders one, a corner zone renders two
  (forming an L) sharing the same drag direction/handlers. All ticks share a single length (10% of
  the viewport's own HEIGHT, `len` below) regardless of orientation -- horizontal and vertical
  ticks previously used 10% of width/height respectively, which looked mismatched whenever the
  viewport wasn't square (user feedback, 2026-07-24). Computed in real pixels from `viewportSize`
  rather than CSS percentages, since a corner's hit region isn't itself sized to the viewport. */
  function renderPanZones() {
    if (!viewportSize || (!overflowsX && !overflowsY)) return null;
    const len = viewportSize.height * PAN_ZONE_TICK_FRACTION;
    const t = PAN_ZONE_THICKNESS_PX;
    const zones: Array<{
      key: string; dx: number; dy: number; cursor: string; visible: boolean;
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

  // --- Geometry/Cadrage integrated into this Zoom (cross-row corrections) --------------------

  function loadGeometryAux() {
    // Waits for any commit still in flight (this row's own mask/vignette edits, or Cadrage's own
    // corner/rotation edits from a moment ago) so the fetched "before" and slider values always
    // reflect the LATEST state, not whatever the backend happened to hold before that commit's
    // response arrived -- see pendingCommit's own comment for the bug this closes.
    pendingCommit.current.then(() => {
      api
        .getAuxiliaryZoomState(sessionId, "geometry")
        .then((state) => {
          const byId = Object.fromEntries(state.sliders.map((s) => [s.identifier, s.value]));
          const byDefault = Object.fromEntries(state.sliders.map((s) => [s.identifier, s.default]));
          setGeometryAux({
            values: geometryValuesFromById(byId),
            defaults: geometryValuesFromById(byDefault),
            photoSrc: `${api.auxiliaryZoomBeforeUrl(sessionId, "geometry")}?t=${Date.now()}`,
          });
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    });
  }

  function loadFramingAux() {
    pendingCommit.current.then(() => {
      Promise.all([api.getAuxiliaryZoomState(sessionId, "framing"), api.getSessionInfo(sessionId)])
        .then(([state, info]) => {
          const byId = Object.fromEntries(state.sliders.map((s) => [s.identifier, s.value]));
          const byDefault = Object.fromEntries(state.sliders.map((s) => [s.identifier, s.default]));
          setFramingAux({
            values: cropValuesFromById(byId),
            defaults: cropValuesFromById(byDefault),
            overlays: state.overlays,
            photoSrc: `${api.auxiliaryZoomBeforeUrl(sessionId, "framing")}?t=${Date.now()}`,
            imageSize: info.source ? { width: info.source.width, height: info.source.height } : null,
          });
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    });
  }

  function toggleCorrection(kind: CorrectionKind) {
    setActiveCorrection((current) => {
      if (current === kind) return null;
      // Always refetch on activation (not just the first time) -- a previous activation earlier
      // in this same Zoom session may have committed edits (corner drags, crop-frame drags) that
      // a stale cached geometryAux/framingAux wouldn't reflect, e.g. re-showing a straightened
      // photo as if it were still neutral after Geometry was toggled off and back on. Nulling the
      // old value out first (rather than leaving it until the fetch resolves) avoids briefly
      // mounting GeometryToolStage/CropToolStage with stale initialValues -- their internal quad/
      // crop-box state is seeded once from props and won't re-sync on its own.
      if (kind === "geometry") {
        setGeometryAux(null);
        loadGeometryAux();
      }
      if (kind === "framing") {
        setFramingAux(null);
        loadFramingAux();
      }
      return kind;
    });
  }

  function handleGeometryCommitParameter(paramIdentifier: string, value: number) {
    trackCommit(
      api
        .setAuxiliaryZoomParameter(sessionId, "geometry", paramIdentifier, value)
        .catch((err) => setError(err instanceof Error ? err.message : String(err))),
    );
  }

  function handleFramingCommitParameter(paramIdentifier: string, value: number) {
    trackCommit(
      api
        .setAuxiliaryZoomParameter(sessionId, "framing", paramIdentifier, value)
        .catch((err) => setError(err instanceof Error ? err.message : String(err))),
    );
  }

  /** Builds a MaskValues record from zoomState's own sliders -- `useDefaults` selects between the
  currently-EFFECTIVE value (sliderValues override, else the slider's live `value`) and each
  field's own declared `default` (the default centered rectangle). Only ever called with
  `useDefaults=true` now (handleReset's mask branch) -- the initial seed on Zoom-open reads
  straight from the API response instead (the effect above), since maskPoints/maskFeather/
  maskInvert are lifted state now, not a mounted component's own initial props. */
  function maskValuesFromZoomState(useDefaults: boolean, prefix = ""): MaskValues {
    if (!zoomState) return { points: [], feather: 2, invert: false };
    const byId: Record<string, number> = {};
    zoomState.sliders.forEach((s) => {
      byId[s.identifier] = useDefaults ? s.default : sliderValues[s.identifier] ?? s.value;
    });
    return maskValuesFromById(byId, prefix);
  }

  /** A single batched write (up to 65 scalar keys: mask_point_count + every coordinate +
  feather/invert) per vertex-commit or feather/invert change (called via maskCommit below),
  mirroring handleReset's own use of api.setZoomParameters. */
  function handleMaskCommit(updates: Array<{ identifier: string; value: number }>) {
    setSliderValues((prev) => {
      const next = { ...prev };
      updates.forEach((u) => {
        next[u.identifier] = u.value;
      });
      return next;
    });
    const seq = ++requestSeq.current;
    trackCommit(applyRenderResponse(seq, api.setZoomParameters(sessionId, updates)));
  }

  /** Commits the given shape/feather/invert via the batched write above -- called at the end of
  every mask gesture (vertex drag release, midpoint insert, vertex removal, feather/invert change).
  Always addressed to the mask currently open in the editor, never to another one. */
  function maskCommit(nextPoints: MaskPoint[], nextFeather: number, nextInvert: boolean) {
    if (!activeMask) return;
    handleMaskCommit(
      maskValuesToUpdates({ points: nextPoints, feather: nextFeather, invert: nextInvert }, activeMask.prefix),
    );
  }

  function maskFractionFromPointer(event: ReactPointerEvent): MaskPoint | null {
    const rect = maskPhotoRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    return {
      x: clampMaskFraction((event.clientX - rect.left) / rect.width),
      y: clampMaskFraction((event.clientY - rect.top) / rect.height),
    };
  }

  function handleMaskVertexPointerDown(index: number, event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    maskDragIndex.current = index;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  /** A midpoint marker's pointerdown inserts a new vertex there immediately and starts dragging it
  in the same gesture (FR-007) -- release without moving is still a valid subdivision-in-place. */
  function handleMaskMidpointPointerDown(edgeIndex: number, event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    if (maskPoints.length >= MAX_MASK_VERTICES) return;
    const a = maskPoints[edgeIndex];
    const b = maskPoints[(edgeIndex + 1) % maskPoints.length];
    const midpoint: MaskPoint = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const nextPoints = [...maskPoints.slice(0, edgeIndex + 1), midpoint, ...maskPoints.slice(edgeIndex + 1)];
    setMaskPoints(nextPoints);
    maskDragIndex.current = edgeIndex + 1;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleMaskPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const index = maskDragIndex.current;
    if (index === null) return;
    const point = maskFractionFromPointer(event);
    if (!point) return;
    setMaskPoints((prev) => prev.map((p, i) => (i === index ? point : p)));
  }

  function handleMaskPointerUp() {
    if (maskDragIndex.current === null) return;
    maskDragIndex.current = null;
    maskCommit(maskPoints, maskFeather, maskInvert);
  }

  /** Double-clicking a vertex removes it, merging its two adjacent segments -- refuses to go below
  MIN_MASK_VERTICES (FR-009). */
  function handleMaskVertexDoubleClick(index: number) {
    if (maskPoints.length <= MIN_MASK_VERTICES) return;
    const nextPoints = maskPoints.filter((_, i) => i !== index);
    setMaskPoints(nextPoints);
    maskCommit(nextPoints, maskFeather, maskInvert);
  }

  function handleMaskFeatherChange(value: number) {
    setMaskFeather(value);
    maskCommit(maskPoints, value, maskInvert);
  }

  function handleMaskInvertToggle() {
    const next = !maskInvert;
    setMaskInvert(next);
    maskCommit(maskPoints, maskFeather, next);
  }

  /** Color Splash only: clears the active range's zone, returning it to the whole image. Writing
  a vertex count of 0 is what the backend reads as "no zone" (color_splash.py's `_read_mask`);
  the editor then re-seeds a full-frame polygon so there is still something to drag. */
  function handleMaskClearZone() {
    if (!activeMask) return;
    handleMaskCommit([{ identifier: `${activeMask.prefix}mask_point_count`, value: 0 }]);
    setMaskPoints(FULL_FRAME_POINTS);
  }

  /** Invoked by the shared bottom-panel "Appliquer" button while a mask editor is open (see
  handleCorrectionApply) -- every edit is already committed as it happens (maskCommit above), so
  there is nothing left to save here; this just exits mask-edit mode, revealing the compare pane
  again (already showing the up-to-date afterSrc). */
  function handleMaskValidate() {
    setActiveMask(null);
  }

  // --- Vignetting's interactive shape editor (dynamic-aids pass) ----------------------------

  function vignetteFractionFromPointer(event: ReactPointerEvent): { x: number; y: number } | null {
    // Reuses the same photo-bounds ref the split-drag/optical-zoom machinery already uses --
    // the shape overlay is rendered inside this exact box (.zoom-overlay__compare-content).
    const rect = contentRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
  }

  /** A single batched write per drag-release gesture, mirroring handleMaskCommit exactly -- only
  the field(s) actually dragged are committed (center_x+center_y together for a center drag, one
  field for every other handle), matching Geometry's own "commit only what was actually dragged"
  convention. Local state (vignetteValues) is already up to date from the drag itself; this only
  pushes it to the backend. */
  function commitVignetteFields(updates: Array<{ identifier: string; value: number }>) {
    setSliderValues((prev) => {
      const next = { ...prev };
      updates.forEach((u) => {
        next[u.identifier] = u.value;
      });
      return next;
    });
    const seq = ++requestSeq.current;
    trackCommit(applyRenderResponse(seq, api.setZoomParameters(sessionId, updates)));
  }

  function handleVignetteToggleTool(tool: VignetteActiveTool) {
    setVignetteActiveTool((current) => (current === tool ? null : tool));
  }

  function handleVignetteCenterPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    vignetteDragTarget.current = { kind: "center" };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleVignetteDialPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    vignetteDragTarget.current = { kind: "dial" };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleVignetteVertexPointerDown(id: EllipseHandleId, event: ReactPointerEvent<HTMLDivElement>) {
    event.stopPropagation();
    vignetteDragTarget.current = { kind: "vertex", id };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleVignetteBorderPointerDown(id: LineBorderId, event: ReactPointerEvent<SVGLineElement>) {
    event.stopPropagation();
    vignetteDragTarget.current = { kind: "border", id };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  /** Same angle math as GeometryToolStage's angleFromPointer (Math.atan2 relative to the dial's
  own bounding-rect center, 0 = straight up, clockwise-positive) -- but no ±45° clamp: Vignetage's
  rotation_angle spans the full ±180° (a rotated line-band needs it to reach every orientation with
  independent top/bottom offsets, unlike Geometry's bounded perspective correction). */
  function vignetteAngleFromPointer(event: ReactPointerEvent): number | null {
    const rect = vignetteDialRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const dx = event.clientX - centerX;
    const dy = event.clientY - centerY;
    return Math.atan2(dx, -dy) * (180 / Math.PI);
  }

  function handleVignettePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const target = vignetteDragTarget.current;
    if (!target || !vignetteValues) return;

    if (target.kind === "center") {
      const pointer = vignetteFractionFromPointer(event);
      if (!pointer) return;
      const centerX = Math.min(Math.max(pointer.x, -0.5), 1.5);
      const centerY = Math.min(Math.max(pointer.y, -0.5), 1.5);
      setVignetteValues((current) => (current ? { ...current, center_x: centerX, center_y: centerY } : current));
      return;
    }

    if (target.kind === "dial") {
      const angle = vignetteAngleFromPointer(event);
      if (angle !== null) setVignetteValues((current) => (current ? { ...current, rotation_angle: angle } : current));
      return;
    }

    const pointer = vignetteFractionFromPointer(event);
    if (!pointer) return;
    const { dx, dy } = fractionToOffset(pointer.x, pointer.y, vignetteValues.center_x, vignetteValues.center_y);
    const { rx, ry } = imageOffsetToLocal(dx, dy, vignetteValues.rotation_angle, vignetteAspect);

    if (target.kind === "vertex") {
      if (target.id === "e" || target.id === "w") {
        const radiusX = Math.min(Math.max(Math.abs(rx), 0.05), 2.0);
        setVignetteValues((current) => (current ? { ...current, radius_x: radiusX } : current));
      } else {
        const radiusY = Math.min(Math.max(Math.abs(ry), 0.05), 2.0);
        setVignetteValues((current) => (current ? { ...current, radius_y: radiusY } : current));
      }
      return;
    }

    if (target.id === "top") {
      const topOffset = Math.min(Math.max(-ry, 0.05), 1.5);
      setVignetteValues((current) => (current ? { ...current, top_offset: topOffset } : current));
    } else {
      const bottomOffset = Math.min(Math.max(ry, 0.05), 1.5);
      setVignetteValues((current) => (current ? { ...current, bottom_offset: bottomOffset } : current));
    }
  }

  function handleVignettePointerUp() {
    const target = vignetteDragTarget.current;
    vignetteDragTarget.current = null;
    if (!target || !vignetteValues) return;
    if (target.kind === "center") {
      commitVignetteFields([
        { identifier: "center_x", value: vignetteValues.center_x },
        { identifier: "center_y", value: vignetteValues.center_y },
      ]);
    } else if (target.kind === "dial") {
      commitVignetteFields([{ identifier: "rotation_angle", value: vignetteValues.rotation_angle }]);
    } else if (target.kind === "vertex") {
      const field = target.id === "e" || target.id === "w" ? "radius_x" : "radius_y";
      commitVignetteFields([{ identifier: field, value: vignetteValues[field] }]);
    } else {
      const field = target.id === "top" ? "top_offset" : "bottom_offset";
      commitVignetteFields([{ identifier: field, value: vignetteValues[field] }]);
    }
  }

  function handleCorrectionApply() {
    if (activeMask) {
      handleMaskValidate();
      return;
    }
    const ref = activeCorrection === "geometry" ? geometryStageRef : activeCorrection === "framing" ? cropStageRef : null;
    if (!ref) return;
    setCorrectionApplying(true);
    // Waits for the last corner/rotation-drag commit to land before rendering "after" -- otherwise
    // a fast click right after releasing a drag can render against the PREVIOUS value.
    pendingCommit.current
      .then(() => ref.current?.apply())
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setCorrectionApplying(false));
  }

  /** Applies a render response via setAfterSrc -- but only if `seq` (captured by the caller via
  ++requestSeq.current at the moment ITS OWN request was issued) still matches requestSeq.current
  when the response arrives, i.e. no newer request (from ANY of this file's render-triggering call
  sites -- plain-slider debounce/settle, mask/vignette gesture commits, Réinitialiser, all share
  this one counter) has been issued since. Shared by every one of them so the guard is applied
  uniformly, not just on the two-tier debounce path that motivated adding it (PERF-ZOOM-RENDER-
  PLAN.md étape 2) -- this codebase has twice shipped a bug from exactly this class of unordered
  async requests (see memory zoom-overlay-commit-race-condition-fix /
  appshell-export-race-condition-fix), so every setAfterSrc write here is guarded the same way. */
  function applyRenderResponse(seq: number, promise: Promise<Blob | undefined>, isReducedPreview: boolean = false) {
    return promise
      .then((blob) => {
        if (seq !== requestSeq.current || !blob) return;
        if (afterBlobUrl.current) URL.revokeObjectURL(afterBlobUrl.current);
        const url = URL.createObjectURL(blob);
        afterBlobUrl.current = url;
        afterImageIsReducedPreview.current = isReducedPreview;
        setAfterSrc(url);
      })
      .catch((err) => {
        if (seq !== requestSeq.current) return;
        setError(err instanceof Error ? err.message : String(err));
      });
  }

  /** Issues one render request and applies its result through applyRenderResponse above.
  `maxDimension` omitted means full resolution. */
  function runParameterUpdate(updates: Array<[string, number]>, maxDimension?: number) {
    const seq = ++requestSeq.current;
    const response = Promise.all(
      updates.map(([identifier, value]) => api.setZoomParameter(sessionId, identifier, value, maxDimension)),
    ).then((blobs) => blobs[blobs.length - 1]);
    return applyRenderResponse(seq, response, maxDimension != null);
  }

  /** PERF-ZOOM-RENDER-PLAN.md étape 2: fires a fast reduced-resolution preview after
  PARAMETER_UPDATE_DEBOUNCE_MS of inactivity, then the real full-resolution render after
  FULL_RESOLUTION_SETTLE_MS -- both timers are reset on every call, so continuous dragging (ticks
  closer together than the debounce) fires neither until the user actually pauses or stops. */
  function scheduleParameterUpdate(updates: Array<[string, number]>) {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    if (fullResSettleTimer.current) clearTimeout(fullResSettleTimer.current);
    pendingSliderUpdate.current = updates;

    debounceTimer.current = setTimeout(() => {
      debounceTimer.current = null;
      if (pendingSliderUpdate.current) trackCommit(runParameterUpdate(pendingSliderUpdate.current, ZOOM_PREVIEW_MAX_DIMENSION_PX));
    }, PARAMETER_UPDATE_DEBOUNCE_MS);

    fullResSettleTimer.current = setTimeout(() => {
      fullResSettleTimer.current = null;
      const toSend = pendingSliderUpdate.current;
      pendingSliderUpdate.current = null;
      if (toSend) trackCommit(runParameterUpdate(toSend));
    }, FULL_RESOLUTION_SETTLE_MS);
  }

  /** Fires the pending plain-slider write (if one hasn't landed at full resolution yet) immediately
  instead of waiting out FULL_RESOLUTION_SETTLE_MS -- "Valider" must call this before confirming, or
  a slider dragged just before clicking Valider could be silently dropped (neither timer gets a
  chance to fire once the Zoom overlay unmounts on confirm). Always sends at full resolution,
  regardless of which tier's timer was still pending -- Valider must never finalize on a reduced
  preview. */
  function flushPendingSliderUpdate() {
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
      debounceTimer.current = null;
    }
    if (fullResSettleTimer.current) {
      clearTimeout(fullResSettleTimer.current);
      fullResSettleTimer.current = null;
    }
    const toSend = pendingSliderUpdate.current;
    pendingSliderUpdate.current = null;
    if (toSend) trackCommit(runParameterUpdate(toSend));
  }

  function handleSliderChange(slider: ZoomSlider, value: number) {
    setSliderValues((prev) => ({ ...prev, [slider.identifier]: value }));
    scheduleParameterUpdate([[slider.identifier, value]]);
  }

  /** Generalized handler behind every COLOR_WHEEL_PAIRS entry -- `satScale` converts the wheel's
  0-100 radius back down to the underlying slider's own native range (1 for Monochrome's
  tint_saturation, already 0-100; 5 for Light's split-tone strength, 0-20%). */
  function handleColorWheelChange(hueIdentifier: string, satIdentifier: string, satScale: number, hue: number, radius: number) {
    const saturationValue = radius / satScale;
    setSliderValues((prev) => ({ ...prev, [hueIdentifier]: hue, [satIdentifier]: saturationValue }));
    scheduleParameterUpdate([
      [hueIdentifier, hue],
      [satIdentifier, saturationValue],
    ]);
  }

  function handleToggleClick(slider: ZoomSlider) {
    const current = sliderValues[slider.identifier] ?? slider.value;
    handleSliderChange(slider, current >= 0.5 ? 0 : 1);
  }

  /** filter_color (B&W row, 2026-08-04) is a mutually-exclusive 0..4 categorical dial (0=Aucun,
  1..4=Yellow/Red/Green/Blue -- see film.py's _resolve_filter_weights), but a raw numeric slider
  showing "1"/"2"/"3"/"4" gave no way to tell which number was which color (user feedback) -- this
  toggles one of FILTER_COLOR_OPTIONS on (turning any other off, since only one filter is ever
  active) or, clicking the already-active one, back off to 0. */
  function handleFilterColorClick(slider: ZoomSlider, value: number) {
    const current = sliderValues[slider.identifier] ?? slider.value;
    handleSliderChange(slider, current === value ? 0 : value);
  }

  function handleHueChange(rangeIdentifier: string, hue: number) {
    setHueRangeValues((prev) => ({ ...prev, [rangeIdentifier]: { hue, feather: prev[rangeIdentifier]?.feather ?? 30 } }));
    scheduleParameterUpdate([[`${rangeIdentifier}_hue_center`, hue]]);
  }

  function handleFeatherChange(rangeIdentifier: string, feather: number) {
    setHueRangeValues((prev) => ({ ...prev, [rangeIdentifier]: { hue: prev[rangeIdentifier]?.hue ?? 0, feather } }));
    scheduleParameterUpdate([[`${rangeIdentifier}_feather`, feather]]);
  }

  // Color Splash's per-range ColorWheel: radius drives `{range}_saturation_boost` (0-200%,
  // rescaled 1:2 from the wheel's 0-100% radius) while the existing numeric slider for it
  // stays visible too (coexistence, same principle as Monochrome Tone's own wheel).
  function handleColorSplashWheelChange(rangeIdentifier: string, boostIdentifier: string | undefined, hue: number, radius: number) {
    setHueRangeValues((prev) => ({ ...prev, [rangeIdentifier]: { hue, feather: prev[rangeIdentifier]?.feather ?? 30 } }));
    const updates: Array<[string, number]> = [[`${rangeIdentifier}_hue_center`, hue]];
    if (boostIdentifier) {
      const boost = radius * 2;
      setSliderValues((prev) => ({ ...prev, [boostIdentifier]: boost }));
      updates.push([boostIdentifier, boost]);
    }
    scheduleParameterUpdate(updates);
  }

  function handleReset() {
    // When a correction is active, "Réinitialiser" targets IT (mirrors GeometryCanvas's/
    // CropCanvas's own Réinitialiser exactly) -- this row's own sliders keep their unmodified
    // values until the user switches back to editing them directly.
    if (activeCorrection === "geometry") {
      geometryStageRef.current?.reset();
      return;
    }
    if (activeCorrection === "framing") {
      cropStageRef.current?.reset();
      return;
    }
    if (activeMask) {
      // Targets the open mask only, at its own prefix -- for Color Splash that means a vertex
      // count back to 0 (zone cleared, range applies to the whole image), so re-seed the editor's
      // visible polygon with the full frame rather than leaving it with nothing to drag.
      const defaults = maskValuesFromZoomState(true, activeMask.prefix);
      setMaskPoints(defaults.points.length >= MIN_MASK_VERTICES ? defaults.points : FULL_FRAME_POINTS);
      setMaskFeather(defaults.feather);
      setMaskInvert(defaults.invert);
      handleMaskCommit(maskValuesToUpdates(defaults, activeMask.prefix));
      return;
    }
    if (!zoomState) return;
    // Both timers AND the pending payload must be cleared, not just debounceTimer -- otherwise a
    // slider dragged right before clicking Réinitialiser could leave fullResSettleTimer armed,
    // which would fire shortly after with the PRE-reset value and race against this very reset
    // (PERF-ZOOM-RENDER-PLAN.md étape 2).
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
      debounceTimer.current = null;
    }
    if (fullResSettleTimer.current) {
      clearTimeout(fullResSettleTimer.current);
      fullResSettleTimer.current = null;
    }
    pendingSliderUpdate.current = null;
    setSliderValues(Object.fromEntries(zoomState.sliders.map((s) => [s.identifier, s.default])));
    if (vignetteShape) {
      setVignetteValues(vignetteValuesFromById(Object.fromEntries(zoomState.sliders.map((s) => [s.identifier, s.default]))));
    }
    setHueRangeValues(
      Object.fromEntries(zoomState.hue_ranges.map((r) => [r.identifier, { hue: r.hue_default, feather: r.feather_default }])),
    );
    const updates: Array<{ identifier: string; value: number }> = [
      ...zoomState.sliders.map((s) => ({ identifier: s.identifier, value: s.default })),
      ...zoomState.hue_ranges.flatMap((r) => [
        { identifier: `${r.identifier}_hue_center`, value: r.hue_default },
        { identifier: `${r.identifier}_feather`, value: r.feather_default },
      ]),
    ];
    const seq = ++requestSeq.current;
    applyRenderResponse(seq, api.setZoomParameters(sessionId, updates));
  }

  function handleConfirm() {
    // Flush any still-debounced plain-slider write, then wait for every other fire-and-forget
    // commit (Geometry/Cadrage/Masque Sujet/Vignette) to land -- otherwise the very last edit made
    // right before clicking "Valider" can be silently lost or raced, confirming a stale recipe.
    flushPendingSliderUpdate();
    pendingCommit.current
      .then(() => api.confirmZoom(sessionId))
      .then((rows) => onConfirm(rows))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }

  function handleCancel() {
    api
      .cancelZoom(sessionId)
      .then((rows) => onCancel(rows))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }

  function updateSplitFromEvent(event: ReactPointerEvent) {
    // Reads the CONTENT box (the actual, possibly-zoomed photo), not the viewport -- keeps the
    // split ratio stable relative to the image itself regardless of zoom/scroll position.
    const rect = contentRef.current?.getBoundingClientRect();
    if (!rect) return;
    const ratio = ((event.clientX - rect.left) / rect.width) * 100;
    setSplit(Math.max(0, Math.min(100, ratio)));
  }

  function handleSplitPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    draggingSplit.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    updateSplitFromEvent(event);
  }

  function handleSplitPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (draggingSplit.current) updateSplitFromEvent(event);
  }

  function handleSplitPointerUp() {
    draggingSplit.current = false;
  }

  const rangeGroups = zoomState ? groupHueRanges(zoomState.hue_ranges, zoomState.sliders) : [];
  const groupedSliderIdentifiers = new Set(
    rangeGroups.flatMap((g) => [g.enabledSlider?.identifier, g.boostSlider?.identifier].filter(Boolean) as string[]),
  );
  // The 7 geometry fields Vignetage's shape editor drives directly (everything but feather_width)
  // are hidden from the flat slider list -- they're edited via the interactive overlay instead,
  // not shown a second time as plain drag sliders. Polygon-mask parameters are hidden for the very
  // same reason, and here it is load-bearing rather than cosmetic: Color Splash has no
  // SLIDER_GROUPS allow-list (see FILM_SLIDER_GROUPS' own note), so it renders EVERY ungrouped
  // slider in "Réglages globaux" -- without this filter its 201 zone parameters (3 ranges x
  // count/feather/invert/32 vertex pairs) would all show up there as raw sliders. Light is already
  // shielded by LIGHT_SLIDER_GROUPS being an allow-list; filtering here too just makes the rule
  // explicit for both.
  const ungroupedSliders = (zoomState?.sliders.filter((s) => !groupedSliderIdentifiers.has(s.identifier)) ?? []).filter(
    (s) => !(vignetteShape && VIGNETTE_SHAPE_GEOMETRY_FIELDS.has(s.identifier)) && !isMaskParameter(s.identifier),
  );
  const ringHandles: HueRingHandle[] = rangeGroups.map(({ hueRange, enabledSlider }) => ({
    identifier: hueRange.identifier,
    hue: hueRangeValues[hueRange.identifier]?.hue ?? hueRange.hue_value,
    feather: hueRangeValues[hueRange.identifier]?.feather ?? hueRange.feather_value,
    enabled: enabledSlider ? (sliderValues[enabledSlider.identifier] ?? enabledSlider.value) >= 0.5 : false,
  }));
  const isColorSplash = rowLabel === "Color Splash";
  const isLight = rowLabel === "Light";
  const sliderGroupMap = SLIDER_GROUPS[rowLabel];
  // Light only: the accordion shows exactly one region's fields at a time (Global · Sujet · Fond,
  // regionTab) -- every other row's ungroupedSliders passes through unfiltered (regionOf is
  // "global" for every non-prefixed identifier, i.e. every other addon's own sliders).
  const regionFilteredSliders = isLight
    ? ungroupedSliders.filter((s) => regionOf(s.identifier) === regionTab)
    : ungroupedSliders;

  function isModified(slider: ZoomSlider) {
    return (sliderValues[slider.identifier] ?? slider.value) !== slider.default;
  }

  /** Geometry/Cadrage toggle row -- extracted so Light can place it AFTER its own Global/Sujet/
  Fond tabs (user request 2026-07-28) while every other row keeps it at the top of the panel,
  without duplicating this JSX at both call sites. */
  function renderCorrections() {
    return (
      <div className="zoom-overlay__corrections">
        {(Object.keys(CORRECTION_LABELS) as CorrectionKind[]).map((kind) => (
          <div key={kind} className="zoom-overlay__slider-row">
            <div className="zoom-overlay__slider-header">
              <span className="zoom-overlay__slider-label">{CORRECTION_LABELS[kind]}</span>
              <button
                type="button"
                className={`zoom-overlay__toggle${activeCorrection === kind ? " zoom-overlay__toggle--on" : ""}`}
                onClick={() => toggleCorrection(kind)}
                aria-label={
                  activeCorrection === kind ? `Désactiver ${CORRECTION_LABELS[kind]}` : `Activer ${CORRECTION_LABELS[kind]}`
                }
              >
                {activeCorrection === kind ? "×" : "+"}
              </button>
            </div>
          </div>
        ))}
      </div>
    );
  }

  /** The `+`/`×` row opening one mask's polygon editor -- same shape and classes as Light's own
  "Masque sujet" row and as renderCorrections' Geometry/Cadrage rows, so all three read alike.
  `prefix` identifies which mask (Color Splash's "range_N_"); `rangeLabel` only feeds the
  accessible name, since the enclosing section title already names the interval on screen. */
  function renderZoneToggle(prefix: string, rangeLabel: string) {
    const open = activeMask?.prefix === prefix;
    return (
      <div className="zoom-overlay__slider-row">
        <div className="zoom-overlay__slider-header">
          <span className="zoom-overlay__slider-label">Zone d'application</span>
          <button
            type="button"
            className={`zoom-overlay__toggle${open ? " zoom-overlay__toggle--on" : ""}`}
            onClick={() => handleToggleMask(prefix, `Zone — ${rangeLabel}`)}
            aria-label={open ? `Fermer la zone de ${rangeLabel}` : `Modifier la zone de ${rangeLabel}`}
          >
            {open ? "×" : "+"}
          </button>
        </div>
      </div>
    );
  }

  function renderSlider(slider: ZoomSlider) {
    if (slider.identifier === "filter_color") {
      const current = sliderValues[slider.identifier] ?? slider.value;
      return (
        <div key={slider.identifier} className="zoom-overlay__slider-row zoom-overlay__filter-color-buttons">
          {FILTER_COLOR_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`zoom-overlay__filter-color-button${current === option.value ? " zoom-overlay__filter-color-button--on" : ""}`}
              onClick={() => handleFilterColorClick(slider, option.value)}
              aria-pressed={current === option.value}
            >
              {option.label}
            </button>
          ))}
        </div>
      );
    }
    if (isBinaryToggle(slider)) {
      return (
        <div key={slider.identifier} className="zoom-overlay__slider-row">
          <div className="zoom-overlay__slider-header">
            <span className="zoom-overlay__slider-label">{slider.label}</span>
            <button
              type="button"
              className={`zoom-overlay__toggle${(sliderValues[slider.identifier] ?? slider.value) >= 0.5 ? " zoom-overlay__toggle--on" : ""}`}
              onClick={() => handleToggleClick(slider)}
            >
              {(sliderValues[slider.identifier] ?? slider.value) >= 0.5 ? "×" : "+"}
            </button>
          </div>
        </div>
      );
    }
    return (
      <div key={slider.identifier} className="zoom-overlay__slider-row">
        <div className="zoom-overlay__slider-header">
          <span className="zoom-overlay__slider-label">{slider.label}</span>
          <span className="zoom-overlay__slider-value">
            {formatSliderValue(slider, sliderValues[slider.identifier] ?? slider.value)}
          </span>
        </div>
        <input
          type="range"
          min={slider.minimum}
          max={slider.maximum}
          step={slider.step}
          value={sliderValues[slider.identifier] ?? slider.value}
          onChange={(event) => handleSliderChange(slider, Number(event.target.value))}
        />
      </div>
    );
  }

  /** The enable toggle + (when enabled) feather/boost rows for one hue-range group -- shared
  between the flat fallback rendering (any future addon with hue ranges but no dedicated grouping)
  and Color Splash's per-interval CollapsibleSection body. `showLabel` repeats the range's own
  label in the toggle row; Color Splash's version omits it since the enclosing section's title
  already names the interval. */
  function renderRangeGroupContents(
    { hueRange, enabledSlider, boostSlider }: ReturnType<typeof groupHueRanges>[number],
    showLabel: boolean,
  ) {
    const enabled = enabledSlider ? (sliderValues[enabledSlider.identifier] ?? enabledSlider.value) >= 0.5 : false;
    const feather = hueRangeValues[hueRange.identifier]?.feather ?? hueRange.feather_value;
    // Whether this range declares its own spatial application zone (Color Splash, 2026-08-24) --
    // detected by the presence of the polygon's own vertex-count parameter, the same
    // convention-not-identifier approach as isBinaryToggle/groupHueRanges above, so a future addon
    // declaring `${range}_mask_*` gets the affordance for free. Only offered for an ENABLED range:
    // a zone restricting a range that colorizes nothing would have no observable effect.
    const hasZone = zoomState?.sliders.some((s) => s.identifier === `${hueRange.identifier}_mask_point_count`) ?? false;
    return (
      <>
        <div className="zoom-overlay__slider-row">
          <div className="zoom-overlay__slider-header">
            <span className="zoom-overlay__slider-label">{showLabel ? hueRange.label : "Actif"}</span>
            {enabledSlider && (
              <button
                type="button"
                className={`zoom-overlay__toggle${enabled ? " zoom-overlay__toggle--on" : ""}`}
                onClick={() => handleToggleClick(enabledSlider)}
                aria-label={enabled ? `Désactiver ${hueRange.label}` : `Activer ${hueRange.label}`}
              >
                {enabled ? "×" : "+"}
              </button>
            )}
          </div>
        </div>
        {enabled && (
          <>
            <div className="zoom-overlay__slider-row">
              <div className="zoom-overlay__slider-header">
                <span className="zoom-overlay__slider-label">Adoucissement</span>
                <span className="zoom-overlay__slider-value">{Math.round(feather)}</span>
              </div>
              <input
                type="range"
                min={hueRange.feather_minimum}
                max={hueRange.feather_maximum}
                step={1}
                value={feather}
                onChange={(event) => handleFeatherChange(hueRange.identifier, Number(event.target.value))}
              />
            </div>
            {boostSlider && renderSlider(boostSlider)}
            {hasZone && renderZoneToggle(`${hueRange.identifier}_`, hueRange.label)}
          </>
        )}
      </>
    );
  }

  function isRangeGroupModified({ hueRange, enabledSlider, boostSlider }: ReturnType<typeof groupHueRanges>[number]) {
    const hue = hueRangeValues[hueRange.identifier]?.hue ?? hueRange.hue_value;
    const feather = hueRangeValues[hueRange.identifier]?.feather ?? hueRange.feather_value;
    return (
      (enabledSlider ? isModified(enabledSlider) : false) ||
      hue !== hueRange.hue_default ||
      feather !== hueRange.feather_default ||
      (boostSlider ? isModified(boostSlider) : false)
    );
  }

  return (
    <div className="zoom-overlay">
      <div className="zoom-overlay__main">
        <div className="zoom-overlay__header">
          <span className="zoom-overlay__category">{rowLabel.toUpperCase()}</span>
          <span className="zoom-overlay__option">{vignetteDisplayText(identifier)}</span>
          <div className="zoom-overlay__spacer" />
          <button type="button" className="zoom-overlay__close" onClick={handleCancel}>
            <CloseIcon />
            Fermer
          </button>
        </div>
        {error && <div className="zoom-overlay__error">{error}</div>}
        {activeCorrection === "geometry" && geometryAux ? (
          <GeometryToolStage
            ref={geometryStageRef}
            sessionId={sessionId}
            photoSrc={geometryAux.photoSrc}
            initialValues={geometryAux.values}
            defaultValues={geometryAux.defaults}
            zoomBounds={zoomBounds}
            onCommitParameter={handleGeometryCommitParameter}
          />
        ) : activeCorrection === "framing" && framingAux ? (
          <CropToolStage
            ref={cropStageRef}
            sessionId={sessionId}
            photoSrc={framingAux.photoSrc}
            imageSize={framingAux.imageSize}
            initialValues={framingAux.values}
            defaultValues={framingAux.defaults}
            overlays={framingAux.overlays}
            zoomBounds={zoomBounds}
            onCommitParameter={handleFramingCommitParameter}
          />
        ) : activeCorrection ? (
          <div className="zoom-overlay__compare zoom-overlay__compare--loading">Chargement…</div>
        ) : (
          <>
            <div className="zoom-overlay__compare-wrap">
              <div
                ref={setCompareRef}
                className="zoom-overlay__compare"
                onPointerDown={activeMask ? undefined : handleSplitPointerDown}
                onPointerMove={activeMask ? undefined : handleSplitPointerMove}
                onPointerUp={activeMask ? undefined : handleSplitPointerUp}
                onPointerLeave={activeMask ? undefined : handleSplitPointerUp}
              >
                <div
                  ref={contentRef}
                  className="zoom-overlay__compare-content"
                  style={
                    naturalSize && zoomPercent !== null
                      ? {
                          width: `${Math.round((naturalSize.width * zoomPercent) / 100)}px`,
                          height: `${Math.round((naturalSize.height * zoomPercent) / 100)}px`,
                        }
                      : undefined
                  }
                >
                  {activeMask ? (
                    <SubjectMaskLayer
                      photoSrc={beforeSrc}
                      points={maskPoints}
                      featherRadiusPx={
                        naturalSize && zoomPercent !== null
                          ? (maskFeather / 100) * Math.min((naturalSize.width * zoomPercent) / 100, (naturalSize.height * zoomPercent) / 100)
                          : 0
                      }
                      photoRef={maskPhotoRef}
                      onVertexPointerDown={handleMaskVertexPointerDown}
                      onVertexDoubleClick={handleMaskVertexDoubleClick}
                      onMidpointPointerDown={handleMaskMidpointPointerDown}
                      onPointerMove={handleMaskPointerMove}
                      onPointerUp={handleMaskPointerUp}
                    />
                  ) : (
                    <>
                      {afterSrc && (
                        <div className="zoom-overlay__pane">
                          <img
                            src={afterSrc} alt="" className="zoom-overlay__pane-img" draggable={false}
                            onLoad={handleAfterPaneLoad} data-testid="zoom-overlay-after-image"
                          />
                        </div>
                      )}
                      {beforeSrc && (
                        <div className="zoom-overlay__pane-clip" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}>
                          <div className="zoom-overlay__pane">
                            <img src={beforeSrc} alt="" className="zoom-overlay__pane-img" draggable={false} />
                          </div>
                        </div>
                      )}
                      <div className="zoom-overlay__badge zoom-overlay__badge--before">AVANT</div>
                      <div className="zoom-overlay__badge zoom-overlay__badge--after">APRÈS</div>
                      <div className="zoom-overlay__handle" style={{ left: `${split}%` }}>
                        <div className="zoom-overlay__handle-grip">
                          <SplitHandleIcon />
                        </div>
                      </div>
                      {vignetteShape && vignetteValues && vignetteAidsEnabled && (
                        <VignetteShapeOverlay
                          shape={vignetteShape}
                          values={vignetteValues}
                          aspect={vignetteAspect}
                          featherRadiusPx={
                            naturalSize && zoomPercent !== null
                              ? ((sliderValues.feather_width ?? vignetteValues.feather_width) / 100) *
                                Math.min((naturalSize.width * zoomPercent) / 100, (naturalSize.height * zoomPercent) / 100)
                              : 0
                          }
                          activeTool={vignetteActiveTool}
                          dialRef={vignetteDialRef}
                          onCenterPointerDown={handleVignetteCenterPointerDown}
                          onDialPointerDown={handleVignetteDialPointerDown}
                          onVertexPointerDown={handleVignetteVertexPointerDown}
                          onBorderPointerDown={handleVignetteBorderPointerDown}
                          onPointerMove={handleVignettePointerMove}
                          onPointerUp={handleVignettePointerUp}
                        />
                      )}
                    </>
                  )}
                </div>
              </div>
              {renderPanZones()}
              {activeMask && (
                <SubjectMaskControls
                  feather={maskFeather}
                  invert={maskInvert}
                  onFeatherChange={handleMaskFeatherChange}
                  onInvertToggle={handleMaskInvertToggle}
                  // Only a per-range zone has a "no zone" resting state to return to; Light's
                  // subject mask has none, so it gets no such button (prefix "" === Light).
                  onClearZone={activeMask.prefix ? handleMaskClearZone : undefined}
                />
              )}
              {vignetteShape && vignetteValues && vignetteAidsEnabled && (
                <VignetteShapeControls activeTool={vignetteActiveTool} onToggleTool={handleVignetteToggleTool} />
              )}
            </div>
            {/* Optical zoom (display-only magnification, feature 038 in the old Qt UI) -- scoped
            to this plain compare view only (Geometry/Cadrage's own stages don't get it, see the
            constants block above), but now also active in mask-edit mode -- it's the same shared
            zoomable viewport as the plain compare view, see .zoom-overlay__compare-content above. */}
            <div className="zoom-overlay__optical-zoom">
              <span className="zoom-overlay__optical-zoom-label">Zoom</span>
              <button type="button" className="zoom-overlay__optical-zoom-button" onClick={handleZoomOut} aria-label="Zoom arrière">
                −
              </button>
              <input
                type="range"
                className="zoom-overlay__optical-zoom-slider"
                min={zoomBounds.min}
                max={zoomBounds.max}
                step={1}
                value={zoomPercent ?? zoomBounds.min}
                onChange={(event) => handleZoomSliderChange(Number(event.target.value))}
              />
              <button type="button" className="zoom-overlay__optical-zoom-button" onClick={handleZoomIn} aria-label="Zoom avant">
                +
              </button>
              <input
                type="text"
                inputMode="numeric"
                className="zoom-overlay__optical-zoom-input"
                value={zoomInputText}
                onChange={(event) => setZoomInputText(event.target.value)}
                onBlur={commitZoomInput}
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.currentTarget.blur();
                }}
                aria-label="Pourcentage de zoom"
              />
              <span className="zoom-overlay__optical-zoom-percent-sign">%</span>
              <button type="button" className="zoom-overlay__optical-zoom-fit" onClick={handleZoomFit}>
                Ajuster
              </button>
            </div>
          </>
        )}
      </div>

      <div className="zoom-overlay__panel">
        {CORRECTION_ROWS[rowLabel] && !isLight && renderCorrections()}
        {vignetteShape && (
          <div className="zoom-overlay__corrections">
            <div className="zoom-overlay__slider-row">
              <div className="zoom-overlay__slider-header">
                <span className="zoom-overlay__slider-label">Aides dynamiques</span>
                <button
                  type="button"
                  className={`zoom-overlay__toggle${vignetteAidsEnabled ? " zoom-overlay__toggle--on" : ""}`}
                  onClick={() => setVignetteAidsEnabled((v) => !v)}
                  aria-label={vignetteAidsEnabled ? "Désactiver les aides dynamiques" : "Activer les aides dynamiques"}
                >
                  {vignetteAidsEnabled ? "×" : "+"}
                </button>
              </div>
            </div>
          </div>
        )}
        {isLight && (
          <div className="zoom-overlay__region-controls">
            <div className="zoom-overlay__region-tabs">
              {(["global", "subject", "background"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={`zoom-overlay__region-tab${regionTab === tab ? " zoom-overlay__region-tab--active" : ""}`}
                  onClick={() => {
                    setRegionTab(tab);
                    // "Masque sujet" is only reachable from Sujet/Fond, Geometry/Cadrage only from
                    // Global -- closing the other context on switch avoids leaving it active with
                    // no visible toggle in the panel to turn it back off from the new tab.
                    if (tab === "global") {
                      if (activeMask) setActiveMask(null);
                    } else if (activeCorrection) {
                      setActiveCorrection(null);
                    }
                  }}
                >
                  {tab === "global" ? "Global" : tab === "subject" ? "Sujet" : "Fond"}
                </button>
              ))}
            </div>
            {regionTab !== "global" && (
              <div className="zoom-overlay__slider-row">
                <div className="zoom-overlay__slider-header">
                  <span className="zoom-overlay__slider-label">Masque sujet</span>
                  <button
                    type="button"
                    className={`zoom-overlay__toggle${activeMask ? " zoom-overlay__toggle--on" : ""}`}
                    onClick={() => handleToggleMask("", "Masque sujet")}
                    aria-label={activeMask ? "Désactiver le masque sujet" : "Activer le masque sujet"}
                  >
                    {activeMask ? "×" : "+"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
        {isLight && regionTab === "global" && CORRECTION_ROWS[rowLabel] && renderCorrections()}
        <div className="zoom-overlay__sliders">
          {isColorSplash ? (
            <>
              {rangeGroups.map((group, index) => (
                <CollapsibleSection
                  key={group.hueRange.identifier}
                  title={group.hueRange.label}
                  hasModifiedValue={isRangeGroupModified(group)}
                >
                  <ColorWheel
                    hue={ringHandles[index].hue}
                    saturation={(group.boostSlider ? sliderValues[group.boostSlider.identifier] ?? group.boostSlider.value : 100) / 2}
                    feather={ringHandles[index].feather}
                    onChange={(hue, radius) =>
                      handleColorSplashWheelChange(group.hueRange.identifier, group.boostSlider?.identifier, hue, radius)
                    }
                  />
                  {renderRangeGroupContents(group, false)}
                </CollapsibleSection>
              ))}
              {ungroupedSliders.length > 0 && (
                <CollapsibleSection title="Réglages globaux" hasModifiedValue={ungroupedSliders.some(isModified)}>
                  {ungroupedSliders.map(renderSlider)}
                </CollapsibleSection>
              )}
            </>
          ) : sliderGroupMap ? (
            GROUP_ORDER[rowLabel]
              .map((groupName) => ({
                groupName,
                groupSliders: regionFilteredSliders.filter((s) => sliderGroupMap[baseIdOf(s.identifier)] === groupName),
              }))
              .filter(({ groupSliders }) => groupSliders.length > 0)
              .map(({ groupName, groupSliders }) => {
                const wheelPairs = (COLOR_WHEEL_PAIRS[rowLabel] ?? []).filter((pair) => pair.group === groupName);
                return (
                  <CollapsibleSection key={groupName} title={groupName} hasModifiedValue={groupSliders.some(isModified)}>
                    {wheelPairs.map((pair) => {
                      const hueSlider = groupSliders.find((s) => s.identifier === pair.hue);
                      const saturationSlider = groupSliders.find((s) => s.identifier === pair.sat);
                      if (!hueSlider || !saturationSlider) return null;
                      return (
                        <div key={pair.hue} className="zoom-overlay__color-wheel-group">
                          {wheelPairs.length > 1 && <span className="zoom-overlay__slider-label">{pair.label}</span>}
                          <ColorWheel
                            hue={sliderValues[hueSlider.identifier] ?? hueSlider.value}
                            saturation={(sliderValues[saturationSlider.identifier] ?? saturationSlider.value) * pair.satScale}
                            onChange={(hue, radius) => handleColorWheelChange(pair.hue, pair.sat, pair.satScale, hue, radius)}
                          />
                        </div>
                      );
                    })}
                    {groupSliders.map(renderSlider)}
                  </CollapsibleSection>
                );
              })
          ) : (
            <>
              {rangeGroups.length > 0 && <HueRing handles={ringHandles} onHueChange={handleHueChange} />}
              {rangeGroups.map((group) => (
                <div key={group.hueRange.identifier} className="zoom-overlay__range-group">
                  {renderRangeGroupContents(group, true)}
                </div>
              ))}
              {ungroupedSliders.map(renderSlider)}
            </>
          )}
          {zoomState && zoomState.sliders.length === 0 && rangeGroups.length === 0 && (
            <div className="zoom-overlay__no-sliders">Aucun réglage manuel disponible pour cette ligne.</div>
          )}
        </div>
        <div className="zoom-overlay__spacer" />
        <div className="zoom-overlay__actions">
          <button type="button" className="zoom-overlay__reset" onClick={handleReset}>
            Réinitialiser
          </button>
          {CORRECTION_ROWS[rowLabel] && (
            <button
              type="button"
              className="zoom-overlay__apply"
              onClick={handleCorrectionApply}
              disabled={(activeCorrection === null && activeMask === null) || correctionApplying}
            >
              {correctionApplying ? "Application…" : "Appliquer"}
            </button>
          )}
          <button type="button" className="zoom-overlay__confirm" onClick={handleConfirm}>
            Valider
          </button>
        </div>
      </div>
    </div>
  );
}
