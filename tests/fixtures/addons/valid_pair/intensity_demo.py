# LumaFlow v1.0 (2026-08-07)
# Addon factice avec un paramètre numérique à curseur (intensity), utilisé aux côtés de
# grid_overlay_demo.py pour vérifier le chargement d'une paire d'addons valides aux capacités différentes.

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission
from lumaflow.addons.parameters import NumericSliderConstraints, ParameterDescription

ADDON_DESCRIPTION = AddonSubmission(
    identifier="intensity_demo",
    label="Intensity Demo",
    category="light",
    thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
    processing_function=lambda image, params: image,
    parameter_descriptions=(
        ParameterDescription(
            identifier="amount",
            label="Amount",
            kind="numeric_slider",
            default=50,
            constraints=NumericSliderConstraints(minimum=0, maximum=100, step=1),
        ),
    ),
)
