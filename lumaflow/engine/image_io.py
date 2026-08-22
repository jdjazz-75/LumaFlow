# LumaFlow v1.0 (2026-08-07)
# Chargement (JPEG/PNG/RAW) et export d'images : detection de format, estimation de
# qualite JPEG source, ecriture atomique via fichier temporaire.
from __future__ import annotations

import errno
import os
import pathlib
import tempfile

import uuid

import numpy
from PIL import Image, JpegImagePlugin, UnidentifiedImageError

from lumaflow.engine.errors import ErrorCategory, ImageIOError
from lumaflow.engine.image_session import ImageSession, ImageSource
from lumaflow.engine.raw_decode import decode_raw
from lumaflow.engine.raw_develop import develop_initial
from lumaflow.engine.raw_formats import is_raw_candidate
from lumaflow.engine.raw_metadata import (
    apply_orientation,
    extract_raw_metadata,
    orientation_flip_code,
)

SUPPORTED_FORMATS: list[str] = ["JPEG", "PNG"]
DEFAULT_JPEG_QUALITY: int = 100
FALLBACK_JPEG_QUALITY: int = 90

_STD_LUMINANCE_QT: list[int] = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
]


def _estimate_jpeg_quality(quantization: dict[int, list[int]] | None) -> int | None:
    if not quantization or 0 not in quantization:
        return None
    table = quantization[0]
    if len(table) != 64:
        return None

    best_quality: int | None = None
    best_error: int | None = None
    for quality in range(1, 101):
        scale = 5000 // quality if quality < 50 else 200 - 2 * quality
        error = 0
        for base, actual in zip(_STD_LUMINANCE_QT, table):
            predicted = max(1, min(255, (base * scale + 50) // 100))
            error += (predicted - actual) ** 2
        if best_error is None or error < best_error:
            best_error = error
            best_quality = quality
    return best_quality


def _detect_jpeg_subsampling(pil_image: Image.Image) -> int | None:
    try:
        value = JpegImagePlugin.get_sampling(pil_image)
    except Exception:
        return None
    return value if isinstance(value, int) and value >= 0 else None


def load_image(path: pathlib.Path) -> ImageSession:
    path = pathlib.Path(path)
    try:
        if is_raw_candidate(path):
            try:
                raw_pixels = decode_raw(path)
            except Exception as e:
                raise ImageIOError(
                    ErrorCategory.RAW_NOT_DECODABLE,
                    "open",
                    detail=f"Fichier RAW ({path.suffix.lower()}) reconnu mais illisible ou corrompu.",
                ) from e
            developed_pixels, development_params = develop_initial(path, raw_pixels)
            flip_code = orientation_flip_code(path)
            oriented_pixels = apply_orientation(developed_pixels, flip_code)
            raw_height, raw_width = oriented_pixels.shape[:2]
            raw_metadata = extract_raw_metadata(path)
            raw_source = ImageSource(
                identifier=uuid.uuid4().hex,
                path=path.resolve(),
                name=path.name,
                width=raw_width,
                height=raw_height,
                image_format=path.suffix.lstrip(".").upper(),
                source_jpeg_quality=None,
                source_jpeg_subsampling=None,
                raw_white_balance_gains=development_params.white_balance_gains,
                raw_white_balance_source=development_params.white_balance_source,
                raw_camera_model=raw_metadata.camera_model,
                raw_lens_model=raw_metadata.lens_model,
                raw_capture_date=raw_metadata.capture_date,
            )
            return ImageSession.create(pixels=oriented_pixels, source=raw_source)
        with Image.open(path) as pil_image:
            detected_format: str = pil_image.format or ""
            if detected_format not in SUPPORTED_FORMATS:
                shown_format = detected_format or "inconnu"
                raise ImageIOError(
                    ErrorCategory.UNSUPPORTED_FORMAT,
                    "open",
                    detail=(
                        f"Format d'image non pris en charge ({shown_format}). "
                        "Utilisez un fichier JPEG ou PNG."
                    ),
                )
            width, height = pil_image.size

            source_jpeg_quality: int | None = None
            source_jpeg_subsampling: int | None = None
            if detected_format == "JPEG":
                source_jpeg_quality = _estimate_jpeg_quality(getattr(pil_image, "quantization", None))
                source_jpeg_subsampling = _detect_jpeg_subsampling(pil_image)

            if pil_image.mode in ("RGBA", "LA") or (pil_image.mode == "P" and "transparency" in pil_image.info):
                background = Image.new("RGB", pil_image.size, (255, 255, 255))
                if pil_image.mode == "P":
                    pil_image = pil_image.convert("RGBA")
                background.paste(pil_image, mask=pil_image.split()[-1])
                rgb_image = background
            else:
                rgb_image = pil_image.convert("RGB")

            pixels: numpy.ndarray = numpy.asarray(rgb_image, dtype=numpy.uint8).copy()

        source = ImageSource(
            identifier=uuid.uuid4().hex,
            path=path.resolve(),
            name=path.name,
            width=width,
            height=height,
            image_format=detected_format,
            source_jpeg_quality=source_jpeg_quality,
            source_jpeg_subsampling=source_jpeg_subsampling,
        )
        return ImageSession.create(pixels=pixels, source=source)
    except ImageIOError:
        raise
    except FileNotFoundError as e:
        raise ImageIOError(ErrorCategory.MISSING_FILE, "open", detail=str(e)) from e
    except PermissionError as e:
        raise ImageIOError(ErrorCategory.PERMISSION_DENIED, "open", detail=str(e)) from e
    except UnidentifiedImageError as e:
        raise ImageIOError(ErrorCategory.CORRUPTED_FILE, "open", detail=str(e)) from e
    except Exception as e:
        raise ImageIOError(ErrorCategory.UNKNOWN, "open", detail=str(e)) from e


def resolve_jpeg_export_params(
    requested_quality: int | None,
    source: ImageSource | None,
) -> tuple[int | None, int | None]:
    if requested_quality is not None:
        return requested_quality, (source.source_jpeg_subsampling if source else None)
    if source is not None:
        return source.source_jpeg_quality, source.source_jpeg_subsampling
    return None, None


def export_image(
    pixels: numpy.ndarray,
    dest_path: pathlib.Path,
    image_format: str,
    *,
    jpeg_quality: int | None = None,
    jpeg_subsampling: int | None = None,
) -> None:
    dest_path = pathlib.Path(dest_path)
    try:
        pil_image = Image.fromarray(pixels, mode="RGB")
        fd, tmp_str = tempfile.mkstemp(dir=dest_path.parent)
        tmp_path = pathlib.Path(tmp_str)
        try:
            os.close(fd)
            if image_format.upper() == "JPEG":
                quality = jpeg_quality if jpeg_quality is not None else FALLBACK_JPEG_QUALITY
                save_kwargs: dict = {"format": "JPEG", "quality": quality}
                if jpeg_subsampling is not None:
                    save_kwargs["subsampling"] = jpeg_subsampling
                pil_image.save(tmp_path, **save_kwargs)
            else:
                pil_image.save(tmp_path, format=image_format.upper())
            os.replace(tmp_path, dest_path)
        except Exception:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
    except ImageIOError:
        raise
    except PermissionError as e:
        raise ImageIOError(ErrorCategory.PERMISSION_DENIED, "export", detail=str(e)) from e
    except FileNotFoundError as e:
        raise ImageIOError(ErrorCategory.INVALID_PATH, "export", detail=str(e)) from e
    except OSError as e:
        if e.errno == errno.ENOSPC:
            raise ImageIOError(ErrorCategory.DISK_FULL, "export", detail=str(e)) from e
        raise ImageIOError(ErrorCategory.UNKNOWN, "export", detail=str(e)) from e
    except Exception as e:
        raise ImageIOError(ErrorCategory.UNKNOWN, "export", detail=str(e)) from e
