# LumaFlow v1.0 (2026-08-07)
# Addon Film : moteur de gradation parametrique partage par les looks Fujifilm/
# Kodak/Ilford (Classic Chrome, Velvia, Acros, Eterna, etc.), avec filtre B&W et grain.
"""Film addon v1 -- Neutral + Classic Chrome/Velvia/Acros/Astia/Pro Neg. Std/
Eterna/Eterna Bleach Bypass one-click looks with a live intensity blend
(feature 042).

No Qt, no pipeline engine, no persistence module import (same convention as
every module under lumaflow/addons/).

2026-07-16: the original, simpler "Classic Chrome" look (`_classic_chrome`
below) has been retired in favor of "Classic Chrome Pro" (the parametric
grade engine + `_CLASSIC_CHROME_PRO_GRADE` calibration further down), judged
a better match for the real Fujifilm look by the user. Left commented out
rather than deleted, per this project's revision convention (a superseded
look is kept in place, commented out, so it stays restorable at any time),
so it can be restored by uncommenting `_classic_chrome`, its `_LOOK_TRANSFORMS`
entry, and its `ThumbnailPreset` -- plus re-adding `"Classic Chrome"` to
`config_workflow.json`'s `film` row (that list has no comment syntax, so the
one-line restoration lives here instead).

2026-07-16 (later same day): "Velvia Pro" and "Acros Pro" were added the same
way, on the same generic engine -- initially alongside the ORIGINAL
`_velvia`/`_acros` (kept active, not commented out) so both generations could
be compared side by side.

2026-07-16 (still later the same day): after comparison, the user judged the
"*_pro" versions better and asked to retire the originals the same way
Classic Chrome was retired above. `_velvia`/`_acros` below are now commented
out rather than deleted (see the Classic Chrome note above for the exact
restoration steps -- the same pattern applies: uncomment the function, its
`_LOOKS` entry, its `_LOOK_TRANSFORMS` entry, its `ThumbnailPreset`, its
`film_look` equal-channel blend-base branch (for "acros"), plus re-adding
"Velvia"/"Acros" to `config_workflow.json`'s `film` row).

2026-07-16 (still later the same day): four more looks -- "Astia",
"Pro Neg. Std", "Eterna" and "Eterna Bleach Bypass" -- were added, all on the
same generic engine, from externally-supplied calibration tables. Added two
new engine primitives to express them: `hsl_luminance` (a per-hue lightness
shift, the "Luminance HSL" row of the shared parameter scale, unused by any
earlier look) and two more named hue centers, "yellow" and "cyan", in
`_HUE_CENTERS`.

2026-07-17: perf remediation (profiled: ~8s for a single full-resolution look
on a 12MP image). Two fixes, both proven bit-identical (numpy.array_equal)
across every active look, no behavior change:
- `_apply_split_tone` was feeding spatially-constant HSL values through
  `_hsl_to_rgb` at the FULL image size just to get a single RGB triplet (the
  hue/saturation/luminance passed in never varied per pixel) -- accounted for
  ~1.8s of the ~8s (2 of `_hsl_to_rgb`'s 3 calls per render). Now computed on
  a 1x1 array through the same function/formula, then broadcast.
- `_box_blur`'s `_blur_axis` used `numpy.take(cumsum, range(...), axis=axis)`
  for a contiguous range, which forces a fancy-indexing copy; switched to
  plain slice indexing (a view) for the same values.
Combined: ~20-35% faster end-to-end for looks using split-tone (Classic
Chrome Pro, Velvia Pro, Astia, Eterna, Eterna Bleach Bypass), ~5-10% for the
two that don't (Acros Pro, Pro Neg. Std, box-blur fix only).

2026-07-17 (later the same day): the "Pro" suffix was dropped from the three
displayed labels that still had it -- "Classic Chrome Pro"/"Velvia Pro"/
"Acros Pro" are now shown (and configured in config_workflow.json) as plain
"Classic Chrome"/"Velvia"/"Acros". Display only: every internal name --
`_classic_chrome_pro`/`_CLASSIC_CHROME_PRO_GRADE`/the `"classic_chrome_pro"`
`look` key and their Velvia/Acros equivalents, `_LOOKS`, `_LOOK_TRANSFORMS`,
`film_look`'s "acros_pro" branch -- is unchanged; only each active
`ThumbnailPreset`'s `identifier`/`label` fields and the matching entries in
`config_workflow.json`'s `film` row changed. This reuses the exact identifier
strings the ORIGINAL (retired) "Classic Chrome"/"Velvia"/"Acros" looks used
(see the 2026-07-16 notes above) -- restoring any of those retired originals
now requires first renaming this collision away, flagged inline at each
commented-out `ThumbnailPreset` below.

2026-07-25: added "Summer Story" (built on Eterna) and "Inky Depths" (built on
Eterna Bleach Bypass), two externally-supplied Fujifilm-recipe-style looks.
Required three new engine primitives -- `color_chrome_effect`,
`color_chrome_blue` (Off/Weak/Strong tonal-compression dials on saturated
pixels, the latter hue-restricted to blue/cyan) and `dynamic_range`
(DR100/200/400, composed from existing `highlights`/`shadows`/`black_clip`
rather than its own pixel-math) -- documented alongside the other calibration
constants further down. Two fields the source recipes also specify have NO
engine equivalent and are deliberately NOT implemented: EV Comp. (belongs to
the separate "Light" addon, not to Film) and ISO N.R. (an in-camera sensor
noise-reduction setting with no
meaningful equivalent for a filter applied to already-captured photos) -- both
recipes simply omit those fields rather than approximating them. `grain_size`
(pre-existing, internal-only) is used directly by both new looks to express
the recipes' "Grain Effect" size (Small/Large) but deliberately remains absent
from `_ABSOLUTE_FIELD_BOUNDS` -- exposing it as a live slider would reverse
the prior, deliberate decision locked in by
`test_grade_overrides_do_not_touch_monochrome_weights_or_grain_size`.

2026-07-25 (later the same day): added a "Bleach Bypass" workflow row (same
film_look addon, category="film", a second row over the same addon -- no
routing change needed) with five more externally-supplied recipes
("Ecowarrior", "Loki", "Sunset Strip", "Rizzle Clicks", "Glacier Blue") plus a
new base look, "Classic Negative" (a documented approximation, no reference
calibration available -- see `_CLASSIC_NEGATIVE_GRADE`'s own comment), used
as the calibration anchor for four of the five. Eterna Bleach Bypass/Inky
Depths moved from the "Film" row into "Bleach Bypass" at the same time
(config_workflow.json only -- no change to their own calibrations).

2026-07-26: added a new "Monochrome" workflow row (same film_look addon,
category="film", a third row over the same addon) with seven more
externally-supplied recipes: "Monochrome", "Titanium", "Mono Moonlight",
"Underglow", "Gilt Trip", "Milestone", "Quicklime". Three build on a new,
deliberately NOT-standalone-selectable calibration anchor,
`_MONOCHROME_BASE_GRADE` (documented approximation, same treatment as
Classic Negative) -- unlike Classic Negative, nothing in the source recipes
calls for a bare/unadjusted "Monochrome" preset, only the fully-specified
"Monochrome" recipe itself, so no extra ThumbnailPreset was added for the
anchor on its own. Two engine changes support these recipes' "Mono Colour"
(WC/MG) field, absent from every prior look: (1) `_apply_monochrome_grade`
now actually applies `temperature`/`tint` (White Balance) to the source
image before the custom-weighted grayscale conversion -- previously silently
ignored on this path (bug fix, no visible regression: Acros Pro, the only
prior monochrome_weights look, always has temperature=tint=0.0, an exact
no-op); (2) two new fields, `mono_color_wc`/`mono_color_mg` (-20..20, Fuji's
native dial is roughly -9..+9), toning the ALREADY-GRAY image via
`_mono_color_to_temperature_tint` + the existing `_apply_temperature_tint`
primitive -- distinct from White Balance, which affects the pre-conversion
channel weighting, not a post-conversion color cast. Both are zero by
default, so every pre-existing look (including Acros Pro) renders
bit-identically. Milestone's White Balance is a literal Kelvin value
(10000K) rather than a named preset -- `_kelvin_shift_to_temperature_tint`
already accepts any float, `tint_baseline` just stays at its 0.0 default.

2026-07-26 (later the same day): added a new "B&W" workflow row (same
film_look addon, category="film", a fourth row over the same addon) with
three more externally-supplied recipes: "Daido Moriyama", "Newsprint",
"Silvertone 99". "Acros" moved from the "Film" row into "B&W"
(config_workflow.json only -- no change to its own calibration, same
pattern as Eterna Bleach Bypass/Inky Depths's move into "Bleach Bypass").
"Daido Moriyama" is field-for-field identical to "Monochrome" above (same
source recipe values) but was deliberately kept as an independent constant
(`_DAIDO_MORIYAMA_GRADE`, not a shared look key) per explicit user request,
so the two can diverge later without cross-affecting each other -- a
one-off exception to the "reuse, don't duplicate" instinct, made knowingly.
Newsprint/Silvertone 99 build on two new, deliberately NOT-standalone-
selectable calibration anchors, `_ACROS_YELLOW_FILTER_GRADE`/
`_ACROS_GREEN_FILTER_GRADE` (documented approximations -- only
`monochrome_weights` differs from Acros Pro, emulating a physical colored
filter in front of black & white film, distinct from White Balance: a
filter changes which wavelengths feed the grayscale conversion itself,
White Balance shifts color before that conversion).

2026-07-27: retired four recipes at the user's request -- "Summer Story"
(Film row), "Monochrome", "Underglow", "Gilt Trip" (Monochrome row). Same
treatment as the 2026-07-16 "Classic Chrome"/"Velvia"/"Acros" retirement:
each `_GradeParams` constant and wrapper function is commented out (kept for
reversibility, not deleted), removed from `_LOOKS`/`_LOOK_TRANSFORMS`/
`_GRADES`/`ADDON_DESCRIPTION.thumbnail_presets`, and dropped from
`config_workflow.json`'s `film`/`monochrome` rows. `_MONOCHROME_BASE_GRADE`
stays -- still the calibration anchor for "Mono Moonlight" and "Daido
Moriyama", neither of which is affected (Daido Moriyama was already an
independent duplicate, not a reference to `_MONOCHROME_GRADE`).

2026-08-04: retired "Mono Moonlight" and "Daido Moriyama" from the "B&W" row
at the user's request, same treatment as 2026-07-27 above (commented out, not
deleted -- restore by uncommenting `_MONO_MOONLIGHT_GRADE`/`_mono_moonlight`,
`_DAIDO_MORIYAMA_GRADE`/`_daido_moriyama`, their `_LOOKS`/`_LOOK_TRANSFORMS`/
`_GRADES`/`ADDON_DESCRIPTION.thumbnail_presets` entries, and re-adding
"Mono Moonlight"/"Daido Moriyama" to `config_workflow.json`'s `bw` row).
`_MONOCHROME_BASE_GRADE` is now an ORPHAN -- no active look references it any
longer (its last two consumers are both retired above) -- but stays defined,
unused, per the same instruction: do NOT delete it, only its two consumers.
Replaced with a real colored-filter mechanism instead: a single "Filtre"
selector (Aucun/Yellow/Red/Green/Blue) + a 3-step intensity (Léger/Modéré/
Foncé), modeled on Wratten filters used in B&W film photography. Unlike
Newsprint/Silvertone 99 above (which bake a filter into a bigger, separately
stylized recipe), this is a general-purpose override -- `filter_color`/
`filter_intensity`, resolved by `_resolve_filter_weights` against
`_FILTER_WEIGHTS_TABLE` and applied in `_apply_grade_overrides` (see that
function's own note for why the resolution has to happen there specifically,
before film_look's monochrome/color dispatch) -- usable both as a live "B&W"
row Zoom-overlay control (`ParameterDescription`s `filter_color`/
`filter_intensity`) and, via `preset_parameters`, as the basis for four new
selectable presets: "Acros + Yellow"/"Acros + Red"/"Acros + Green"/
"Acros + Blue" (all `look="acros_pro"` plus a filter override at the Modéré
default -- see their own `ThumbnailPreset` comment for why they don't need a
dedicated `_GradeParams` each). Yellow's and Green's "Modéré" weight rows
reuse `_ACROS_YELLOW_FILTER_GRADE`/`_ACROS_GREEN_FILTER_GRADE`'s own
`monochrome_weights` directly, so Newsprint/Silvertone 99 (still active as of
this paragraph) were unaffected by this change -- see 2026-08-05 below for
their own later retirement.

2026-08-05: retired "Newsprint" and "Silvertone 99" from the "B&W" row at the
user's request, same treatment as 2026-08-04 above (commented out, not
deleted -- restore by uncommenting `_NEWSPRINT_GRADE`/`_newsprint`,
`_SILVERTONE_99_GRADE`/`_silvertone_99`, their `_LOOKS`/`_LOOK_TRANSFORMS`/
`_GRADES`/`ADDON_DESCRIPTION.thumbnail_presets` entries, and re-adding
"Newsprint"/"Silvertone 99" to `config_workflow.json`'s `bw` row).
`_ACROS_YELLOW_FILTER_GRADE`/`_ACROS_GREEN_FILTER_GRADE` themselves are NOT
touched -- unlike `_MONOCHROME_BASE_GRADE` above, they did not become
orphans: `_FILTER_WEIGHTS_TABLE`'s Yellow/Green "Modéré" rows still read
their `monochrome_weights` directly (see that table's own comment), so they
remain live calibration anchors for the "Filtre" selector and the "Acros +
Yellow"/"Acros + Green" presets even with Newsprint/Silvertone 99 gone. The
"B&W" row now has 6 vignettes: "neutral", "Acros", and the four "Acros +
Couleur" presets.

2026-08-05 (later the same day): added three more externally-supplied
recipes to the "B&W" row -- "Kodak T-MAX" (Film Simulation: Monochrome,
built on the module-internal `_MONOCHROME_BASE_GRADE`), "Kodak T-MAX 3200"
and "Kodak Tri-X" (Film Simulation: Acros, both built on `_ACROS_PRO_GRADE`).
Same treatment as every other recipe in this file: a `_GradeParams` constant
via `._replace(...)`, Fuji-scale deltas via `FUJI_SCALE_STEP`/
`GRAIN_EFFECT_TABLE`/`GRAIN_SIZE_TABLE`, White Balance via
`_kelvin_shift_to_temperature_tint` (Kodak T-MAX 3200 uses a literal 5500K,
like Milestone), Mono Colour toning via `mono_color_wc`/`mono_color_mg` where
the source recipe specifies it (Kodak T-MAX 3200 only). ISO/High ISO NR/EV
Comp. omitted per the 2026-07-25 scope note above. Kodak Tri-X's Clarity
(base 18.0 + 4*25=118) clips to the engine's 100.0 maximum; its Color Chrome
Effect: Strong is declared on the grade for fidelity to the source recipe but
is a documented no-op -- `_apply_monochrome_grade` (the render path for any
look with `monochrome_weights` set) never calls `_apply_color_chrome_effect`.
This also required generalizing `film_look`'s fractional-intensity
equal-channel base check from a hard-coded `look == "acros_pro"` to
`grade.monochrome_weights is not None` (bit-identical for Acros Pro, the
prior condition's sole consumer) -- without it, the Zoom overlay's Intensity
slider would blend these three new looks against the original color image
instead of a grayscale base.

2026-08-05 (later still): added five more externally-supplied recipes to the
"B&W" row -- "Agfa APX" and "Ilford XP2" (Film Simulation: Acros, built on
`_ACROS_PRO_GRADE`), "Ilford Delta", "Ilford FP4" and "Ilford HP5" (Film
Simulation: Monochrome, built on `_MONOCHROME_BASE_GRADE`). Same treatment as
every other recipe in this file. Two source-recipe ambiguities resolved by
explicit user decision rather than guessed: (1) Agfa APX/Ilford Delta/Ilford
XP2 specify a Grain Effect strength (Weak/Strong) without a size
(Small/Large), unlike every prior recipe in this file -- Large chosen for all
three; (2) Agfa APX's "Toning: +1 (warm)" is a single signed value on a
warm/cool axis rather than the usual WC/MG pair -- mapped to
`mono_color_wc=1.0, mono_color_mg=0.0` (positive `mono_color_wc` is warm, per
`_apply_temperature_tint`'s own docstring). Agfa APX and Ilford Delta specify
no White Balance at all in the source recipe -- their base's own
temperature/tint (0.0/0.0) pass through unchanged, same treatment as any
other unspecified field (e.g. "Highlight: 0" elsewhere in this file). Ilford
XP2's White Balance is a literal 10000K, like Kodak T-MAX 3200/Milestone's
own literal-Kelvin usage. Agfa APX's Sharpening (base 15.0 + 4*25=115) clips
to the engine's 100.0 maximum; its Color Chrome Effect: Strong is declared on
the grade for fidelity to the source recipe but is a documented no-op, same
reasoning as Kodak Tri-X's. No new engine changes required -- the
`grade.monochrome_weights is not None` generalization from earlier this day
already covers these five new looks.

2026-08-05 (still later the same day): retired five recipes from the "B&W"
row at the user's request -- "Kodak T-MAX", "Agfa APX", "Ilford Delta",
"Ilford HP5", "Ilford XP2". Same treatment as every other retirement in this
file: each `_GradeParams` constant and wrapper function is commented out
(kept for reversibility, not deleted), removed from `_LOOK_TRANSFORMS`/
`_GRADES`/`ADDON_DESCRIPTION.thumbnail_presets`, and dropped from
`config_workflow.json`'s `bw` row. `_MONOCHROME_BASE_GRADE`/`_ACROS_PRO_GRADE`
themselves are unaffected -- both remain live calibration anchors for the
looks that stay active (Ilford FP4 and Kodak T-MAX 3200/Kodak Tri-X/Acros
Pro itself, respectively). The "B&W" row now has 9 vignettes: "neutral",
"Acros", the four "Acros + Couleur" presets, "Kodak T-MAX 3200", "Kodak
Tri-X" and "Ilford FP4".
"""

from __future__ import annotations

from typing import Any, NamedTuple

import numpy

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, ParameterDescription

def _luma(image: numpy.ndarray) -> numpy.ndarray:
    return (
        image[..., 0] * 0.299 + image[..., 1] * 0.587 + image[..., 2] * 0.114
    )


def _s_curve_contrast(channel: numpy.ndarray, amount: float = 0.15) -> numpy.ndarray:
    """A mild S-curve around mid-gray (128): pushes values away from the
    midpoint proportionally to their own distance from it.
    """
    return channel + (channel - 128.0) * amount


def _clip(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


# ---------------------------------------------------------------------------
# Generic parametric grade engine -- a reusable HSL-space pipeline consuming
# a declarative _GradeParams calibration, so a future "*_pro" look needs only
# a new calibration instance, not new pixel-math code. Every field defaults
# to its neutral value from the shared parameter scale; _apply_parametric_grade
# with an all-defaults _GradeParams() is a mathematically exact no-op --
# verified by test_addon_film.py::test_apply_parametric_grade_neutral_params_is_bit_identical.
# Does NOT touch (the now-retired) _classic_chrome/_velvia/_acros above --
# those stay exactly as they were.
# ---------------------------------------------------------------------------

_HUE_CENTERS = {
    "red": 0.0,
    "orange": 30.0,
    "yellow": 60.0,
    "green": 120.0,
    "cyan": 180.0,
    "blue": 240.0,
    "magenta": 300.0,
}
_GRAIN_SEED = 20260716  # fixed constant -- never derived from clock/content,
                         # so the same image shape always gets the same grain
                         # (FR-004-style determinism, feature 042 precedent).


class _GradeParams(NamedTuple):
    """One row of the shared parametric grading scale the user supplied --
    every field's default is that scale's own neutral value. A plain
    `typing.NamedTuple` rather than `@dataclass` deliberately: addon modules
    are loaded via `importlib.util.spec_from_file_location` (loader.py)
    WITHOUT being registered in `sys.modules`, and `dataclasses._process_class`
    looks itself up via `sys.modules[cls.__module__]` on this Python version
    -- it raises `AttributeError: 'NoneType' object has no attribute
    '__dict__'` for any `@dataclass` defined in a module loaded that way.
    NamedTuple has no such dependency. `hsl_saturation`/`hsl_hue_rotation`/
    `hsl_luminance`'s empty-dict defaults are shared across instances (the
    usual mutable-default caveat) but are never mutated in place anywhere in
    this module, only read via `.items()`.
    """

    contrast: float = 0.0                      # -100..100
    highlights: float = 0.0                     # -100..100
    shadows: float = 0.0                        # -100..100
    global_saturation: float = 1.0               # x0..x2
    hsl_saturation: dict[str, float] = {}         # -50..50 (%) per hue name
    hsl_hue_rotation: dict[str, float] = {}       # -30..30 (deg) per hue name
    hsl_luminance: dict[str, float] = {}          # -30..30 per hue name
    temperature: float = 0.0                     # -1000..1000 K (approximation, not Planckian)
    tint: float = 0.0                            # -20..20 (green-magenta)
    split_tone_shadow_hue: float | None = None    # 0..360 deg
    split_tone_shadow_strength: float = 0.0       # 0..20 (%)
    split_tone_highlight_hue: float | None = None
    split_tone_highlight_strength: float = 0.0
    clarity: float = 0.0                          # -100..100
    sharpness: float = 0.0                        # -100..100
    grain_std: float = 0.0                        # 0..0.05 (stddev on 0..1 luminance)
    grain_size: float = 1.0                       # px
    grain_std_shadow_boost: float = 0.0           # 0..0.05, added to grain_std as shadows darken
    black_clip: float = 0.0                       # 0..0.10
    monochrome_weights: tuple[float, float, float] | None = None  # (wR, wG, wB), sum ~1.0
    color_chrome_effect: float = 0.0              # 0=Off, 1=Weak, 2=Strong
    color_chrome_blue: float = 0.0                # 0=Off, 1=Weak, 2=Strong
    dynamic_range: float = 0.0                    # 0=DR100, 1=DR200, 2=DR400
    mono_color_wc: float = 0.0                    # -20..20 (Fuji "Mono Colour" WC dial, ~-9..+9 native)
    mono_color_mg: float = 0.0                    # -20..20 (Fuji "Mono Colour" MG dial, ~-9..+9 native)


def _rgb_to_hsl(rgb: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    """rgb: float32 (H, W, 3) in 0..255. Returns (h in 0..360, s in 0..1, l in 0..1)."""
    normalized = rgb / 255.0
    r, g, b = normalized[..., 0], normalized[..., 1], normalized[..., 2]
    # PERF-ZOOM-RENDER-PLAN.md étape 3: numpy.max(normalized, axis=-1) was tried here (fewer
    # allocations, bit-identical) but measured 3-5x SLOWER than the nested maximum/minimum below --
    # reducing along a small, strided last axis (size 3) has worse per-element overhead than two
    # elementwise passes over contiguous-enough (H, W) views, on this numpy/machine. Reverted after
    # measurement; kept as the cautionary example this plan's own "mesurer, ne pas supposer"
    # discipline calls for -- do not reintroduce without re-benchmarking.
    maxc = numpy.maximum(numpy.maximum(r, g), b)
    minc = numpy.minimum(numpy.minimum(r, g), b)
    luminance = (maxc + minc) / 2.0
    delta = maxc - minc
    saturation = numpy.where(
        delta < 1e-6, 0.0, delta / (1.0 - numpy.abs(2.0 * luminance - 1.0) + 1e-6)
    )
    delta_safe = numpy.where(delta < 1e-6, 1.0, delta)
    hue = 4.0 + (r - g) / delta_safe
    hue = numpy.where(maxc == g, 2.0 + (b - r) / delta_safe, hue)
    hue = numpy.where(maxc == r, ((g - b) / delta_safe) % 6.0, hue)
    hue = numpy.where(delta < 1e-6, 0.0, hue * 60.0)
    return hue % 360.0, numpy.clip(saturation, 0.0, 1.0), luminance


def _hsl_to_rgb(hue: numpy.ndarray, saturation: numpy.ndarray, luminance: numpy.ndarray) -> numpy.ndarray:
    """Inverse of _rgb_to_hsl -- returns float32 (H, W, 3) in 0..255."""
    hue = hue % 360.0
    chroma = (1.0 - numpy.abs(2.0 * luminance - 1.0)) * saturation
    h_prime = hue / 60.0
    x = chroma * (1.0 - numpy.abs(h_prime % 2.0 - 1.0))
    zeros = numpy.zeros_like(hue)
    conditions = [
        (h_prime >= 0.0) & (h_prime < 1.0),
        (h_prime >= 1.0) & (h_prime < 2.0),
        (h_prime >= 2.0) & (h_prime < 3.0),
        (h_prime >= 3.0) & (h_prime < 4.0),
        (h_prime >= 4.0) & (h_prime < 5.0),
        (h_prime >= 5.0) & (h_prime < 6.0),
    ]
    r1 = numpy.select(conditions, [chroma, x, zeros, zeros, x, chroma], default=zeros)
    g1 = numpy.select(conditions, [x, chroma, chroma, x, zeros, zeros], default=zeros)
    b1 = numpy.select(conditions, [zeros, zeros, x, chroma, chroma, x], default=zeros)
    m = luminance - chroma / 2.0
    return numpy.stack([r1 + m, g1 + m, b1 + m], axis=-1) * 255.0


def _zone_weights(luminance: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Shadow/highlight weights from 0..1 luminance -- 1 at the extreme, 0 at
    or past mid-gray (0.5), linear falloff. Shared by tone curve and
    split-tone so both target the same zones.
    """
    shadow_weight = numpy.clip((0.5 - luminance) / 0.5, 0.0, 1.0)
    highlight_weight = numpy.clip((luminance - 0.5) / 0.5, 0.0, 1.0)
    return shadow_weight, highlight_weight


def _apply_tone_curve(
    luminance: numpy.ndarray, contrast: float, highlights: float, shadows: float
) -> numpy.ndarray:
    """Contrast: S-curve around mid-gray. Shadows/highlights: convention is
    positive lightens/hardens (pushes brighter), negative darkens/compresses
    (pulls toward mid) -- both read directly from the -100..100 scale.
    """
    # Coefficients calibrated so shadows/highlights (0.25) are NOT swamped by
    # contrast (0.3) at the extreme tail -- an earlier 0.15/0.6 split let
    # contrast fully cancel and even reverse a negative `highlights` value at
    # near-white luminance (verified via visual-verification sampling),
    # contradicting the "highlights stay relatively soft" trait this engine
    # needs to be able to reproduce (see the Classic Chrome Pro calibration).
    shadow_weight, highlight_weight = _zone_weights(luminance)
    result = luminance + shadow_weight * (shadows / 100.0) * 0.25
    result = result + highlight_weight * (highlights / 100.0) * 0.25
    result = result + (result - 0.5) * (contrast / 100.0) * 0.3
    return numpy.clip(result, 0.0, 1.0)


def _apply_global_saturation(saturation: numpy.ndarray, factor: float) -> numpy.ndarray:
    return numpy.clip(saturation * factor, 0.0, 1.0)


def _hue_window(hue: numpy.ndarray, center: float) -> numpy.ndarray:
    """The cosine-weighted hue window (half-width 40 deg) shared by every per-hue primitive:
    1 at `center`, falling to 0 at 40 deg away, exactly 0 beyond.

    Extracted 2026-08-23 from the four call sites that each carried an identical copy
    (`_apply_hsl_saturation_by_hue`, `_apply_hsl_luminance_by_hue`, `_apply_hsl_hue_rotation`,
    `_apply_color_chrome_blue`), so the formula lives once and -- more to the point -- so its
    RESULT can be memoized across them by `_hue_window_for`. One window costs about as much as a
    third of a full RGB->HSL conversion at 2 MP (the `numpy.cos` over every pixel dominates), and
    a single look routinely asks for the same hue two or three times: Titanium computed the blue
    and cyan windows twice each (once for saturation, once for Color Chrome Blue), Velvia computed
    blue and green twice (saturation, then hue rotation)."""
    angular_distance = numpy.abs(((hue - center + 180.0) % 360.0) - 180.0)
    return numpy.where(
        angular_distance <= 40.0,
        0.5 * (1.0 + numpy.cos(angular_distance / 40.0 * numpy.pi)),
        0.0,
    )


def _hue_window_for(
    hue: numpy.ndarray, center: float, windows: dict[float, numpy.ndarray] | None
) -> numpy.ndarray:
    """`_hue_window` behind an optional per-grade memo, keyed by hue CENTER (not name, so the
    name-driven HSL loops and `_apply_color_chrome_blue`'s direct `_HUE_CENTERS[...]` lookups share
    the same entries automatically).

    THE MEMO IS VALID FOR EXACTLY ONE `hue` ARRAY. `_apply_parametric_grade` builds a fresh one per
    call and hands it only to primitives that read the SAME pre-rotation `hue`
    (`_apply_hsl_hue_rotation` deliberately weights from `original_hue`, and is the last of the four
    to run). Reordering the grade so a consumer sees post-rotation hue, or reusing a memo across two
    images, would silently return windows computed for the wrong array -- pass `windows=None` in any
    such case, which restores the original per-call computation."""
    if windows is None:
        return _hue_window(hue, center)
    cached = windows.get(center)
    if cached is None:
        cached = _hue_window(hue, center)
        windows[center] = cached
    return cached


def _apply_hsl_saturation_by_hue(
    hue: numpy.ndarray,
    saturation: numpy.ndarray,
    deltas: dict[str, float],
    windows: dict[float, numpy.ndarray] | None = None,
) -> numpy.ndarray:
    """For each named hue in `deltas` (-50..50 %), scales saturation within a
    cosine-weighted window (half-width 40 deg) centered on that hue's
    standard angle -- pixels far from every named hue are unaffected.

    `windows`: optional shared memo, see `_hue_window_for`. Default None keeps the original
    per-call computation, so direct callers (tests) need no change.
    """
    result = saturation
    for name, delta_pct in deltas.items():
        center = _HUE_CENTERS.get(name)
        if center is None:
            continue
        weight = _hue_window_for(hue, center, windows)
        result = numpy.clip(result * (1.0 + weight * (delta_pct / 100.0)), 0.0, 1.0)
    return result


def _apply_hsl_luminance_by_hue(
    hue: numpy.ndarray,
    luminance: numpy.ndarray,
    deltas: dict[str, float],
    windows: dict[float, numpy.ndarray] | None = None,
) -> numpy.ndarray:
    """For each named hue in `deltas` (-30..30, the "Luminance HSL" row of
    the shared parameter scale), shifts luminance within the same
    cosine-weighted window used by saturation/hue-rotation -- e.g. brightening
    skin tones ("orange/peau") without touching the rest of the tone curve.
    Scale (0.15) deliberately modest: this is meant as a subtle per-hue
    lightness nudge, not a second tone curve.

    `windows`: optional shared memo, see `_hue_window_for`.
    """
    result = luminance
    for name, delta in deltas.items():
        center = _HUE_CENTERS.get(name)
        if center is None:
            continue
        weight = _hue_window_for(hue, center, windows)
        result = numpy.clip(result + weight * (delta / 30.0) * 0.15, 0.0, 1.0)
    return result


_COLOR_CHROME_STRENGTH = {0.0: 0.0, 1.0: 0.5, 2.0: 1.0}  # level (Off/Weak/Strong) -> internal strength


def _color_chrome_strength(level: float) -> float:
    """Linear interpolation over `_COLOR_CHROME_STRENGTH`'s three calibrated
    points -- Zoom overrides can land on a non-integer level (clipped to
    0..2), so this must handle fractional input, not just the three exact
    preset values.
    """
    if level <= 0.0:
        return 0.0
    if level >= 2.0:
        return 1.0
    if level <= 1.0:
        return level * _COLOR_CHROME_STRENGTH[1.0]
    return _COLOR_CHROME_STRENGTH[1.0] + (level - 1.0) * (
        _COLOR_CHROME_STRENGTH[2.0] - _COLOR_CHROME_STRENGTH[1.0]
    )


def _relative_gate(values: numpy.ndarray, low_percentile: float, high_percentile: float) -> numpy.ndarray:
    """Normalizes `values` to 0..1 between its OWN low/high percentile,
    rather than fixed absolute bounds -- a bug fix (2026-07-25): the original
    `_color_chrome_trigger` used a hardcoded `saturation > 0.45` cutoff, which
    silently never fired on any heavily-desaturated look (Eterna Bleach
    Bypass's global_saturation=0.30, Inky Depths's own 0.21 -- post-grade
    saturation there never exceeds ~0.15, so Color Chrome Effect/Blue had
    ZERO visible effect at any level, Off through Strong, confirmed by a
    before/after pixel diff). Percentiles of the array actually being graded
    keep the gate meaningful regardless of how much a look's own calibration
    has already compressed the range.
    """
    low = float(numpy.percentile(values, low_percentile))
    high = float(numpy.percentile(values, high_percentile))
    if high - low < 1e-6:
        return numpy.zeros_like(values)
    return numpy.clip((values - low) / (high - low), 0.0, 1.0)


def _color_chrome_trigger(saturation: numpy.ndarray, luminance: numpy.ndarray) -> numpy.ndarray:
    """Fuji's real Color Chrome Effect/Blue only visibly act on the most
    saturated, brightest pixels RELATIVE TO THE REST OF THIS IMAGE (its
    purpose is protecting saturated highlights from clipping) -- see
    `_relative_gate`'s docstring for why this must be percentile-based, not a
    fixed absolute cutoff.
    """
    sat_gate = _relative_gate(saturation, 60.0, 95.0)
    luma_gate = _relative_gate(luminance, 30.0, 90.0)
    return sat_gate * luma_gate


def _apply_color_chrome_effect(
    saturation: numpy.ndarray, luminance: numpy.ndarray, level: float
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Deepens/compresses strongly-saturated, bright pixels -- a broad
    (hue-independent) approximation of Fuji's Color Chrome Effect dial.
    No-op at level 0 (Off), matching every other primitive's convention.
    """
    strength = _color_chrome_strength(level)
    if strength <= 0.0:
        return saturation, luminance
    trigger = _color_chrome_trigger(saturation, luminance) * strength
    saturation = numpy.clip(saturation - trigger * 0.20, 0.0, 1.0)
    luminance = numpy.clip(luminance - trigger * 0.06, 0.0, 1.0)
    return saturation, luminance


def _apply_color_chrome_blue(
    hue: numpy.ndarray,
    saturation: numpy.ndarray,
    luminance: numpy.ndarray,
    level: float,
    windows: dict[float, numpy.ndarray] | None = None,
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Same mechanism as `_apply_color_chrome_effect`, but hue-restricted to
    blue/cyan (the same cosine-weighted-window pattern used by
    `_apply_hsl_saturation_by_hue`) -- approximates Fuji's Color Chrome Blue
    dial, which only deepens blue skies/water, not the whole image. Takes the
    max of the two hue windows rather than summing them, so a pixel exactly
    between blue and cyan isn't double-weighted.

    `windows`: optional shared memo, see `_hue_window_for`. This is the primitive that gains most
    from it -- every look whose `hsl_saturation` names blue or cyan (Titanium, Eterna Bleach Bypass,
    Inky Depths...) has already built the very same window earlier in the grade.
    """
    strength = _color_chrome_strength(level)
    if strength <= 0.0:
        return saturation, luminance

    hue_weight = numpy.maximum(
        _hue_window_for(hue, _HUE_CENTERS["blue"], windows),
        _hue_window_for(hue, _HUE_CENTERS["cyan"], windows),
    )
    trigger = _color_chrome_trigger(saturation, luminance) * strength * hue_weight
    saturation = numpy.clip(saturation - trigger * 0.20, 0.0, 1.0)
    luminance = numpy.clip(luminance - trigger * 0.06, 0.0, 1.0)
    return saturation, luminance


_DR_DELTA_PER_LEVEL = (-15.0, 10.0, -0.008)  # (highlights, shadows, black_clip) per DR level step


def _resolve_dynamic_range(grade: "_GradeParams") -> "_GradeParams":
    """DR100/200/400 is deliberately composed from existing tone-curve/
    black-clip fields rather than given its own pixel-math primitive -- see
    the module docstring's 2026-07-25 note. No-op at level 0 (DR100), true
    for every look predating this feature, so this composes for free with the
    "same object, no behavior change" invariant `_apply_grade_overrides`
    already protects.
    """
    if grade.dynamic_range == 0.0:
        return grade
    highlight_delta, shadow_delta, black_clip_delta = _DR_DELTA_PER_LEVEL
    level = _clip(grade.dynamic_range, 0.0, 2.0)
    return grade._replace(
        highlights=_clip(grade.highlights + level * highlight_delta, -100.0, 100.0),
        shadows=_clip(grade.shadows + level * shadow_delta, -100.0, 100.0),
        black_clip=_clip(grade.black_clip + level * black_clip_delta, 0.0, 0.10),
    )


def _apply_hsl_hue_rotation(
    hue: numpy.ndarray,
    rotations: dict[str, float],
    windows: dict[float, numpy.ndarray] | None = None,
) -> numpy.ndarray:
    """For each named hue in `rotations` (-30..30 deg), rotates hue within the
    same cosine-weighted window used by saturation. Weight is computed from
    the ORIGINAL `hue` for every named entry (not the progressively-rotated
    result), so multiple rotations in the same call don't feed into each
    other's windows. A no-op for already-desaturated pixels since chroma is
    what actually reads `hue` downstream in `_hsl_to_rgb`.

    `windows`: optional shared memo, see `_hue_window_for`. Weighting from `original_hue` -- the
    array every other per-hue primitive in the grade also saw -- is precisely what makes sharing
    the memo with them legitimate here.
    """
    original_hue = hue
    result = hue
    for name, degrees in rotations.items():
        center = _HUE_CENTERS.get(name)
        if center is None:
            continue
        weight = _hue_window_for(original_hue, center, windows)
        result = (result + weight * degrees) % 360.0
    return result


def _apply_temperature_tint(rgb: numpy.ndarray, temperature: float, tint: float) -> numpy.ndarray:
    """Simplified per-channel white-balance approximation -- NOT a physically
    accurate Planckian-locus computation. Negative temperature cools the
    image (less red, more blue); negative tint shifts toward green.
    """
    result = rgb.copy()
    result[..., 0] *= 1.0 + (temperature / 1000.0) * 0.10
    result[..., 2] *= 1.0 - (temperature / 1000.0) * 0.10
    result[..., 1] *= 1.0 - (tint / 20.0) * 0.05
    return result


def _apply_split_tone(rgb: numpy.ndarray, luminance: numpy.ndarray, grade: "_GradeParams") -> numpy.ndarray:
    """Blends a target hue's color into the shadow/highlight zones,
    generalizing the retired _classic_chrome's hard-coded R+/B- split tone
    into an arbitrary hue + strength pair reusable by any future calibration.
    """
    result = rgb
    shadow_weight, highlight_weight = _zone_weights(luminance)
    # Perf remediation (2026-07-17): the target color is spatially CONSTANT
    # (hue/saturation/luminance are all `full_like`/`ones_like` -- no per-pixel
    # variation), so running it through _hsl_to_rgb at the full (H, W) size
    # was ~12M pixels of vectorized HSL->RGB work (6 numpy.select branches
    # etc.) to compute a single RGB triplet. A 1x1 call through the exact
    # same function/formula gives a bit-identical result (proven: every pixel
    # of the old full-size computation equals this 1x1 result exactly, since
    # the formula has no cross-pixel coupling) at a fraction of the cost --
    # the (3,) result broadcasts against (H, W, 3) via ordinary numpy rules,
    # so the actual per-pixel blend below is unchanged.
    if grade.split_tone_shadow_hue is not None and grade.split_tone_shadow_strength > 0.0:
        tiny_hue = numpy.array([[grade.split_tone_shadow_hue]], dtype=luminance.dtype)
        target = _hsl_to_rgb(tiny_hue, numpy.ones_like(tiny_hue), numpy.full_like(tiny_hue, 0.5))[0, 0]
        blend = (shadow_weight * (grade.split_tone_shadow_strength / 100.0))[..., numpy.newaxis]
        result = result * (1.0 - blend) + target * blend
    if grade.split_tone_highlight_hue is not None and grade.split_tone_highlight_strength > 0.0:
        tiny_hue = numpy.array([[grade.split_tone_highlight_hue]], dtype=luminance.dtype)
        target = _hsl_to_rgb(tiny_hue, numpy.ones_like(tiny_hue), numpy.full_like(tiny_hue, 0.5))[0, 0]
        blend = (highlight_weight * (grade.split_tone_highlight_strength / 100.0))[..., numpy.newaxis]
        result = result * (1.0 - blend) + target * blend
    return result


def _box_blur(channel: numpy.ndarray, radius: int) -> numpy.ndarray:
    """Deterministic separable box blur via prefix sums -- no scipy
    dependency. radius <= 0 is a no-op.
    """
    if radius <= 0:
        return channel
    size = 2 * radius + 1

    def _blur_axis(data: numpy.ndarray, axis: int) -> numpy.ndarray:
        pad_width = [(0, 0), (0, 0)]
        pad_width[axis] = (radius, radius)
        padded = numpy.pad(data, pad_width, mode="edge")
        cumsum = numpy.cumsum(padded, axis=axis)
        zero_pad_width = [(0, 0), (0, 0)]
        zero_pad_width[axis] = (1, 0)
        cumsum = numpy.pad(cumsum, zero_pad_width)
        # Perf remediation (2026-07-17): numpy.take with a contiguous range
        # forces a fancy-indexing copy; a plain slice on the target axis
        # returns a view instead, for the exact same values (bit-identical,
        # verified) at a lower cost.
        n = cumsum.shape[axis]
        upper_index = [slice(None), slice(None)]
        upper_index[axis] = slice(size, n)
        lower_index = [slice(None), slice(None)]
        lower_index[axis] = slice(0, n - size)
        upper = cumsum[tuple(upper_index)]
        lower = cumsum[tuple(lower_index)]
        return (upper - lower) / size

    return _blur_axis(_blur_axis(channel, axis=0), axis=1)


def _apply_clarity_sharpness(rgb: numpy.ndarray, clarity: float, sharpness: float) -> numpy.ndarray:
    """Clarity: unsharp mask on luma with a wide radius (midtone/local
    contrast). Sharpness: unsharp mask per channel with a narrow radius
    (fine detail). Both no-op at 0.
    """
    result = rgb
    if clarity != 0.0:
        luma = _luma(result)
        height, width = luma.shape
        radius = max(1, int(round(min(height, width) * 0.02)))
        blurred = _box_blur(luma, radius)
        detail = (luma - blurred) * (clarity / 100.0) * 0.8
        result = result + detail[..., numpy.newaxis]
    if sharpness != 0.0:
        radius = 1
        for channel_index in range(3):
            channel = result[..., channel_index]
            blurred = _box_blur(channel, radius)
            result[..., channel_index] = channel + (channel - blurred) * (sharpness / 100.0) * 0.8
    return result


def _apply_grain(
    rgb: numpy.ndarray,
    std: float,
    size: float,
    shadow_boost: float = 0.0,
    luminance: numpy.ndarray | None = None,
) -> numpy.ndarray:
    """Deterministic film grain -- a fixed-seed RNG depending only on the
    image's own shape, never on wall-clock time or pixel content, so the
    same input always produces byte-identical output (Principle IV).

    `shadow_boost` + `luminance` (0..1) make the grain strength itself
    luminance-dependent -- `sigma(l) = std + shadow_boost * (1 - l) ** 0.7`,
    heavier in shadows than highlights (the Acros Pro calibration's own
    formula). A single standard-normal draw is scaled per-pixel by that
    local sigma rather than drawing a second RNG stream, so determinism
    (same seed) is unaffected by whether shadow_boost is used.
    """
    if std <= 0.0 and shadow_boost <= 0.0:
        return rgb
    height, width = rgb.shape[0], rgb.shape[1]
    rng = numpy.random.default_rng(_GRAIN_SEED)
    if shadow_boost > 0.0 and luminance is not None:
        sigma = (std + shadow_boost * (1.0 - luminance) ** 0.7) * 255.0
        noise = rng.normal(0.0, 1.0, size=(height, width)).astype(numpy.float32) * sigma
    else:
        noise = rng.normal(0.0, std * 255.0, size=(height, width)).astype(numpy.float32)
    blur_radius = max(0, int(round(size / 2.0)))
    if blur_radius > 0:
        noise = _box_blur(noise, blur_radius)
    return rgb + noise[..., numpy.newaxis]


def _apply_black_clip(rgb: numpy.ndarray, amount: float) -> numpy.ndarray:
    """Raises the black point -- crushes near-black values toward pure black
    more aggressively as `amount` increases. No-op at 0.
    """
    if amount <= 0.0:
        return rgb
    normalized = numpy.clip(rgb / 255.0, 0.0, 1.0)
    remapped = numpy.clip((normalized - amount) / (1.0 - amount), 0.0, 1.0)
    return remapped * 255.0


def _apply_monochrome_grade(image: numpy.ndarray, grade: "_GradeParams") -> numpy.ndarray:
    """A separate, simpler branch for calibrations declaring `monochrome_weights`
    (e.g. Acros Pro) -- converts straight to a custom-weighted grayscale
    (bypassing standard HSL lightness, which uses (max+min)/2, not an
    arbitrary R/G/B weighting) up front, so every later step (tone curve,
    clarity/sharpness, grain, black clip) operates on an already-equal-channel
    image and the R == G == B guarantee holds unconditionally, the same
    guarantee the original _acros() makes. Resolves `dynamic_range` itself
    (see `_resolve_dynamic_range`) since `film_look` calls this function
    directly for monochrome grades, bypassing `_apply_parametric_grade`
    entirely -- this is the sole choke point for the monochrome path, so DR
    is applied exactly once.

    2026-07-26: two additions for the "Monochrome" workflow row's recipes --
    (1) `temperature`/`tint` (White Balance) are now applied to the SOURCE
    image before the custom-weighted grayscale conversion, like a colored
    filter in front of black & white film (affects the relative brightness
    fed into the conversion, not just a final cast). Previously silently
    ignored on this path -- invisible until now since Acros Pro (the only
    prior monochrome_weights look) always has temperature=tint=0.0, an exact
    no-op (`_apply_temperature_tint` multiplies by `1 + 0`), so this is a
    bit-identical no-op for every pre-existing monochrome look. (2) A
    "Mono Colour" WC/MG toning pass (`mono_color_wc`/`mono_color_mg`,
    distinct from White Balance -- a color cast applied to the ALREADY-GRAY
    image, Fuji's "Monochromatic Color" adjustment) reuses the same
    `_apply_temperature_tint` primitive via `_mono_color_to_temperature_tint`,
    applied to the gray RGB triplet. No-op at the default 0.0/0.0.
    """
    grade = _resolve_dynamic_range(grade)
    source = _apply_temperature_tint(image, grade.temperature, grade.tint)
    weight_r, weight_g, weight_b = grade.monochrome_weights
    custom_luma = source[..., 0] * weight_r + source[..., 1] * weight_g + source[..., 2] * weight_b
    luminance = numpy.clip(custom_luma / 255.0, 0.0, 1.0)
    luminance = _apply_tone_curve(luminance, grade.contrast, grade.highlights, grade.shadows)
    gray = luminance * 255.0
    rgb = numpy.stack([gray, gray, gray], axis=-1)
    mono_temperature, mono_tint = _mono_color_to_temperature_tint(grade.mono_color_wc, grade.mono_color_mg)
    rgb = _apply_temperature_tint(rgb, mono_temperature, mono_tint)
    rgb = _apply_clarity_sharpness(rgb, grade.clarity, grade.sharpness)
    rgb = _apply_grain(rgb, grade.grain_std, grade.grain_size, grade.grain_std_shadow_boost, luminance)
    rgb = _apply_black_clip(rgb, grade.black_clip)
    return rgb


def _apply_parametric_grade(image: numpy.ndarray, grade: "_GradeParams") -> numpy.ndarray:
    """Orchestrates the generic grading pipeline against one declarative
    _GradeParams calibration -- see the module-level comment above this
    section for the reuse rationale.
    """
    if grade.monochrome_weights is not None:
        return _apply_monochrome_grade(image, grade)
    # DR is resolved here (not before the monochrome dispatch above) so it's
    # applied exactly once no matter which path renders the grade --
    # `_apply_monochrome_grade` resolves it itself, since `film_look` also
    # calls that function directly, bypassing this one entirely.
    grade = _resolve_dynamic_range(grade)
    hue, saturation, luminance = _rgb_to_hsl(image)
    # One memo of cosine hue windows for this grade, shared by the four per-hue primitives below
    # (perf, 2026-08-23 -- see `_hue_window_for`). Every one of them weights from THIS `hue` array:
    # `_apply_hsl_hue_rotation` is the only one that changes hue, it runs last, and it weights from
    # the original anyway. Keep it that way, or the memo silently goes stale -- the four calls must
    # stay above the reassignment of `hue`.
    hue_windows: dict[float, numpy.ndarray] = {}
    luminance = _apply_tone_curve(luminance, grade.contrast, grade.highlights, grade.shadows)
    saturation = _apply_global_saturation(saturation, grade.global_saturation)
    saturation = _apply_hsl_saturation_by_hue(hue, saturation, grade.hsl_saturation, hue_windows)
    luminance = _apply_hsl_luminance_by_hue(hue, luminance, grade.hsl_luminance, hue_windows)
    saturation, luminance = _apply_color_chrome_effect(saturation, luminance, grade.color_chrome_effect)
    saturation, luminance = _apply_color_chrome_blue(
        hue, saturation, luminance, grade.color_chrome_blue, hue_windows
    )
    hue = _apply_hsl_hue_rotation(hue, grade.hsl_hue_rotation, hue_windows)
    rgb = _hsl_to_rgb(hue, saturation, luminance)
    rgb = _apply_temperature_tint(rgb, grade.temperature, grade.tint)
    rgb = _apply_split_tone(rgb, luminance, grade)
    rgb = _apply_clarity_sharpness(rgb, grade.clarity, grade.sharpness)
    rgb = _apply_grain(rgb, grade.grain_std, grade.grain_size, grade.grain_std_shadow_boost, luminance)
    rgb = _apply_black_clip(rgb, grade.black_clip)
    return rgb


_CLASSIC_CHROME_PRO_GRADE = _GradeParams(
    contrast=10.0,
    highlights=-12.0,
    shadows=-20.0,
    global_saturation=0.78,
    hsl_saturation={"magenta": -25.0, "red": -15.0, "green": -15.0, "blue": -10.0},
    temperature=-100.0,
    tint=-2.0,
    split_tone_shadow_hue=215.0,
    split_tone_shadow_strength=8.0,
    split_tone_highlight_hue=45.0,
    split_tone_highlight_strength=2.0,
    clarity=10.0,
    sharpness=5.0,
    grain_std=0.012,
    grain_size=1.0,
)


def _classic_chrome_pro(image: numpy.ndarray) -> numpy.ndarray:
    """The precise, externally-calibrated Classic Chrome recipe, built on the
    generic parametric grade engine above -- the sole Classic Chrome look
    since the simpler `_classic_chrome` was retired (module docstring).
    """
    return _apply_parametric_grade(image, _CLASSIC_CHROME_PRO_GRADE)


_VELVIA_PRO_GRADE = _GradeParams(
    contrast=28.0,
    highlights=15.0,
    shadows=-20.0,
    global_saturation=1.32,
    hsl_saturation={"red": 10.0, "green": 12.0, "blue": 10.0, "orange": -5.0},
    hsl_hue_rotation={"green": -4.0, "blue": -4.0},  # green->yellow, blue->cyan
    temperature=-150.0,
    tint=3.0,
    split_tone_shadow_hue=220.0,
    split_tone_shadow_strength=5.0,
    split_tone_highlight_hue=45.0,
    split_tone_highlight_strength=2.0,
    clarity=8.0,
    sharpness=10.0,
    grain_std=0.008,
    grain_size=0.85,
)


def _velvia_pro(image: numpy.ndarray) -> numpy.ndarray:
    """The precise, externally-calibrated Velvia recipe, built on the generic
    parametric grade engine -- kept alongside the original `_velvia` (not a
    replacement) so both can be compared, per the user's explicit request.
    """
    return _apply_parametric_grade(image, _VELVIA_PRO_GRADE)


_ACROS_PRO_GRADE = _GradeParams(
    contrast=30.0,
    highlights=10.0,
    shadows=-25.0,
    monochrome_weights=(0.30, 0.59, 0.11),
    clarity=18.0,
    sharpness=15.0,
    grain_std=0.010,
    grain_std_shadow_boost=0.020,
    grain_size=1.0,
    black_clip=0.010,
)


def _acros_pro(image: numpy.ndarray) -> numpy.ndarray:
    """The precise, externally-calibrated Acros recipe (custom R/G/B
    monochrome weights + luminance-dependent grain), built on the generic
    parametric grade engine -- kept alongside the original `_acros` (not a
    replacement) so both can be compared, per the user's explicit request.
    """
    return _apply_parametric_grade(image, _ACROS_PRO_GRADE)


# Module-internal calibration anchors (2026-07-26, "B&W" workflow row) --
# documented approximations, like _CLASSIC_NEGATIVE_GRADE/_MONOCHROME_BASE_GRADE
# above: no reference values available. Originally just the base for
# Newsprint/Silvertone 99 (retired 2026-08-05, see module docstring); now also
# the live source of _FILTER_WEIGHTS_TABLE's Yellow/Green "Modéré" rows (see
# that table's own comment), so still actively read despite those two
# retirements. Unlike Classic Negative, NOT exposed as
# standalone selectable looks -- nothing in the source recipes calls for a
# bare "Acros Yellow/Green Filter" preset, only the fully-specified recipes.
# Only `monochrome_weights` differs from Acros Pro -- these are filter
# VARIANTS of Acros (the physical colored-filter-in-front-of-B&W-film
# concept: a filter changes which wavelengths contribute to the grayscale
# conversion, distinct from White Balance, which shifts color BEFORE that
# weighting rather than the weights themselves), not new simulations, so
# every other field (contrast/highlights/shadows/clarity/sharpness/grain/
# black_clip) is inherited unchanged.
_ACROS_YELLOW_FILTER_GRADE = _ACROS_PRO_GRADE._replace(
    monochrome_weights=(0.40, 0.40, 0.20),  # a yellow filter physically blocks blue (darkens sky),
    # passes red/green -- blue weight reduced, red/green equal and dominant. Starting point, to be
    # refined visually like every other calibration here.
)
_ACROS_GREEN_FILTER_GRADE = _ACROS_PRO_GRADE._replace(
    monochrome_weights=(0.20, 0.70, 0.10),  # a green filter favors green (skin/foliage contrast)
    # at the expense of red and blue. Starting point, to be refined visually.
)

# Wratten-filter-inspired R/G/B weight table (2026-08-04, "B&W" row filter
# selector -- see _resolve_filter_weights below and _apply_grade_overrides's
# own note). Approximate engineering values, not a spectrophotometric
# simulation of the real Wratten #8/#12/#15 (yellow), #23A/#25/#29 (red),
# #11/#13 (green), #47/#47B (blue) filters -- same spirit as _GradeParams'
# "approximation, not Planckian" comment on `temperature`. Yellow's and
# Green's "Modéré" (index 1) rows read _ACROS_YELLOW_FILTER_GRADE's/
# _ACROS_GREEN_FILTER_GRADE's own monochrome_weights directly (not a
# duplicated literal) so they can never drift from those two anchors, which
# Newsprint/Silvertone 99 still build on unchanged -- "Léger"/"Foncé" are new
# values extrapolated the same distance below/above that fixed pivot, away
# from the neutral panchromatic weights (_ACROS_PRO_GRADE.monochrome_weights
# = (0.30, 0.59, 0.11)). Red/Blue have no pre-existing anchor to preserve, so
# all three of their rows are new. Every row sums to 1.0; effect strength
# increases monotonically Léger->Modéré->Foncé per channel.
_FILTER_WEIGHTS_TABLE: dict[int, dict[int, tuple[float, float, float]]] = {
    1: {0: (0.35, 0.50, 0.15), 1: _ACROS_YELLOW_FILTER_GRADE.monochrome_weights, 2: (0.45, 0.30, 0.25)},  # Yellow
    2: {0: (0.45, 0.40, 0.15), 1: (0.60, 0.30, 0.10), 2: (0.75, 0.20, 0.05)},  # Red
    3: {0: (0.25, 0.65, 0.10), 1: _ACROS_GREEN_FILTER_GRADE.monochrome_weights, 2: (0.15, 0.75, 0.10)},  # Green
    4: {0: (0.25, 0.40, 0.35), 1: (0.15, 0.30, 0.55), 2: (0.05, 0.20, 0.75)},  # Blue
}


def _resolve_filter_weights(filter_color: float, filter_intensity: float) -> tuple[float, float, float] | None:
    """filter_color: 0=Aucun (no-op, returns None), 1=Yellow, 2=Red, 3=Green,
    4=Blue. filter_intensity: 0=Léger, 1=Modéré (default), 2=Foncé -- only
    meaningful when filter_color != 0. Both are categorical dials (discrete
    Wratten-strength steps), not a continuous physical quantity, so this
    rounds to the nearest calibrated index rather than interpolating:
    interpolating BETWEEN two different filter colors would produce a
    physically meaningless blended hue.
    """
    color_index = int(round(_clip(filter_color, 0.0, 4.0)))
    if color_index == 0:
        return None
    intensity_index = int(round(_clip(filter_intensity, 0.0, 2.0)))
    return _FILTER_WEIGHTS_TABLE[color_index][intensity_index]


_ASTIA_GRADE = _GradeParams(
    contrast=-10.0,
    highlights=-15.0,
    shadows=8.0,
    global_saturation=1.02,
    hsl_saturation={"red": 3.0, "orange": 5.0, "blue": 5.0},
    hsl_luminance={"orange": 4.0},
    temperature=150.0,
    tint=2.0,
    split_tone_highlight_hue=40.0,
    split_tone_highlight_strength=3.0,
    split_tone_shadow_hue=220.0,
    split_tone_shadow_strength=2.0,
    clarity=-4.0,
    sharpness=5.0,
    grain_std=0.006,
    grain_size=0.6,
)


def _astia(image: numpy.ndarray) -> numpy.ndarray:
    """The precise, externally-calibrated Astia recipe -- soft contrast,
    brightened skin tones (hsl_luminance on "orange"), present but restrained
    color, built on the generic parametric grade engine.
    """
    return _apply_parametric_grade(image, _ASTIA_GRADE)


_PRO_NEG_STD_GRADE = _GradeParams(
    contrast=-20.0,
    highlights=-20.0,
    shadows=15.0,
    global_saturation=0.85,
    hsl_saturation={
        "red": -8.0,
        "orange": -3.0,
        "yellow": -10.0,
        "green": -8.0,
        "cyan": -8.0,
        "blue": -8.0,
        "magenta": -8.0,
    },
    hsl_luminance={"orange": 5.0},
    temperature=100.0,
    tint=1.0,
    clarity=-5.0,
    sharpness=2.0,
    grain_std=0.006,
    grain_size=0.6,
)


def _pro_neg_std(image: numpy.ndarray) -> numpy.ndarray:
    """The precise, externally-calibrated Pro Neg. Std recipe -- neutral,
    malleable rendering with soft gradients and natural skin tones, built on
    the generic parametric grade engine. "Autres couleurs -8%" (the
    calibration's own wording for every hue not individually named) is
    expressed as an explicit -8% entry on every remaining named hue center
    (green/cyan/blue/magenta) rather than a separate "default" mechanism --
    with windows spaced <=60 deg apart across all 7 named centers, this
    already covers the full hue circle with overlap.
    """
    return _apply_parametric_grade(image, _PRO_NEG_STD_GRADE)


_ETERNA_GRADE = _GradeParams(
    contrast=-32.0,
    highlights=-35.0,
    shadows=25.0,
    black_clip=0.025,  # the calibration's "Niveau minimal des noirs" -- same
                        # mechanism/field as Acros Pro's "Écrêtage des noirs".
    global_saturation=0.68,
    hsl_saturation={"red": -15.0, "yellow": -20.0, "green": -25.0, "blue": -15.0},
    split_tone_shadow_hue=200.0,
    split_tone_shadow_strength=6.0,
    split_tone_highlight_hue=40.0,
    split_tone_highlight_strength=5.0,
    clarity=-7.0,
    sharpness=-2.0,
    grain_std=0.010,
    grain_size=1.0,
)


def _eterna(image: numpy.ndarray) -> numpy.ndarray:
    """The precise, externally-calibrated Eterna recipe -- a soft cinema-style
    curve, very progressive highlights, open shadows and contained color,
    built on the generic parametric grade engine.
    """
    return _apply_parametric_grade(image, _ETERNA_GRADE)


_ETERNA_BLEACH_BYPASS_GRADE = _GradeParams(
    contrast=45.0,
    highlights=25.0,
    shadows=-38.0,
    black_clip=0.025,
    global_saturation=0.30,
    hsl_saturation={"orange": 10.0, "cyan": 10.0, "blue": 10.0},  # relative
    # %, applied by _apply_hsl_saturation_by_hue AFTER global_saturation has
    # already crushed saturation to x0.30 -- exactly the "relatif après
    # désaturation" the calibration calls for, no special-casing needed.
    temperature=-350.0,
    tint=-2.0,
    split_tone_shadow_hue=205.0,
    split_tone_shadow_strength=10.0,
    split_tone_highlight_hue=45.0,
    split_tone_highlight_strength=3.0,
    clarity=20.0,
    sharpness=8.0,
    grain_std=0.020,
    grain_size=1.15,
)


def _eterna_bleach_bypass(image: numpy.ndarray) -> numpy.ndarray:
    """The precise, externally-calibrated Eterna Bleach Bypass recipe --
    near-monochrome, cold and metallic, heavily contrasted, built on the
    generic parametric grade engine. Not a true monochrome look (no
    `monochrome_weights`): the heavy `global_saturation=0.30` crush plus the
    cool split tone is what the calibration itself specifies to reach "almost
    monochrome", not a hard R==G==B guarantee.
    """
    return _apply_parametric_grade(image, _ETERNA_BLEACH_BYPASS_GRADE)


_CLASSIC_NEGATIVE_GRADE = _GradeParams(
    # Documented approximation (2026-07-25), not an externally-supplied
    # calibration table like the looks above -- Classic Negative has no
    # reference values available, only its role as the base for 4 recipes
    # (Loki/Sunset Strip/Rizzle Clicks/Glacier Blue). Distinct from Classic
    # Chrome (milder contrast=10, no green cast) and Eterna Bleach Bypass
    # (much heavier crush, global_saturation=0.30): punchier contrast, moderate
    # desaturation, a cyan-green shadow / warm-highlight split tone -- the
    # combination generally associated with this simulation. A starting
    # point, to be refined visually like every other calibration here.
    contrast=22.0,
    highlights=-10.0,
    shadows=-18.0,
    black_clip=0.015,
    global_saturation=0.82,
    hsl_saturation={"green": -18.0, "cyan": -12.0, "orange": -6.0},
    temperature=-70.0,
    tint=-6.0,  # negative -> green push, see _apply_temperature_tint
    split_tone_shadow_hue=185.0,
    split_tone_shadow_strength=9.0,
    split_tone_highlight_hue=48.0,
    split_tone_highlight_strength=4.0,
    clarity=14.0,
    sharpness=6.0,
    grain_std=0.010,
    grain_size=1.0,
)


def _classic_negative(image: numpy.ndarray) -> numpy.ndarray:
    """"Classic Negative" -- a documented approximation (see
    `_CLASSIC_NEGATIVE_GRADE`'s own comment) of Fujifilm's consumer-negative-
    film-inspired simulation, built on the generic parametric grade engine.
    Exposed as its own selectable look (like every other base simulation in
    this file), in addition to serving as the base for four 2026-07-25
    recipes.
    """
    return _apply_parametric_grade(image, _CLASSIC_NEGATIVE_GRADE)


_MONOCHROME_BASE_GRADE = _GradeParams(
    # Documented approximation (2026-07-26), like Classic Negative above --
    # no reference calibration available, only its role as the calibration
    # anchor for two 2026-07-26 recipes ("Monochrome", "Mono Moonlight").
    # Deliberately mild/flat (contrast=8, standard luma weights) rather than
    # Acros Pro's already-punchy look (contrast=30, custom weights, baked-in
    # grain) -- meant to stay a plain B&W reference, with each recipe's own
    # character coming entirely from its own explicit dial values, not from
    # this base. Unlike Classic Negative, NOT itself exposed as a standalone
    # selectable look -- the user's recipe list has no separate "plain,
    # unadjusted Monochrome" entry, only the full "Monochrome" recipe below
    # (Highlights/Shadows/Sharpness/Clarity/Grain/WB/DR/Mono Colour all
    # explicitly specified), so there is nothing un-decorated to expose.
    contrast=8.0,
    monochrome_weights=(0.299, 0.587, 0.114),
)


# ---------------------------------------------------------------------------
# Fuji-scale -> Film-scale conversion constants (2026-07-25). Fuji's in-camera
# Highlights/Shadows/Colour/Sharpness/Clarity dials are each roughly -4..+4;
# Grain Effect is (Off/Weak/Strong) x (Small/Large); White Balance is Kelvin +
# R/B shift (roughly -9..+9 each) or a named preset. Every converted delta is
# anchored to the BASE LOOK's own value (never to a generic neutral/zero) --
# these dials adjust *from* the selected film simulation's baseline on a real
# Fuji camera, not from scratch. Used only by _SUMMER_STORY_GRADE/
# _INKY_DEPTHS_GRADE below; documented here as a reusable, consistent formula
# for any future recipe rather than a one-off guessed number.
# ---------------------------------------------------------------------------
FUJI_SCALE_STEP = 25.0     # Film units per Fuji -4..+4 step (additive), e.g.
                            #   highlights_film = base.highlights + fuji_value * FUJI_SCALE_STEP
                            # applied the same way to shadows/sharpness/clarity.
                            # (Film's 200-wide range / Fuji's 8-step range = 25.)
FUJI_COLOUR_STEP = 0.075   # multiplicative -- global_saturation is a 0..2 ratio:
                            #   global_saturation = base.global_saturation * (1 + fuji_colour * FUJI_COLOUR_STEP)
GRAIN_EFFECT_TABLE = {"off": 0.0, "weak": 0.010, "strong": 0.022}  # absolute override of grain_std
GRAIN_SIZE_TABLE = {"small": 0.6, "large": 1.4}  # absolute override of grain_size (internal-only, see module docstring)

_WB_REFERENCE_KELVIN = 5500.0
_WB_TEMPERATURE_PER_KELVIN = 0.4
_WB_TEMPERATURE_PER_SHIFT_UNIT = 40.0
_WB_TINT_PER_SHIFT_UNIT = 2.0


def _kelvin_shift_to_temperature_tint(
    kelvin: float, red_shift: float, blue_shift: float, tint_baseline: float = 0.0
) -> tuple[float, float]:
    """Converts a Fuji-style white-balance spec (Kelvin + R/B shift, each
    roughly -9..+9) to this engine's own (non-Planckian, see
    `_apply_temperature_tint`) temperature/tint scale. The R/B differential
    maps to the warm/cool `temperature` axis, their average to the
    green/magenta `tint` axis (an R/B shift that's symmetric, e.g. -2/-2, is
    a pure warm/cool move with no green/magenta component).
    """
    diff = (red_shift - blue_shift) / 2.0
    average = (red_shift + blue_shift) / 2.0
    temperature = _clip(
        (kelvin - _WB_REFERENCE_KELVIN) * _WB_TEMPERATURE_PER_KELVIN + diff * _WB_TEMPERATURE_PER_SHIFT_UNIT,
        -1000.0,
        1000.0,
    )
    tint = _clip(tint_baseline + average * _WB_TINT_PER_SHIFT_UNIT, -20.0, 20.0)
    return temperature, tint


def _mono_color_to_temperature_tint(wc: float, mg: float) -> tuple[float, float]:
    """Converts Fuji's "Mono Colour" WC/MG dial pair (each roughly -9..+9,
    2026-07-26) to this engine's own temperature/tint scale, reusing the
    exact per-shift-unit constants White Balance already uses -- WC maps 1:1
    to the warm/cool `temperature` axis, MG 1:1 to the green/magenta `tint`
    axis (unlike `_kelvin_shift_to_temperature_tint`'s R/B-shift pair, WC/MG
    are already independent axes, no diff/average step needed).
    """
    return (
        _clip(wc * _WB_TEMPERATURE_PER_SHIFT_UNIT, -1000.0, 1000.0),
        _clip(mg * _WB_TINT_PER_SHIFT_UNIT, -20.0, 20.0),
    )


# Named white-balance presets, keyed lowercase, each mapped to a (kelvin,
# tint_baseline) pair fed through _kelvin_shift_to_temperature_tint alongside
# a recipe's own R/B shift. "Underwater" (recipe-community-documented cool/
# blue cast, not a manufacturer-published Kelvin figure) was the first;
# "auto"/"daylight"/"shade" added 2026-07-25 for Loki/Glacier Blue/Sunset
# Strip. "auto" and "daylight" deliberately coincide (both just
# _WB_REFERENCE_KELVIN with no baseline) -- real Auto WB is scene-dependent
# and not resolvable at recipe-authoring time, so it's approximated by the
# same neutral reference Daylight already IS; "shade" uses ~8000K, the usual
# assumed color temperature of open shade light.
_WB_PRESET_TABLE = {
    "underwater": {"kelvin": 3800.0, "tint_baseline": 6.0},
    "auto": {"kelvin": _WB_REFERENCE_KELVIN, "tint_baseline": 0.0},
    "daylight": {"kelvin": _WB_REFERENCE_KELVIN, "tint_baseline": 0.0},
    "shade": {"kelvin": 8000.0, "tint_baseline": 0.0},
}


_INKY_DEPTHS_GRADE = _ETERNA_BLEACH_BYPASS_GRADE._replace(
    highlights=_clip(_ETERNA_BLEACH_BYPASS_GRADE.highlights + 4 * FUJI_SCALE_STEP, -100.0, 100.0),  # Highlights +4
    shadows=_ETERNA_BLEACH_BYPASS_GRADE.shadows + 1 * FUJI_SCALE_STEP,  # Shadows +1
    global_saturation=_clip(
        _ETERNA_BLEACH_BYPASS_GRADE.global_saturation * (1 + -4 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour -4
    sharpness=_clip(_ETERNA_BLEACH_BYPASS_GRADE.sharpness + 1 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpness +1
    # Clarity 0 (Fuji value) -- Eterna Bleach Bypass's own clarity (20.0) passes through unchanged.
    grain_std=GRAIN_EFFECT_TABLE["weak"],
    grain_size=GRAIN_SIZE_TABLE["large"],
    dynamic_range=1.0,       # DR200
    color_chrome_effect=2.0,  # Strong
    color_chrome_blue=0.0,    # Off
)
_INKY_DEPTHS_GRADE = _INKY_DEPTHS_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["underwater"]["kelvin"],
                red_shift=-3.0,
                blue_shift=3.0,
                tint_baseline=_WB_PRESET_TABLE["underwater"]["tint_baseline"],
            ),
        )
    )
)


def _inky_depths(image: numpy.ndarray) -> numpy.ndarray:
    """"Inky Depths" -- an externally-supplied Fujifilm-recipe-style look
    built on Eterna Bleach Bypass: pushed highlights, richer shadows, heavily
    desaturated, sharper, weak+large grain, a cool "Underwater"-preset White
    Balance push, DR200 and a strong Color Chrome Effect. See the module
    docstring (2026-07-25) for the EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _INKY_DEPTHS_GRADE)


# ---------------------------------------------------------------------------
# Five more externally-supplied recipes (2026-07-25), moved into their own
# "Bleach Bypass" workflow row alongside Eterna Bleach Bypass/Inky Depths
# (config_workflow.json; same film_look addon, category="film", a second row
# just listing a different preset subset -- no engine change needed for that
# split). Ecowarrior builds on Eterna Bleach Bypass; the other four build on
# Classic Negative.
# ---------------------------------------------------------------------------

_ECOWARRIOR_GRADE = _ETERNA_BLEACH_BYPASS_GRADE._replace(
    highlights=_ETERNA_BLEACH_BYPASS_GRADE.highlights + 1 * FUJI_SCALE_STEP,   # Highlights +1
    shadows=_ETERNA_BLEACH_BYPASS_GRADE.shadows + 3 * FUJI_SCALE_STEP,         # Shadows +3
    global_saturation=_clip(
        _ETERNA_BLEACH_BYPASS_GRADE.global_saturation * (1 + 4 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour +4
    sharpness=_clip(_ETERNA_BLEACH_BYPASS_GRADE.sharpness + 2 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpness +2
    # Clarity 0 (Fuji value) -- Eterna Bleach Bypass's own clarity (20.0) passes through unchanged.
    grain_std=GRAIN_EFFECT_TABLE["strong"],
    grain_size=GRAIN_SIZE_TABLE["small"],
    dynamic_range=1.0,        # DR200
    color_chrome_effect=2.0,  # Strong
    color_chrome_blue=0.0,    # Off
)
_ECOWARRIOR_GRADE = _ECOWARRIOR_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(7700.0, red_shift=0.0, blue_shift=7.0),
        )
    )
)


def _ecowarrior(image: numpy.ndarray) -> numpy.ndarray:
    """"Ecowarrior" -- an externally-supplied Fujifilm-recipe-style look
    built on Eterna Bleach Bypass: lifted highlights and much lighter
    shadows, richer colour, punchier sharpness, strong+small grain, a warm
    White Balance push, DR200 and a strong Color Chrome Effect. See the
    module docstring (2026-07-25) for the EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _ECOWARRIOR_GRADE)


_LOKI_GRADE = _CLASSIC_NEGATIVE_GRADE._replace(
    highlights=_CLASSIC_NEGATIVE_GRADE.highlights + 4 * FUJI_SCALE_STEP,  # Highlights +4
    shadows=_CLASSIC_NEGATIVE_GRADE.shadows + 4 * FUJI_SCALE_STEP,        # Shadows +4
    # Colour 0 -- Classic Negative's own global_saturation (0.82) passes through unchanged.
    sharpness=_clip(_CLASSIC_NEGATIVE_GRADE.sharpness + 3 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpness +3
    clarity=_clip(_CLASSIC_NEGATIVE_GRADE.clarity + 3 * FUJI_SCALE_STEP, -100.0, 100.0),       # Clarity +3
    grain_std=GRAIN_EFFECT_TABLE["off"],
    dynamic_range=0.0,        # DR100
    color_chrome_effect=0.0,  # Off
    color_chrome_blue=0.0,    # Off
)
_LOKI_GRADE = _LOKI_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["auto"]["kelvin"], red_shift=3.0, blue_shift=-5.0,
                tint_baseline=_WB_PRESET_TABLE["auto"]["tint_baseline"],
            ),
        )
    )
)


def _loki(image: numpy.ndarray) -> numpy.ndarray:
    """"Loki" -- an externally-supplied Fujifilm-recipe-style look built on
    Classic Negative: strongly lifted highlights and shadows, punchier
    sharpness/clarity, no grain, a neutral-Auto White Balance push, DR100 and
    Color Chrome Effect/Blue both off. See the module docstring (2026-07-25)
    for the EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _LOKI_GRADE)


_SUNSET_STRIP_GRADE = _CLASSIC_NEGATIVE_GRADE._replace(
    highlights=_CLASSIC_NEGATIVE_GRADE.highlights + -1 * FUJI_SCALE_STEP,  # Highlights -1
    shadows=_CLASSIC_NEGATIVE_GRADE.shadows + -1 * FUJI_SCALE_STEP,        # Shadows -1
    global_saturation=_clip(
        _CLASSIC_NEGATIVE_GRADE.global_saturation * (1 + 2 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour +2
    sharpness=_clip(_CLASSIC_NEGATIVE_GRADE.sharpness + -4 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpness -4
    clarity=-20.0,  # fixed override (user request, 2026-07-26) -- was -86.0 via the Fuji-scale formula above
    grain_std=GRAIN_EFFECT_TABLE["weak"],
    grain_size=GRAIN_SIZE_TABLE["small"],
    dynamic_range=2.0,        # DR400
    color_chrome_effect=0.0,  # Off
    color_chrome_blue=1.0,    # Weak
)
_SUNSET_STRIP_GRADE = _SUNSET_STRIP_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["shade"]["kelvin"], red_shift=0.0, blue_shift=-9.0,
                tint_baseline=_WB_PRESET_TABLE["shade"]["tint_baseline"],
            ),
        )
    )
)


def _sunset_strip(image: numpy.ndarray) -> numpy.ndarray:
    """"Sunset Strip" -- an externally-supplied Fujifilm-recipe-style look
    (source recipe name "Sunset Strip E6") built on Classic Negative: softer
    highlights/shadows, slightly richer colour, much softer sharpness/
    clarity, weak+small grain, a warm Shade-preset White Balance push, DR400
    and a weak Color Chrome Blue. See the module docstring (2026-07-25) for
    the EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _SUNSET_STRIP_GRADE)


_RIZZLE_CLICKS_GRADE = _CLASSIC_NEGATIVE_GRADE._replace(
    highlights=_CLASSIC_NEGATIVE_GRADE.highlights + -1 * FUJI_SCALE_STEP,  # Highlights -1
    shadows=_CLASSIC_NEGATIVE_GRADE.shadows + -1 * FUJI_SCALE_STEP,        # Shadows -1
    global_saturation=_clip(
        _CLASSIC_NEGATIVE_GRADE.global_saturation * (1 + -1 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour -1
    # Sharpness 0 -- Classic Negative's own sharpness (6.0) passes through unchanged.
    clarity=-20.0,  # fixed override (user request, 2026-07-26) -- was -36.0 via the Fuji-scale formula above
    grain_std=GRAIN_EFFECT_TABLE["strong"],
    grain_size=GRAIN_SIZE_TABLE["small"],
    dynamic_range=2.0,        # DR400
    color_chrome_effect=2.0,  # Strong
    color_chrome_blue=0.0,    # Off
)
_RIZZLE_CLICKS_GRADE = _RIZZLE_CLICKS_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(4000.0, red_shift=7.0, blue_shift=-7.0),
        )
    )
)


def _rizzle_clicks(image: numpy.ndarray) -> numpy.ndarray:
    """"Rizzle Clicks" -- an externally-supplied Fujifilm-recipe-style look
    built on Classic Negative: softer highlights/shadows, slightly muted
    colour, unchanged sharpness, softer clarity, strong+small grain, a warm
    White Balance push, DR400 and a strong Color Chrome Effect. See the
    module docstring (2026-07-25) for the EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _RIZZLE_CLICKS_GRADE)


_GLACIER_BLUE_GRADE = _CLASSIC_NEGATIVE_GRADE._replace(
    highlights=_CLASSIC_NEGATIVE_GRADE.highlights + -1 * FUJI_SCALE_STEP,  # Highlights -1
    shadows=_CLASSIC_NEGATIVE_GRADE.shadows + 2 * FUJI_SCALE_STEP,         # Shadows +2
    global_saturation=_clip(
        _CLASSIC_NEGATIVE_GRADE.global_saturation * (1 + -4 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour -4
    # Sharpness 0 -- Classic Negative's own sharpness (6.0) passes through unchanged.
    # Clarity 0 -- Classic Negative's own clarity (14.0) passes through unchanged.
    grain_std=GRAIN_EFFECT_TABLE["off"],
    dynamic_range=1.0,        # DR200
    color_chrome_effect=2.0,  # Strong
    color_chrome_blue=1.0,    # Weak
)
_GLACIER_BLUE_GRADE = _GLACIER_BLUE_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["daylight"]["kelvin"], red_shift=-4.0, blue_shift=1.0,
                tint_baseline=_WB_PRESET_TABLE["daylight"]["tint_baseline"],
            ),
        )
    )
)


def _glacier_blue(image: numpy.ndarray) -> numpy.ndarray:
    """"Glacier Blue" -- an externally-supplied Fujifilm-recipe-style look
    built on Classic Negative: softer highlights, lifted shadows, notably
    muted colour, unchanged sharpness/clarity, no grain, a cool Daylight-
    preset White Balance push, DR200 and a strong Color Chrome Effect +
    weak Color Chrome Blue. See the module docstring (2026-07-25) for the
    EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _GLACIER_BLUE_GRADE)


# ---------------------------------------------------------------------------
# Seven more externally-supplied recipes (2026-07-26), in their own new
# "Monochrome" workflow row (config_workflow.json; same film_look addon,
# category="film", a third row over the same addon -- see the "Bleach
# Bypass" precedent above for why no engine/routing change is needed for
# this). Monochrome and Mono Moonlight build on the new, module-internal
# _MONOCHROME_BASE_GRADE; Titanium on Eterna Bleach Bypass; Underglow,
# Milestone and Quicklime on Classic Negative/Classic Chrome Pro; Gilt Trip
# on Acros Pro. Three of the seven (Monochrome, Mono Moonlight, Gilt Trip)
# also set the new `mono_color_wc`/`mono_color_mg` fields (see
# _apply_monochrome_grade's 2026-07-26 note) -- absent/zero for the other
# four, which are color (non-monochrome_weights) looks.
# ---------------------------------------------------------------------------

_TITANIUM_GRADE = _ETERNA_BLEACH_BYPASS_GRADE._replace(
    highlights=_ETERNA_BLEACH_BYPASS_GRADE.highlights + -0.5 * FUJI_SCALE_STEP,  # Highlights -0.5
    shadows=_ETERNA_BLEACH_BYPASS_GRADE.shadows + -1.5 * FUJI_SCALE_STEP,        # Shadows -1.5
    global_saturation=_clip(
        _ETERNA_BLEACH_BYPASS_GRADE.global_saturation * (1 + -4 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour -4
    sharpness=_clip(_ETERNA_BLEACH_BYPASS_GRADE.sharpness + 1 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpness +1
    # Clarity 0 (Fuji value) -- Eterna Bleach Bypass's own clarity (20.0) passes through unchanged.
    grain_std=GRAIN_EFFECT_TABLE["weak"],
    grain_size=GRAIN_SIZE_TABLE["small"],
    dynamic_range=2.0,        # DR400
    color_chrome_effect=0.0,  # Off
    color_chrome_blue=1.0,    # Weak
)
_TITANIUM_GRADE = _TITANIUM_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["shade"]["kelvin"], red_shift=-3.0, blue_shift=3.0,
                tint_baseline=_WB_PRESET_TABLE["shade"]["tint_baseline"],
            ),
        )
    )
)


def _titanium(image: numpy.ndarray) -> numpy.ndarray:
    """"Titanium" -- an externally-supplied Fujifilm-recipe-style look built
    on Eterna Bleach Bypass: slightly softer highlights and shadows, muted
    colour, a touch sharper, weak+small grain, a warm Shade-preset White
    Balance push, DR400 and a weak Color Chrome Blue. See the module
    docstring's EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _TITANIUM_GRADE)


_MILESTONE_GRADE = _CLASSIC_CHROME_PRO_GRADE._replace(
    highlights=_CLASSIC_CHROME_PRO_GRADE.highlights + 1 * FUJI_SCALE_STEP,  # Highlights +1
    shadows=_CLASSIC_CHROME_PRO_GRADE.shadows + -1 * FUJI_SCALE_STEP,        # Shadows -1
    global_saturation=_clip(
        _CLASSIC_CHROME_PRO_GRADE.global_saturation * (1 + -2 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour -2
    # Sharpness 0 (Fuji value) -- Classic Chrome's own sharpness (5.0) passes through unchanged.
    clarity=_clip(_CLASSIC_CHROME_PRO_GRADE.clarity + 2 * FUJI_SCALE_STEP, -100.0, 100.0),  # Clarity +2
    grain_std=GRAIN_EFFECT_TABLE["off"],
    # Dynamic Range 0.0 (DR100, Classic Chrome's own default) -- unchanged.
    color_chrome_effect=1.0,  # Weak
    color_chrome_blue=0.0,    # Off
)
_MILESTONE_GRADE = _MILESTONE_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(10000.0, red_shift=-5.0, blue_shift=8.0),  # literal Kelvin, no named preset
        )
    )
)


def _milestone(image: numpy.ndarray) -> numpy.ndarray:
    """"Milestone" -- an externally-supplied Fujifilm-recipe-style look built
    on Classic Chrome: lifted highlights, softer shadows, muted colour,
    punchier clarity, no grain, a cool literal-10000K White Balance push,
    DR100 (unchanged) and a weak Color Chrome Effect. See the module
    docstring's EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _MILESTONE_GRADE)


_QUICKLIME_GRADE = _CLASSIC_CHROME_PRO_GRADE._replace(
    highlights=_CLASSIC_CHROME_PRO_GRADE.highlights + 2 * FUJI_SCALE_STEP,  # Highlights +2
    # Shadows 0 (Fuji value) -- Classic Chrome's own shadows (-20.0) passes through unchanged.
    global_saturation=_clip(
        _CLASSIC_CHROME_PRO_GRADE.global_saturation * (1 + -4 * FUJI_COLOUR_STEP), 0.0, 2.0
    ),  # Colour -4
    sharpness=_clip(_CLASSIC_CHROME_PRO_GRADE.sharpness + -2 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpness -2
    clarity=-20.0,  # fixed override (user request, 2026-07-26) -- was -40.0 via the Fuji-scale formula above
    grain_std=GRAIN_EFFECT_TABLE["off"],
    dynamic_range=1.0,        # DR200
    color_chrome_effect=1.0,  # Weak
    color_chrome_blue=0.0,    # Off
)
_QUICKLIME_GRADE = _QUICKLIME_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["shade"]["kelvin"], red_shift=-2.0, blue_shift=-4.0,
                tint_baseline=_WB_PRESET_TABLE["shade"]["tint_baseline"],
            ),
        )
    )
)


def _quicklime(image: numpy.ndarray) -> numpy.ndarray:
    """"Quicklime" -- an externally-supplied Fujifilm-recipe-style look built
    on Classic Chrome: lifted highlights, muted colour, softer sharpness/
    clarity, no grain, a warm Shade-preset White Balance push, DR200 and a
    weak Color Chrome Effect. See the module docstring's EV Comp./ISO N.R.
    scope note.
    """
    return _apply_parametric_grade(image, _QUICKLIME_GRADE)


# ---------------------------------------------------------------------------
# Three more externally-supplied recipes (2026-08-05), added to the existing
# "B&W" workflow row alongside Acros/the four "Acros + Couleur" presets --
# same film_look addon, same row, no routing change needed. Kodak T-MAX
# builds on the module-internal Monochrome base (Film Simulation: Monochrome
# in the source recipe); Kodak T-MAX 3200 and Kodak Tri-X build on Acros Pro
# (Film Simulation: Acros). See the module docstring's EV Comp./ISO N.R.
# scope note -- none of the three set those fields.
# ---------------------------------------------------------------------------

_KODAK_TMAX_3200_GRADE = _ACROS_PRO_GRADE._replace(
    highlights=_ACROS_PRO_GRADE.highlights + 1 * FUJI_SCALE_STEP,  # Highlight +1
    shadows=_ACROS_PRO_GRADE.shadows + 3 * FUJI_SCALE_STEP,  # Shadow +3
    sharpness=_clip(_ACROS_PRO_GRADE.sharpness + 2 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpness +2
    clarity=_clip(_ACROS_PRO_GRADE.clarity + 1 * FUJI_SCALE_STEP, -100.0, 100.0),  # Clarity +1
    grain_std=GRAIN_EFFECT_TABLE["strong"],
    grain_size=GRAIN_SIZE_TABLE["large"],
    dynamic_range=2.0,  # DR400
    mono_color_wc=-1.0,  # WC -1
    mono_color_mg=-1.0,  # MG -1
    # Color Chrome Effect/FX Blue Off -- already the base's own default (0.0).
)
_KODAK_TMAX_3200_GRADE = _KODAK_TMAX_3200_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            # Literal 5500K (not a named preset), like Milestone's own White
            # Balance -- _kelvin_shift_to_temperature_tint accepts any float.
            _kelvin_shift_to_temperature_tint(5500.0, red_shift=4.0, blue_shift=7.0),
        )
    )
)


def _kodak_tmax_3200(image: numpy.ndarray) -> numpy.ndarray:
    """"Kodak T-MAX 3200" -- a Kodak-recipe-style look built on Acros: lifted
    highlights and shadows, punchier sharpness/clarity, strong+large grain, a
    warm 5500K White Balance push, a cool-leaning Mono Colour toning and
    DR400. See the module docstring's EV Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _KODAK_TMAX_3200_GRADE)


_KODAK_TRIX_GRADE = _ACROS_PRO_GRADE._replace(
    # Highlight 0 (Fuji value) -- Acros's own highlights (10.0) passes through unchanged.
    shadows=_ACROS_PRO_GRADE.shadows + 3 * FUJI_SCALE_STEP,  # Shadow +3
    sharpness=_clip(_ACROS_PRO_GRADE.sharpness + 1 * FUJI_SCALE_STEP, -100.0, 100.0),  # Sharpening +1
    clarity=100.0,  # base 18.0 + 4*25=118 clipped to the engine's [-100,100] range
    grain_std=GRAIN_EFFECT_TABLE["strong"],
    grain_size=GRAIN_SIZE_TABLE["large"],
    dynamic_range=1.0,  # DR200
    # Color Chrome Effect: Strong (recipe value) -- declared for fidelity to
    # the source recipe, but a documented no-op here: film_look dispatches any
    # look with monochrome_weights set (true for this look) to
    # _apply_monochrome_grade, which never calls _apply_color_chrome_effect --
    # see that function's own docstring. Kept anyway, same treatment as
    # grain_size (declared, known-inert on some paths).
    color_chrome_effect=2.0,  # Strong
    # Color Chrome FX Blue Off -- already the base's own default (0.0).
    # No Toning (Mono Colour) specified in the source recipe -- Acros's own
    # mono_color_wc/mg defaults (0.0/0.0, i.e. Off) pass through unchanged.
)
_KODAK_TRIX_GRADE = _KODAK_TRIX_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["daylight"]["kelvin"], red_shift=9.0, blue_shift=-9.0,
                tint_baseline=_WB_PRESET_TABLE["daylight"]["tint_baseline"],
            ),
        )
    )
)


def _kodak_trix(image: numpy.ndarray) -> numpy.ndarray:
    """"Kodak Tri-X" -- a Kodak-recipe-style look built on Acros: unchanged
    highlights, lifted shadows, punchier sharpening, clarity clipped to the
    engine's maximum, strong+large grain, a warm Daylight-preset White
    Balance push, a strong (but visually inert on this monochrome path) Color
    Chrome Effect, DR200, no Mono Colour toning. See the module docstring's EV
    Comp./ISO N.R. scope note.
    """
    return _apply_parametric_grade(image, _KODAK_TRIX_GRADE)


# ---------------------------------------------------------------------------
# Five more externally-supplied recipes (2026-08-05, later still), added to
# the "B&W" workflow row alongside Acros/the Acros + Couleur presets/the
# three Kodak recipes above -- same film_look addon, same row. Agfa APX and
# Ilford XP2 build on Acros Pro (Film Simulation: Acros); Ilford Delta/FP4/
# HP5 build on the module-internal Monochrome base (Film Simulation:
# Monochrome). Grain size (Small/Large) is unspecified in the source recipe
# for Agfa APX/Ilford Delta/Ilford XP2 -- Large chosen per explicit user
# decision (2026-08-05).
# ---------------------------------------------------------------------------

_ILFORD_FP4_GRADE = _MONOCHROME_BASE_GRADE._replace(
    highlights=_MONOCHROME_BASE_GRADE.highlights + -0.5 * FUJI_SCALE_STEP,  # Highlight -0.5
    shadows=_MONOCHROME_BASE_GRADE.shadows + -1.5 * FUJI_SCALE_STEP,  # Shadow -1.5
    # Sharpness 0 (Fuji value) -- Monochrome base's own sharpness (0.0) passes through unchanged.
    clarity=_clip(_MONOCHROME_BASE_GRADE.clarity + 2 * FUJI_SCALE_STEP, -100.0, 100.0),  # Clarity +2
    grain_std=GRAIN_EFFECT_TABLE["weak"],
    grain_size=GRAIN_SIZE_TABLE["large"],
    dynamic_range=1.0,  # DR200
    # Monochromatic Color 0 WC & 0 MG, Color Chrome Effect/FX Blue Off -- all
    # already the base's own default (0.0), no override needed.
)
_ILFORD_FP4_GRADE = _ILFORD_FP4_GRADE._replace(
    **dict(
        zip(
            ("temperature", "tint"),
            _kelvin_shift_to_temperature_tint(
                _WB_PRESET_TABLE["daylight"]["kelvin"], red_shift=6.0, blue_shift=-8.0,
                tint_baseline=_WB_PRESET_TABLE["daylight"]["tint_baseline"],
            ),
        )
    )
)


def _ilford_fp4(image: numpy.ndarray) -> numpy.ndarray:
    """"Ilford FP4" -- a film-recipe-style look built on the module-internal
    Monochrome base: softer highlights and shadows, punchier clarity,
    weak+large grain, a warm Daylight-preset White Balance push, no Mono
    Colour toning, DR200. See the module docstring's EV Comp./ISO N.R. scope
    note.
    """
    return _apply_parametric_grade(image, _ILFORD_FP4_GRADE)


_LOOK_TRANSFORMS = {
    "classic_chrome_pro": _classic_chrome_pro,
    "velvia_pro": _velvia_pro,
    "acros_pro": _acros_pro,
    "astia": _astia,
    "pro_neg_std": _pro_neg_std,
    "eterna": _eterna,
    "eterna_bleach_bypass": _eterna_bleach_bypass,
    "inky_depths": _inky_depths,
    "classic_negative": _classic_negative,
    "ecowarrior": _ecowarrior,
    "loki": _loki,
    "sunset_strip": _sunset_strip,
    "rizzle_clicks": _rizzle_clicks,
    "glacier_blue": _glacier_blue,
    "titanium": _titanium,
    "milestone": _milestone,
    "quicklime": _quicklime,
    "kodak_tmax_3200": _kodak_tmax_3200,
    "kodak_trix": _kodak_trix,
    "ilford_fp4": _ilford_fp4,
}

# Base calibration per look, keyed the same as _LOOK_TRANSFORMS -- needed
# alongside it (not instead of it) so film_look's Zoom-parameter override path
# (below) can read a look's starting _GradeParams directly and adjust it,
# rather than only being able to call the look as an opaque, non-adjustable
# function the way _LOOK_TRANSFORMS's entries are used elsewhere.
_GRADES: dict[str, "_GradeParams"] = {
    "classic_chrome_pro": _CLASSIC_CHROME_PRO_GRADE,
    "velvia_pro": _VELVIA_PRO_GRADE,
    "acros_pro": _ACROS_PRO_GRADE,
    "astia": _ASTIA_GRADE,
    "pro_neg_std": _PRO_NEG_STD_GRADE,
    "eterna": _ETERNA_GRADE,
    "eterna_bleach_bypass": _ETERNA_BLEACH_BYPASS_GRADE,
    "inky_depths": _INKY_DEPTHS_GRADE,
    "classic_negative": _CLASSIC_NEGATIVE_GRADE,
    "ecowarrior": _ECOWARRIOR_GRADE,
    "loki": _LOKI_GRADE,
    "sunset_strip": _SUNSET_STRIP_GRADE,
    "rizzle_clicks": _RIZZLE_CLICKS_GRADE,
    "glacier_blue": _GLACIER_BLUE_GRADE,
    "titanium": _TITANIUM_GRADE,
    "milestone": _MILESTONE_GRADE,
    "quicklime": _QUICKLIME_GRADE,
    "kodak_tmax_3200": _KODAK_TMAX_3200_GRADE,
    "kodak_trix": _KODAK_TRIX_GRADE,
    "ilford_fp4": _ILFORD_FP4_GRADE,
}

# Neutral (no `look` key at all -- the "neutral" ThumbnailPreset has no
# preset_parameters) has no calibration of its own, but Zoom-only manual
# overrides should still be able to apply on top of an otherwise-untouched
# image (bug fix, 2026-07-23: sliders had no effect on Neutral). An
# all-defaults _GradeParams() run through the same parametric engine is a
# proven bit-identical no-op (test_apply_parametric_grade_neutral_params_is_
# bit_identical) when nothing overrides it, so `film_look` below only reaches
# for this when at least one override key is actually present -- Neutral's
# ordinary zero-cost passthrough (no overrides) is otherwise unchanged.
_NEUTRAL_GRADE = _GradeParams()


# Zoom-only manual adjustment layer (feature: Zoom overlay screen,
# 2026-07-22; switched from a delta/scale model to an ABSOLUTE-value model on
# 2026-07-22 after user feedback: a slider must seed with the value actually
# in effect for the selected look, e.g. Velvia's own calibrated contrast
# (~28), not a neutral "no adjustment yet" delta of 0). Each field name here
# matches a real _GradeParams attribute 1:1, with that attribute's own
# documented natural range (see _GradeParams's inline comments) as bounds --
# if the identifier is present in `params`, it REPLACES the look's own value
# outright (clipped to these bounds); if absent, the look's own calibrated
# value passes through completely untouched. hsl_saturation/hsl_luminance/
# split_tone_* stay SCALE-based (multiplicative, neutral=1.0) since those
# fields are per-hue dicts / a hue+strength pair, not a single scalar with
# one absolute value to seed a slider from.
_ABSOLUTE_FIELD_BOUNDS: dict[str, tuple[float, float]] = {
    "contrast": (-100.0, 100.0),
    "highlights": (-100.0, 100.0),
    "shadows": (-100.0, 100.0),
    "black_clip": (0.0, 0.10),
    "global_saturation": (0.0, 2.0),
    "temperature": (-1000.0, 1000.0),
    "tint": (-20.0, 20.0),
    "clarity": (-100.0, 100.0),
    "sharpness": (-100.0, 100.0),
    "grain_std": (0.0, 0.05),
    "color_chrome_effect": (0.0, 2.0),
    "color_chrome_blue": (0.0, 2.0),
    "dynamic_range": (0.0, 2.0),
    "mono_color_wc": (-20.0, 20.0),
    "mono_color_mg": (-20.0, 20.0),
}

# The 20 slider identifiers that actually affect a grade (used by film_look
# to decide whether Neutral -- which has no calibration of its own -- should
# still run the parametric engine). `intensity` is deliberately excluded:
# alone, against an all-defaults _NEUTRAL_GRADE, it blends toward an
# identical output, so it has no effect on Neutral either way -- including it
# here would just run the engine for nothing.
_ZOOM_OVERRIDE_KEYS = frozenset(_ABSOLUTE_FIELD_BOUNDS) | {
    "hsl_saturation_scale",
    "hsl_luminance_scale",
    "split_tone_scale",
    "filter_color",
    "filter_intensity",
}


def _override_numeric(params: dict[str, Any], identifier: str, default: float) -> float:
    value = params.get(identifier, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _apply_grade_overrides(base: "_GradeParams", params: dict[str, Any]) -> "_GradeParams":
    """All 20 zoom-only identifiers below (15 absolute + 3 scale + 2
    filter-table) are declared as ParameterDescription entries further down
    (zoom_only=True), and are otherwise absent from every preset's own
    preset_parameters (except the four "Acros + Couleur" presets, which
    deliberately reuse filter_color/filter_intensity to seed themselves --
    see their own ThumbnailPreset comment) -- so ordinary thumbnail/preview
    rendering never reaches the non-trivial branch here for every other
    preset (confirmed by the early return below, which keeps `base` itself,
    same object, when nothing is overridden -- guaranteeing the pre-existing
    bit-identical-output tests are unaffected). The one exception is `base`
    being `_NEUTRAL_GRADE`: `film_look` only calls this at all for Neutral
    once it has already confirmed an override key is present, so the
    non-trivial branch below IS reached in that specific case -- by design,
    that's the 2026-07-23 fix."""
    absolute_overrides: dict[str, float] = {}
    for field_name, (minimum, maximum) in _ABSOLUTE_FIELD_BOUNDS.items():
        if field_name in params:
            absolute_overrides[field_name] = _clip(
                _override_numeric(params, field_name, getattr(base, field_name)), minimum, maximum
            )

    # Dynamic Range gotcha (2026-07-25): _resolve_dynamic_range runs a SECOND
    # time, unconditionally, wherever this grade is actually rendered
    # (_apply_parametric_grade/_apply_monochrome_grade) -- necessary so a
    # look's own `dynamic_range` still has an effect when this function
    # returns `base` untouched (no overrides at all, see the early return
    # below). But `resolve_zoom_values` seeds the highlights/shadows/
    # black_clip sliders with THAT already-DR-composed value (Zoom overlay's
    # absolute-value model) -- an explicit override of one of those three
    # fields is therefore itself the final effective value the user is
    # setting, and must NOT have the same delta added a second time
    # downstream. Pre-subtract it here (using whichever `dynamic_range` value
    # will actually be in effect after this call -- the override if the
    # caller also touched that slider, else the look's own), so the later,
    # unconditional re-application nets out to exactly the override value.
    dr_level = _clip(absolute_overrides.get("dynamic_range", base.dynamic_range), 0.0, 2.0)
    if dr_level != 0.0:
        highlight_delta, shadow_delta, black_clip_delta = _DR_DELTA_PER_LEVEL
        if "highlights" in absolute_overrides:
            absolute_overrides["highlights"] -= dr_level * highlight_delta
        if "shadows" in absolute_overrides:
            absolute_overrides["shadows"] -= dr_level * shadow_delta
        if "black_clip" in absolute_overrides:
            absolute_overrides["black_clip"] -= dr_level * black_clip_delta

    hsl_saturation_scale = _override_numeric(params, "hsl_saturation_scale", 1.0)
    hsl_luminance_scale = _override_numeric(params, "hsl_luminance_scale", 1.0)
    split_tone_scale = _override_numeric(params, "split_tone_scale", 1.0)

    # B&W colored-filter override (2026-08-04) -- filter_color/filter_intensity
    # are NOT _GradeParams fields, same "transient, params-only" treatment as
    # the *_scale trio just above (not color_chrome_effect/dynamic_range's
    # baked-field treatment): a physical filter is screwed on for one shot,
    # not part of a film stock's own calibration, and resolving it here --
    # the sole choke point BEFORE film_look's `grade.monochrome_weights is
    # not None` dispatch check -- is required for the override to actually
    # flip a color look onto the monochrome pipeline. `_resolve_filter_weights`
    # returns None at filter_color==0 ("Aucun filtre", the default and the
    # only value ever implicitly in effect for a look that never mentions it)
    # -- a true no-op, leaving `base.monochrome_weights` (None for a color
    # look, or that look's own baked value for a monochrome one) untouched.
    # When non-None, this DELIBERATELY overwrites monochrome_weights even on
    # a color look (base.monochrome_weights is None): a physical B&W filter
    # has no meaning on color film, so forcing monochrome_weights here --
    # and thereby flipping film_look's dispatch onto _apply_monochrome_grade
    # -- matches a photographer never using a Wratten filter to shoot color,
    # rather than silently discarding the override as color_chrome_effect
    # does on a monochrome look. A deliberate choice, not a technical guard;
    # every consumer of this API (the Zoom overlay) already hides
    # filter_color/filter_intensity outside the "B&W" row (see
    # web/src/components/ZoomOverlay.tsx's BW_SLIDER_GROUPS).
    filter_color = _override_numeric(params, "filter_color", 0.0)
    filter_intensity = _override_numeric(params, "filter_intensity", 1.0)
    filter_weights = _resolve_filter_weights(filter_color, filter_intensity)

    if (
        not absolute_overrides
        and hsl_saturation_scale == 1.0
        and hsl_luminance_scale == 1.0
        and split_tone_scale == 1.0
        and filter_weights is None
    ):
        return base

    return base._replace(
        **absolute_overrides,
        monochrome_weights=filter_weights if filter_weights is not None else base.monochrome_weights,
        hsl_saturation={
            name: _clip(value * hsl_saturation_scale, -50.0, 50.0) for name, value in base.hsl_saturation.items()
        },
        hsl_luminance={
            name: _clip(value * hsl_luminance_scale, -30.0, 30.0) for name, value in base.hsl_luminance.items()
        },
        split_tone_shadow_strength=_clip(base.split_tone_shadow_strength * split_tone_scale, 0.0, 20.0),
        split_tone_highlight_strength=_clip(base.split_tone_highlight_strength * split_tone_scale, 0.0, 20.0),
    )


def resolve_zoom_values(params: dict[str, Any]) -> dict[str, float]:
    """Given a step's current parameter values (e.g. {"look": "velvia_pro",
    "intensity": 1.0}, optionally plus already-confirmed overrides), returns
    the EFFECTIVE value of every zoom parameter this addon declares -- an
    override present in `params` wins, otherwise the value is the selected
    look's own calibrated grade. Used by the Zoom overlay (via
    AddonDescriptor.resolve_zoom_values) to seed sliders with what's actually
    in effect, instead of a generic declared default. An unrecognized/absent
    `look` (e.g. "neutral") has no calibrated grade to seed from, so only
    `intensity` is returned -- callers fall back to each parameter's own
    generic declared default for the rest.
    """
    intensity = params.get("intensity", 1.0)
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        intensity = 1.0
    values: dict[str, float] = {"intensity": float(intensity)}

    grade = _GRADES.get(params.get("look"))
    if grade is None:
        return values

    # Routed through the same _apply_grade_overrides + _resolve_dynamic_range
    # pair `film_look` itself uses (rather than a parallel per-field lookup)
    # so a slider seeds with what will actually render -- critical for
    # highlights/shadows/black_clip, whose effective value is the look's own
    # field PLUS whatever `_resolve_dynamic_range` adds on top for a look with
    # `dynamic_range != 0` (e.g. Summer Story/Inky Depths, both DR200).
    resolved = _resolve_dynamic_range(_apply_grade_overrides(grade, params))
    for field_name in _ABSOLUTE_FIELD_BOUNDS:
        values[field_name] = float(getattr(resolved, field_name))
    values["hsl_saturation_scale"] = float(params.get("hsl_saturation_scale", 1.0))
    values["hsl_luminance_scale"] = float(params.get("hsl_luminance_scale", 1.0))
    values["split_tone_scale"] = float(params.get("split_tone_scale", 1.0))
    values["filter_color"] = float(params.get("filter_color", 0.0))
    values["filter_intensity"] = float(params.get("filter_intensity", 1.0))
    return values


def film_look(image: numpy.ndarray, params: dict[str, Any]) -> numpy.ndarray:
    """Film-look addon transform. An unrecognized
    ``look`` (a real but unknown name, e.g. "sepia") or malformed/out-of-range
    ``intensity`` fall back to identity -- a full fallback, not a per-key
    clamp (FR-014). A MISSING ``look`` (Neutral -- no preset_parameters at
    all) is different: it still has no calibration to render, but Zoom-only
    manual overrides (bug fix, 2026-07-23) apply on top of an otherwise
    untouched image via `_NEUTRAL_GRADE`, instead of being silently discarded
    -- ordinary Neutral rendering (no overrides present) stays the same
    zero-cost passthrough it always was. Never raises; does not mutate
    ``image``.
    """
    look = params.get("look")
    if look is None:
        if not any(key in params for key in _ZOOM_OVERRIDE_KEYS):
            return image
        grade_base = _NEUTRAL_GRADE
        intensity = params.get("intensity", 1.0)
    elif look in _GRADES:
        grade_base = _GRADES[look]
        intensity = params.get("intensity")
    else:
        return image

    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        return image
    t = float(intensity)
    if t < 0.0 or t > 1.0:
        return image
    if t == 0.0:
        return image

    source = image.astype(numpy.float32)
    grade = _apply_grade_overrides(grade_base, params)
    if grade.monochrome_weights is not None:
        look_output = _apply_monochrome_grade(source, grade)
    else:
        look_output = _apply_parametric_grade(source, grade)
    if t == 1.0:
        return numpy.clip(look_output, 0, 255).round().astype(numpy.uint8)

    base = source
    if grade.monochrome_weights is not None:
        # Same reasoning as "acros" above, generalized (2026-08-05) from a
        # hard-coded `look == "acros_pro"` check to any look whose grade
        # declares monochrome_weights -- Acros Pro was the only such look
        # when that check was written, but Kodak T-MAX/T-MAX 3200/Tri-X are
        # monochrome_weights looks too and need the same equal-channel base
        # for a correct fractional-intensity blend. Bit-identical for
        # Acros Pro (the prior condition's sole consumer): overrides never
        # touch monochrome_weights, so `look == "acros_pro"` and
        # `grade.monochrome_weights is not None` were already equivalent
        # whenever `look == "acros_pro"` -- this just widens the condition to
        # the other monochrome looks, using grade.monochrome_weights (not a
        # static per-look constant) as the more honest source of truth.
        weight_r, weight_g, weight_b = grade.monochrome_weights
        custom_luma = source[..., 0] * weight_r + source[..., 1] * weight_g + source[..., 2] * weight_b
        base = numpy.repeat(custom_luma[..., numpy.newaxis], 3, axis=-1)
    blended = base * (1.0 - t) + look_output * t
    return numpy.clip(blended, 0, 255).round().astype(numpy.uint8)


ADDON_DESCRIPTION = AddonSubmission(
    identifier="film_look",
    label="Film",
    category="film",
    thumbnail_presets=(
        ThumbnailPreset(identifier="neutral", label="Neutre", neutral=True),
        ThumbnailPreset(
            identifier="Classic Chrome",
            label="Classic Chrome",
            preset_parameters={"look": "classic_chrome_pro", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Velvia",
            label="Velvia",
            preset_parameters={"look": "velvia_pro", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Acros",
            label="Acros",
            preset_parameters={"look": "acros_pro", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Astia",
            label="Astia",
            preset_parameters={"look": "astia", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Pro Neg. Std",
            label="Pro Neg. Std",
            preset_parameters={"look": "pro_neg_std", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Eterna",
            label="Eterna",
            preset_parameters={"look": "eterna", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Eterna Bleach Bypass",
            label="Eterna Bleach Bypass",
            preset_parameters={"look": "eterna_bleach_bypass", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Classic Negative",
            label="Classic Negative",
            preset_parameters={"look": "classic_negative", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Inky Depths",
            label="Inky Depths",
            preset_parameters={"look": "inky_depths", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Ecowarrior",
            label="Ecowarrior",
            preset_parameters={"look": "ecowarrior", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Loki",
            label="Loki",
            preset_parameters={"look": "loki", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Sunset Strip",
            label="Sunset Strip",
            preset_parameters={"look": "sunset_strip", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Rizzle Clicks",
            label="Rizzle Clicks",
            preset_parameters={"look": "rizzle_clicks", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Glacier Blue",
            label="Glacier Blue",
            preset_parameters={"look": "glacier_blue", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Titanium",
            label="Titanium",
            preset_parameters={"look": "titanium", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Milestone",
            label="Milestone",
            preset_parameters={"look": "milestone", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Quicklime",
            label="Quicklime",
            preset_parameters={"look": "quicklime", "intensity": 1.0},
        ),
        # Four new "B&W" row presets (2026-08-04) exercising the new
        # filter_color/filter_intensity override mechanism (see
        # _apply_grade_overrides's own note) instead of a dedicated
        # _GradeParams constant each -- avoids duplicating
        # _FILTER_WEIGHTS_TABLE, and keeps film_look's `if look ==
        # "acros_pro":` intensity-blend special case (equal-channel base from
        # grade.monochrome_weights) correctly applying to these too, since
        # `look` stays "acros_pro". Default intensity for the filter itself
        # is Modéré (1.0), per explicit user decision. identifier == label
        # here, and in every non-neutral preset below: the frontend renders
        # `RowSpec.vignette_labels` -- i.e. the raw identifiers coming from
        # config_workflow.json -- and never a ThumbnailPreset.label, so a
        # technical identifier distinct from the user-facing wording would
        # simply never be displayed.
        ThumbnailPreset(
            identifier="Acros + Yellow",
            label="Acros + Yellow",
            preset_parameters={"look": "acros_pro", "intensity": 1.0, "filter_color": 1.0, "filter_intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Acros + Red",
            label="Acros + Red",
            preset_parameters={"look": "acros_pro", "intensity": 1.0, "filter_color": 2.0, "filter_intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Acros + Green",
            label="Acros + Green",
            preset_parameters={"look": "acros_pro", "intensity": 1.0, "filter_color": 3.0, "filter_intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Acros + Blue",
            label="Acros + Blue",
            preset_parameters={"look": "acros_pro", "intensity": 1.0, "filter_color": 4.0, "filter_intensity": 1.0},
        ),
        # Three more "B&W" row presets (2026-08-05) -- Kodak-recipe-style
        # looks, see the module docstring. identifier == label, per the
        # convention noted above.
        ThumbnailPreset(
            identifier="Kodak T-MAX 3200",
            label="Kodak T-MAX 3200",
            preset_parameters={"look": "kodak_tmax_3200", "intensity": 1.0},
        ),
        ThumbnailPreset(
            identifier="Kodak Tri-X",
            label="Kodak Tri-X",
            preset_parameters={"look": "kodak_trix", "intensity": 1.0},
        ),
        # Five more "B&W" row presets (2026-08-05, later still), see the
        # module docstring. identifier == label, per the convention noted
        # above.
        ThumbnailPreset(
            identifier="Ilford FP4",
            label="Ilford FP4",
            preset_parameters={"look": "ilford_fp4", "intensity": 1.0},
        ),
    ),
    processing_function=film_look,
    parameter_descriptions=(
        ParameterDescription(
            identifier="intensity", label="Intensity", kind="numeric_slider", default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=1.0, step=0.01),
        ),
        # The 13 "Réglages manuels" sliders below (Zoom overlay screen,
        # 2026-07-22) -- every identifier here is read by
        # _apply_grade_overrides above, applied on top of whichever look is
        # currently selected. The 10 scalar ones are ABSOLUTE values matching
        # a real _GradeParams field 1:1, at that field's own natural range;
        # `default` here is only the generic fallback used when no look is
        # selected at all (e.g. "neutral") -- the Zoom overlay normally seeds
        # each slider from resolve_zoom_values's per-look calibrated value
        # instead (lumaflow/api/app.py's _zoom_state_out), not from this
        # static declaration. hsl_saturation_scale/hsl_luminance_scale/
        # split_tone_scale stay SCALE-based (default 1.0 = "as calibrated"),
        # see _apply_grade_overrides's own comment for why.
        ParameterDescription(
            identifier="contrast", label="Contraste", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="highlights", label="Hautes lumières", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="shadows", label="Ombres", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="black_clip", label="Noir minimal (écrêtage)", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=0.10, step=0.005),
        ),
        ParameterDescription(
            identifier="global_saturation", label="Saturation globale", kind="numeric_slider",
            default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.01),
        ),
        ParameterDescription(
            identifier="hsl_saturation_scale", label="Saturation HSL", kind="numeric_slider", default=1.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.05),
        ),
        ParameterDescription(
            identifier="hsl_luminance_scale", label="Luminance HSL", kind="numeric_slider", default=1.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.05),
        ),
        ParameterDescription(
            identifier="temperature", label="Température", kind="numeric_slider", default=0.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=-1000.0, maximum=1000.0, step=10.0),
        ),
        ParameterDescription(
            identifier="tint", label="Teinte", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-20.0, maximum=20.0, step=0.5),
        ),
        ParameterDescription(
            identifier="split_tone_scale", label="Virage coloré", kind="numeric_slider", default=1.0,
            zoom_only=True, constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=0.05),
        ),
        ParameterDescription(
            identifier="clarity", label="Clarté", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="sharpness", label="Netteté", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-100.0, maximum=100.0, step=1.0),
        ),
        ParameterDescription(
            identifier="grain_std", label="Grain", kind="numeric_slider", default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=0.05, step=0.001),
        ),
        # Three new sliders (2026-07-25, Summer Story/Inky Depths) -- each a
        # discrete Off/Weak/Strong (or DR100/200/400) 3-level dial, modeled as
        # an ordinary numeric_slider with an integer step rather than a new
        # ParameterDescription `kind`: the web Zoom overlay's generic slider
        # renderer already displays an integer-step slider correctly with no
        # code changes (see web/src/components/ZoomOverlay.tsx's
        # isBinaryToggle()/decimal-formatting logic, which only special-cases
        # the exact 0..1 step-1 shape as a toggle). Each identifier must also
        # be added to that file's SLIDER_GROUPS.Film map, or it silently never
        # renders in the Zoom overlay for the Film row (that map is an
        # allow-list, not a fallback-inclusive one).
        ParameterDescription(
            identifier="color_chrome_effect", label="Col. Chr. Effect", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=1.0),
        ),
        ParameterDescription(
            identifier="color_chrome_blue", label="Col. Chr. Blue", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=1.0),
        ),
        ParameterDescription(
            identifier="dynamic_range", label="Dynamic Range", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=1.0),
        ),
        # Two new sliders (2026-07-26, "Monochrome" workflow row) -- Fuji's
        # "Mono Colour" WC/MG dial pair, a color-toning adjustment specific to
        # monochrome_weights looks (see _apply_monochrome_grade's 2026-07-26
        # note). Silently inert (0.0 default, see _mono_color_to_temperature_
        # tint) for every color look, same convention as color_chrome_effect/
        # blue being inert on monochrome looks today.
        ParameterDescription(
            identifier="mono_color_wc", label="Mono Colour WC", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-20.0, maximum=20.0, step=1.0),
        ),
        ParameterDescription(
            identifier="mono_color_mg", label="Mono Colour MG", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=-20.0, maximum=20.0, step=1.0),
        ),
        # Two new sliders (2026-08-04, "B&W" workflow row filter selector) --
        # a single categorical filter + a 3-step intensity, mutually
        # exclusive (one physical filter screwed on at a time), read directly
        # from `params` by _apply_grade_overrides (NOT _GradeParams fields --
        # see that function's own note) rather than declared in
        # _ABSOLUTE_FIELD_BOUNDS. Ordinary numeric_slider, same convention as
        # color_chrome_effect/dynamic_range above (no new ParameterDescription
        # `kind`) -- must also be added to web/src/components/ZoomOverlay.tsx's
        # SLIDER_GROUPS, in a dedicated BW_SLIDER_GROUPS map (not
        # FILM_SLIDER_GROUPS), so they surface only on the "B&W" row's Zoom
        # overlay, not Film/Bleach Bypass's (inert there -- monochrome_weights
        # starts at None on every color look, see _apply_grade_overrides).
        ParameterDescription(
            identifier="filter_color", label="Filtre", kind="numeric_slider",
            default=0.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=4.0, step=1.0),
        ),
        ParameterDescription(
            identifier="filter_intensity", label="Intensité du filtre", kind="numeric_slider",
            default=1.0, zoom_only=True,
            constraints=NumericSliderConstraints(minimum=0.0, maximum=2.0, step=1.0),
        ),
    ),
    overlay_descriptions=(),
    resolve_zoom_values=resolve_zoom_values,
)
