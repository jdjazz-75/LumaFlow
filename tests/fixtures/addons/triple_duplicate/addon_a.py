# LumaFlow v1.0 (2026-08-07)
# Addon factice utilisé avec addon_b.py et addon_c.py pour vérifier la détection par le loader d'un
# identifiant dupliqué entre trois addons distincts (pas seulement deux).

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission

ADDON_DESCRIPTION = AddonSubmission(
    identifier="triple_id",
    label="Triple A",
    category="light",
    thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
    processing_function=lambda image, params: image,
)
