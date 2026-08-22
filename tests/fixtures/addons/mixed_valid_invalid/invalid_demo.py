# LumaFlow v1.0 (2026-08-07)
# Addon factice syntaxiquement valide mais incomplet (champs obligatoires manquants), utilisé pour
# vérifier que le loader rejette un addon invalide tout en continuant de charger les addons valides
# du même répertoire (voir valid_demo.py).

from lumaflow.addons.loader import AddonSubmission

ADDON_DESCRIPTION = AddonSubmission(identifier="invalid_demo")
