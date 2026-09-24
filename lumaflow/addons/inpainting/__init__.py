# LumaFlow v1.1 (2026-09-24)
"""Inpainting engine package (feature 100, addon Suppression d'objets).

Regular importable package (NOT under `lumaflow/addons/builtin/`) so `lumaflow.addons.loader`'s
directory scan never picks it up as an addon module, and so it (unlike every file under
`builtin/`) IS registered in `sys.modules` on import -- a normal Python module.

Only `inpaint_regions` is public; `engine`/`lama_backend` are implementation detail. The fill
algorithm is LaMa (a pretrained network run via `lama_backend.py`) as of the pivot documented in
`specs/100-addon-object-removal-v1/research.md` R3 -- the original pure-numpy PatchMatch engine
(`kernels.py`) has been retired.
"""

from lumaflow.addons.inpainting.engine import inpaint_regions

__all__ = ["inpaint_regions"]
