# LumaFlow v1.0 (2026-08-07)
# ImageSource (metadonnees de l'image chargee) et ImageSession (pixels originaux
# immuables + pixels actifs modifiables).
from __future__ import annotations

import pathlib
import uuid
from dataclasses import dataclass
from typing import Optional

import numpy


@dataclass(frozen=True)
class ImageSource:
    identifier: str
    path: Optional[pathlib.Path]
    name: str
    width: int
    height: int
    image_format: str
    source_jpeg_quality: Optional[int] = None
    source_jpeg_subsampling: Optional[int] = None
    raw_white_balance_gains: Optional[tuple[float, float, float]] = None
    raw_white_balance_source: Optional[str] = None
    raw_camera_model: Optional[str] = None
    raw_lens_model: Optional[str] = None
    raw_capture_date: Optional[str] = None


class ImageSession:
    def __init__(
        self,
        source: ImageSource,
        original: numpy.ndarray,
        active: numpy.ndarray,
    ) -> None:
        self.source = source
        self._original = original
        self._active = active

    @classmethod
    def create(cls, pixels: numpy.ndarray, source: ImageSource) -> ImageSession:
        original = pixels.copy()
        original.flags.writeable = False
        return cls(source=source, original=original, active=original)

    @property
    def original(self) -> numpy.ndarray:
        return self._original

    @property
    def active(self) -> numpy.ndarray:
        return self._active

    @property
    def pixels(self) -> numpy.ndarray:
        return self.active

    def replace_active(self, new_pixels: numpy.ndarray) -> None:
        if not isinstance(new_pixels, numpy.ndarray):
            raise ValueError("new_pixels must be a numpy.ndarray.")
        if new_pixels.dtype != numpy.uint8:
            raise ValueError(
                f"new_pixels must have dtype uint8, got {new_pixels.dtype}."
            )
        if new_pixels.ndim != 3:
            raise ValueError(
                f"new_pixels must be a 3-dimensional array (H,W,3), got ndim={new_pixels.ndim}."
            )
        if new_pixels.shape[2] != 3:
            raise ValueError(
                f"new_pixels must have 3 channels (RGB), got shape {new_pixels.shape}."
            )
        self._active = new_pixels
