# LumaFlow v1.0 (2026-08-07)
# Addon factice utilisé avec shared_id_b.py pour vérifier la détection par le loader d'un doublon
# d'identifiant entre deux addons distincts.

from lumaflow.addons.contract import ThumbnailPreset
from lumaflow.addons.loader import AddonSubmission

ADDON_DESCRIPTION = AddonSubmission(
    identifier="shared_id",
    label="Shared A",
    category="light",
    thumbnail_presets=(ThumbnailPreset(identifier="neutral", label="Neutral", neutral=True),),
    processing_function=lambda image, params: image,
)
