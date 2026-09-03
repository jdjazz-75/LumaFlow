# LumaFlow v1.0 (2026-08-07)
# Preferences UI persistees (preferences.json) : mise en page, couleurs de guide,
# qualite d'export, chemins de dialogues -- chargement/sauvegarde avec bornes validees.
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_VALID_POSITIONS = {"left", "top"}
# Langue de l'IHM (i18n phase 6, 2026-09-03). Doit rester synchronise avec web/src/i18n/
# index.ts's LOCALES -- ajouter une locale = ajouter son code ici ET un catalogue la-bas.
_VALID_LANGUAGES = {"fr", "en"}
_HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Bounds for the layout preferences below -- generous enough for real use,
# tight enough to prevent a degenerate (near-invisible or all-consuming) row.
ROW_SPACING_PX_MIN = 0
ROW_SPACING_PX_MAX = 40
VIGNETTE_MARGIN_PX_MIN = 0
VIGNETTE_MARGIN_PX_MAX = 40
ATTENUATED_OPACITY_PERCENT_MIN = 10
ATTENUATED_OPACITY_PERCENT_MAX = 100
ROW_HORIZONTAL_MARGIN_PX_MIN = 0
ROW_HORIZONTAL_MARGIN_PX_MAX = 40
ZOOM_MIN_PERCENT_MIN = 1
ZOOM_MIN_PERCENT_MAX = 100
ZOOM_MAX_PERCENT_MIN = 100
ZOOM_MAX_PERCENT_MAX = 2000
EXPORT_JPEG_QUALITY_MIN = 1
EXPORT_JPEG_QUALITY_MAX = 100

DEFAULT_ROW_SPACING_PX = 8
DEFAULT_VIGNETTE_MARGIN_PX = 8
DEFAULT_ATTENUATED_OPACITY_PERCENT = 80
DEFAULT_ROW_HORIZONTAL_MARGIN_PX = 8
DEFAULT_ZOOM_MIN_PERCENT = 20
DEFAULT_ZOOM_MAX_PERCENT = 400
# Mirrors lumaflow/engine/image_io.py's FALLBACK_JPEG_QUALITY -- same value, for visual
# continuity between "no preference saved yet" and "user hasn't touched the default".
DEFAULT_EXPORT_JPEG_QUALITY = 90
# Current hardcoded CSS values (GeometryCanvas.css/CropCanvas.css/SubjectMaskStage.css/
# VignetteShapeStage.css) before these became configurable -- amber boundary/handle stroke,
# near-white dynamic-aid stroke (alpha dropped, the hex picker has no alpha channel).
DEFAULT_GUIDE_LIMIT_COLOR = "#E3A75E"
DEFAULT_GUIDE_OVERLAY_COLOR = "#FFFFFF"
# Préférences > Général (2026-08-07): couleur d'accentuation globale de l'IHM (focus, sélection,
# boutons d'action, sliders, interrupteurs, barre flottante, onglets Préférences...). Distincte de
# guide_limit_color/guide_overlay_color ci-dessus -- champ indépendant, aucun état partagé. Même
# valeur que l'ambre actuellement codé en dur (tokens.css's --amber) pour un rendu inchangé tant
# que l'utilisateur ne personnalise pas.
DEFAULT_ACCENT_COLOR = "#E3A75E"
# Le francais reste la langue de reference du produit (et le repli de tout catalogue
# incomplet, cf. web/src/i18n/index.ts's FALLBACK_LOCALE) -- une preferences.json anterieure
# a l'i18n n'a pas ce champ et retombe donc sur le comportement d'avant, a l'identique.
DEFAULT_UI_LANGUAGE = "fr"


@dataclass
class UIPreferences:
    menu_position: str = "left"
    menu_collapsed: bool = False
    row_spacing_px: int = DEFAULT_ROW_SPACING_PX
    vignette_margin_px: int = DEFAULT_VIGNETTE_MARGIN_PX
    attenuated_opacity_percent: int = DEFAULT_ATTENUATED_OPACITY_PERCENT
    row_horizontal_margin_px: int = DEFAULT_ROW_HORIZONTAL_MARGIN_PX
    zoom_min_percent: int = DEFAULT_ZOOM_MIN_PERCENT
    zoom_max_percent: int = DEFAULT_ZOOM_MAX_PERCENT
    export_jpeg_quality: int = DEFAULT_EXPORT_JPEG_QUALITY
    guide_limit_color: str = DEFAULT_GUIDE_LIMIT_COLOR
    guide_overlay_color: str = DEFAULT_GUIDE_OVERLAY_COLOR
    accent_color: str = DEFAULT_ACCENT_COLOR
    # Préférences > Général (2026-09-03): "fr" | "en". Validée contre _VALID_LANGUAGES au
    # chargement, comme menu_position l'est contre _VALID_POSITIONS -- une valeur inconnue
    # (fichier écrit par une version ultérieure) retombe sur le français plutôt que de casser.
    ui_language: str = DEFAULT_UI_LANGUAGE
    # Header preset combobox (2026-08-05) -- absolute path to the folder scanned by GET /presets.
    # None until the user picks one in Préférences > Général (no default location).
    presets_directory: str | None = None
    # Default `initialdir` for Photo > Ouvrir/Exporter's native dialogs (2026-08-05), same
    # optional-path shape/validation as presets_directory above.
    open_image_directory: str | None = None
    export_image_directory: str | None = None
    # Préférences > Workflow (2026-08-06 follow-up): which file the live workflow config was last
    # loaded from/validated against (the canonical config_workflow.json, or a file opened via
    # "Ouvrir…") -- display-only breadcrumb, persisted here so it survives an app restart, same
    # optional-path shape as presets_directory/open_image_directory above. None means "the
    # canonical default path" (lumaflow/api/session.py falls back to
    # default_workflow_config_path() when this is unset).
    workflow_config_source_path: str | None = None
    version: int = 1


def _int_in_range(value, minimum: int, maximum: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if not (minimum <= value <= maximum):
        return default
    return value


def _optional_dir(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _hex_color(value, default: str) -> str:
    if not isinstance(value, str) or not _HEX_COLOR_PATTERN.match(value):
        return default
    return value.upper()


def load_preferences(path: Path) -> UIPreferences:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return UIPreferences()
        if data.get("version") != 1:
            return UIPreferences()
        position = data.get("menu_position", "left")
        if position not in _VALID_POSITIONS:
            position = "left"
        collapsed = data.get("menu_collapsed", False)
        if not isinstance(collapsed, bool):
            collapsed = False
        # "active_row_ratio_percent" is no longer read from a persisted file
        # (2026-07-13 ergonomics correction) -- a stale value from an older
        # preferences.json is simply ignored, same as any other unknown key.
        row_spacing_px = _int_in_range(
            data.get("row_spacing_px", DEFAULT_ROW_SPACING_PX),
            ROW_SPACING_PX_MIN, ROW_SPACING_PX_MAX, DEFAULT_ROW_SPACING_PX,
        )
        vignette_margin_px = _int_in_range(
            data.get("vignette_margin_px", DEFAULT_VIGNETTE_MARGIN_PX),
            VIGNETTE_MARGIN_PX_MIN, VIGNETTE_MARGIN_PX_MAX, DEFAULT_VIGNETTE_MARGIN_PX,
        )
        attenuated_opacity_percent = _int_in_range(
            data.get("attenuated_opacity_percent", DEFAULT_ATTENUATED_OPACITY_PERCENT),
            ATTENUATED_OPACITY_PERCENT_MIN, ATTENUATED_OPACITY_PERCENT_MAX, DEFAULT_ATTENUATED_OPACITY_PERCENT,
        )
        row_horizontal_margin_px = _int_in_range(
            data.get("row_horizontal_margin_px", DEFAULT_ROW_HORIZONTAL_MARGIN_PX),
            ROW_HORIZONTAL_MARGIN_PX_MIN, ROW_HORIZONTAL_MARGIN_PX_MAX, DEFAULT_ROW_HORIZONTAL_MARGIN_PX,
        )
        zoom_min_percent = _int_in_range(
            data.get("zoom_min_percent", DEFAULT_ZOOM_MIN_PERCENT),
            ZOOM_MIN_PERCENT_MIN, ZOOM_MIN_PERCENT_MAX, DEFAULT_ZOOM_MIN_PERCENT,
        )
        zoom_max_percent = _int_in_range(
            data.get("zoom_max_percent", DEFAULT_ZOOM_MAX_PERCENT),
            ZOOM_MAX_PERCENT_MIN, ZOOM_MAX_PERCENT_MAX, DEFAULT_ZOOM_MAX_PERCENT,
        )
        # zoom_min_percent's own valid range (1-100) and zoom_max_percent's
        # (100-2000) can never overlap into an inverted pair once each has
        # individually passed _int_in_range -- unlike the other fields above,
        # no separate min>max guard is needed here.
        export_jpeg_quality = _int_in_range(
            data.get("export_jpeg_quality", DEFAULT_EXPORT_JPEG_QUALITY),
            EXPORT_JPEG_QUALITY_MIN, EXPORT_JPEG_QUALITY_MAX, DEFAULT_EXPORT_JPEG_QUALITY,
        )
        guide_limit_color = _hex_color(data.get("guide_limit_color"), DEFAULT_GUIDE_LIMIT_COLOR)
        guide_overlay_color = _hex_color(data.get("guide_overlay_color"), DEFAULT_GUIDE_OVERLAY_COLOR)
        accent_color = _hex_color(data.get("accent_color"), DEFAULT_ACCENT_COLOR)
        ui_language = data.get("ui_language", DEFAULT_UI_LANGUAGE)
        if ui_language not in _VALID_LANGUAGES:
            ui_language = DEFAULT_UI_LANGUAGE
        return UIPreferences(
            menu_position=position,
            menu_collapsed=collapsed,
            row_spacing_px=row_spacing_px,
            vignette_margin_px=vignette_margin_px,
            attenuated_opacity_percent=attenuated_opacity_percent,
            row_horizontal_margin_px=row_horizontal_margin_px,
            zoom_min_percent=zoom_min_percent,
            zoom_max_percent=zoom_max_percent,
            export_jpeg_quality=export_jpeg_quality,
            guide_limit_color=guide_limit_color,
            guide_overlay_color=guide_overlay_color,
            accent_color=accent_color,
            ui_language=ui_language,
            presets_directory=_optional_dir(data.get("presets_directory")),
            open_image_directory=_optional_dir(data.get("open_image_directory")),
            export_image_directory=_optional_dir(data.get("export_image_directory")),
            workflow_config_source_path=_optional_dir(data.get("workflow_config_source_path")),
        )
    except Exception:
        return UIPreferences()


def save_preferences(prefs: UIPreferences, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "version": prefs.version,
            "menu_position": prefs.menu_position,
            "menu_collapsed": prefs.menu_collapsed,
            "row_spacing_px": prefs.row_spacing_px,
            "vignette_margin_px": prefs.vignette_margin_px,
            "attenuated_opacity_percent": prefs.attenuated_opacity_percent,
            "row_horizontal_margin_px": prefs.row_horizontal_margin_px,
            "zoom_min_percent": prefs.zoom_min_percent,
            "zoom_max_percent": prefs.zoom_max_percent,
            "export_jpeg_quality": prefs.export_jpeg_quality,
            "guide_limit_color": prefs.guide_limit_color,
            "guide_overlay_color": prefs.guide_overlay_color,
            "accent_color": prefs.accent_color,
            "ui_language": prefs.ui_language,
            "presets_directory": prefs.presets_directory,
            "open_image_directory": prefs.open_image_directory,
            "export_image_directory": prefs.export_image_directory,
            "workflow_config_source_path": prefs.workflow_config_source_path,
        },
        indent=2,
    )
    path.write_text(payload, encoding="utf-8")


def default_preferences_path() -> Path:
    # Qt-free (2026-07-20, part of the FastAPI/React migration research: this
    # was the only Qt import anywhere outside lumaflow/ui/) -- platformdirs
    # resolves the same kind of OS-appropriate config directory
    # QStandardPaths.AppConfigLocation did, without requiring a QApplication
    # instance to exist.
    import platformdirs
    base = platformdirs.user_config_dir("LumaFlow", appauthor=False)
    return Path(base) / "preferences.json"
