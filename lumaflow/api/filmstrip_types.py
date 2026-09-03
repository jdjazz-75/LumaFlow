# LumaFlow v1.0 (2026-08-07)
# Types partages de la filmstrip (RowSpec, VignetteState, fenetre de 3 lignes visibles)
# consommes par app.py et session.py.
"""Filmstrip row/vignette types shared by the web API (`app.py`, `session.py`).

Relocated verbatim from `lumaflow/ui/filmstrip_view.py` (2026-07-29, Qt UI removal) -- these
identifiers were always pure Python (numpy/enum/dataclasses only) but lived in a module whose
top-level PySide6 imports pulled in Qt as a side effect of importing them. No logic changed.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

import numpy

NEUTRAL_PRESET_IDENTIFIER = "neutral"


def visible_row_indices(active_index: int, total: int) -> list[int]:
    """The always-3-wide row window (ergonomics correction, 2026-07-13):
    centered on ``active_index`` in the general case, but pinned to the same
    side at either boundary -- active=first yields [active, next, next-next];
    active=last yields [prev-prev, prev, active] -- so the row count never
    drops below three just because the active step sits at an edge. Below 3
    total steps there simply aren't enough rows to fill the window; every
    real index is returned instead.

    The SINGLE source of truth for this window: this function is called both
    by the (now-removed) Qt filmstrip and by the web API's own vignette-state
    computation, so the two could never drift out of sync (they did once,
    shipping a real bug: the newly-visible boundary row rendered as an empty
    placeholder because a separate copy of this window's math existed).
    """
    if total <= 3:
        window_start = 0
    elif active_index == 0:
        window_start = 0
    elif active_index == total - 1:
        window_start = total - 3
    else:
        window_start = active_index - 1
    return list(range(window_start, min(window_start + 3, total)))


def _ensure_neutral_first(labels: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize labels so NEUTRAL_PRESET_IDENTIFIER is first, exactly once.

    Relative order of every other entry is preserved.
    """
    rest = tuple(label for label in labels if label != NEUTRAL_PRESET_IDENTIFIER)
    return (NEUTRAL_PRESET_IDENTIFIER, *rest)


def vignette_display_text(identifier: str) -> str:
    """Single source of truth for a vignette's caption text (feature 034
    Decision 5) -- VignetteCard's own caption and the Zoom shell's indicator
    label both call this instead of each keeping their own copy of the rule.
    """
    return "Neutral" if identifier == NEUTRAL_PRESET_IDENTIFIER else identifier


class VignetteStatus(enum.Enum):
    PENDING = "pending"
    READY = "ready"
    ERROR = "error"


@dataclass(frozen=True)
class VignetteState:
    """One vignette's current renderable state (F-027).

    pixels is set iff status == READY; detail is set iff status == ERROR.
    Carries only numpy/str/enum values -- no other lumaflow domain type,
    preserving this module's import-purity invariant.
    """

    status: VignetteStatus = VignetteStatus.PENDING
    pixels: numpy.ndarray | None = None
    detail: str = ""


@dataclass(frozen=True)
class RowSpec:
    """The neutral hand-off type crossing the config->UI boundary: a row's
    display label plus its ordered vignette (preset) identifiers.

    __post_init__ unconditionally guarantees NEUTRAL_PRESET_IDENTIFIER is
    present at index 0 -- no caller can construct one without it (F-026).
    ``short_description`` is a short, workflow-configured caption shown below
    the main label (F-030) -- distinct from the row's ordinal "Step N"
    position, which StepLabelColumn derives on its own from the row's index.
    ``selected_vignette_identifier`` names which of ``vignette_labels`` is
    this step's currently-active preset choice. Defaults to
    ``NEUTRAL_PRESET_IDENTIFIER`` -- this is not a fabricated guess: absent
    any other recorded choice, "neutral" (no transformation) genuinely IS
    the preset every step's pipeline actually runs (F-010's neutral
    ``PipelineStep.apply``), so it is the honest default rather than an
    invented one (Principle V). ``None`` is still accepted for a step with
    no real vignette content at all (e.g. no image loaded yet).
    """

    label: str
    # config_workflow.json's stable row identifier ("film", "bleach_bypass", "color_splash"...).
    # Added 2026-09-03 (i18n, phase 1): the web UI used to key its per-row behaviour off `label`
    # (hidden rows, Zoom slider grouping, cross-row corrections), a convention filmstrip.ts itself
    # called "fragile-but-established" -- and one that breaks outright the moment a label is
    # translated. Defaults to "" so no existing construction site is invalidated.
    identifier: str = ""
    vignette_labels: tuple[str, ...] = ()
    vignette_states: dict[str, VignetteState] = field(default_factory=dict)
    short_description: str = ""
    selected_vignette_identifier: str | None = NEUTRAL_PRESET_IDENTIFIER

    def __post_init__(self) -> None:
        object.__setattr__(self, "vignette_labels", _ensure_neutral_first(self.vignette_labels))
