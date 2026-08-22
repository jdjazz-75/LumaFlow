# LumaFlow v1.0 (2026-08-07)
# Detection des fichiers RAW par extension (CR2/NEF/ARW), sans lecture de contenu.
"""RAW file extension detection — the single place that lists which RAW
formats LumaFlow recognizes (Canon .cr2, Nikon .nef, Sony .arw). Extend
`RAW_EXTENSIONS` here to support an additional camera format; both the
open-image path (`lumaflow/engine/image_io.py`) and the native file dialog
(`lumaflow/api/app.py`) import this module rather than each keeping their
own list.

Detection is extension-only (no header/content sniffing): a RAW file with an
empty or truncated body must still classify as a RAW candidate, which a
content-based check could not guarantee.
"""
from __future__ import annotations

import pathlib

RAW_EXTENSIONS: frozenset[str] = frozenset({".cr2", ".nef", ".arw"})


def is_raw_candidate(path: pathlib.Path) -> bool:
    """Return True iff `path`'s extension (case-insensitive) is a known RAW
    format. Never opens or reads the file's content."""
    return path.suffix.lower() in RAW_EXTENSIONS
