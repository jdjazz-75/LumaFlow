# LumaFlow v1.0 (2026-08-07)
# Addon factice avec une description de surcouche graphique (overlay grille), utilisé aux côtés de
# intensity_demo.py pour vérifier le chargement d'une paire d'addons valides aux capacités différentes.

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import OverlayDescription

ADDON_DESCRIPTION = AddonSubmission(
    identifier="grid_overlay_demo",
    label="Grid Overlay Demo",
    category="geometry",
    thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
    processing_function=lambda image, params: image,
    overlay_descriptions=(
        OverlayDescription(
            kind="grid",
            label="Rule-of-thirds grid",
            default_active=False,
            graphical_parameters={"line_spacing": 3},
        ),
    ),
)
