# LumaFlow v1.0 (2026-08-07)
# Extraction des metadonnees EXIF RAW (appareil, objectif, date) et correction
# d'orientation (rotation) a partir du flip code LibRaw.
"""RAW EXIF metadata extraction and orientation correction.

Both concerns are "RAW metadata" in the spec's sense, even though
orientation ends up as a pixel transformation rather than a stored field —
kept together here rather than splitting into a fourth small RAW module.

Neither `extract_raw_metadata()` nor `orientation_flip_code()` ever raises:
missing or unreadable metadata degrades silently to `None` fields / no
rotation, never a blocked open: unreadable metadata must never prevent a
photo from being opened.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

import numpy
import rawpy
from PIL import ExifTags, Image

_LENS_MODEL_TAG = 42036
_DATE_TIME_ORIGINAL_TAG = 36867
_DATE_TIME_TAG = 306

_VALID_FLIP_CODES = {0, 3, 5, 6}


@dataclass(frozen=True)
class RawExifMetadata:
    camera_model: Optional[str]
    lens_model: Optional[str]
    capture_date: Optional[str]


def _combine_make_model(make: Optional[str], model: Optional[str]) -> Optional[str]:
    make = (make or "").strip()
    model = (model or "").strip()
    if make and model:
        return model if model.startswith(make) else f"{make} {model}"
    return model or make or None


def extract_raw_metadata(path: pathlib.Path) -> RawExifMetadata:
    try:
        with Image.open(path) as pil_image:
            exif = pil_image.getexif()
            make = exif.get(271)
            model = exif.get(272)
            date_time = exif.get(_DATE_TIME_TAG)

            lens_model = None
            capture_date = date_time
            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except Exception:
                exif_ifd = {}
            if exif_ifd:
                lens_model = exif_ifd.get(_LENS_MODEL_TAG) or None
                capture_date = exif_ifd.get(_DATE_TIME_ORIGINAL_TAG) or date_time

            camera_model = _combine_make_model(make, model)
            return RawExifMetadata(
                camera_model=camera_model,
                lens_model=lens_model or None,
                capture_date=capture_date or None,
            )
    except Exception:
        return RawExifMetadata(camera_model=None, lens_model=None, capture_date=None)


def orientation_flip_code(path: pathlib.Path) -> int:
    try:
        with rawpy.imread(str(path)) as raw:
            flip = raw.sizes.flip
    except Exception:
        return 0
    return flip if flip in _VALID_FLIP_CODES else 0


def apply_orientation(pixels: numpy.ndarray, flip_code: int) -> numpy.ndarray:
    """Pure function — never mutates `pixels` in place."""
    if flip_code == 3:
        return numpy.rot90(pixels, k=2)
    if flip_code == 5:
        return numpy.rot90(pixels, k=1)
    if flip_code == 6:
        return numpy.rot90(pixels, k=-1)
    return pixels
