# LumaFlow v1.0 (2026-08-07)
# Addon factice complet et valide, utilisé aux côtés de invalid_demo.py pour vérifier que le loader
# charge correctement un addon valide même quand un addon voisin est invalide.

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission

ADDON_DESCRIPTION = AddonSubmission(
    identifier="valid_demo",
    label="Valid Demo",
    category="light",
    thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
    processing_function=lambda image, params: image,
)
