# LumaFlow v1.0 (2026-08-07)
# Teste export_image et resolve_jpeg_export_params : aller-retour JPEG/PNG, absence de canal alpha,
# valeurs extrêmes de qualité JPEG, non-altération du fichier source, écriture atomique (pas de
# fichier partiel en cas d'échec), et reprise de la qualité/sous-échantillonnage source au ré-export.

"""Tests for export_image engine function — US1 (§1–§5)."""
from __future__ import annotations

import hashlib
import io
import pathlib
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from lumaflow.engine.errors import ImageIOError
from lumaflow.engine.image_session import ImageSource
from lumaflow.engine.image_io import (
    DEFAULT_JPEG_QUALITY,
    export_image,
    load_image,
    resolve_jpeg_export_params,
)


def _rgb_array(h: int = 20, w: int = 30) -> np.ndarray:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :, 0] = 100
    arr[:, :, 1] = 150
    arr[:, :, 2] = 200
    return arr


def _gradient_array(h: int = 64, w: int = 64) -> np.ndarray:
    """Non-flat content — a solid color compresses to ~the same size at any
    quality/subsampling and would not exercise the size-comparison tests."""
    return np.fromfunction(
        lambda y, x, c: (x * 4 + y * 2 + c * 60) % 256,
        (h, w, 3),
        dtype=np.int64,
    ).astype(np.uint8)


def _file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jpeg(path: pathlib.Path, w: int = 10, h: int = 8) -> pathlib.Path:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(80, 120, 160)).save(buf, format="JPEG")
    path.write_bytes(buf.getvalue())
    return path


def _write_gradient_jpeg(path: pathlib.Path, *, quality: int, subsampling: int, w: int = 64, h: int = 64) -> pathlib.Path:
    buf = io.BytesIO()
    Image.fromarray(_gradient_array(h, w), mode="RGB").save(
        buf, format="JPEG", quality=quality, subsampling=subsampling
    )
    path.write_bytes(buf.getvalue())
    return path


# ---------------------------------------------------------------------------
# §1.2 — JPEG roundtrip
# ---------------------------------------------------------------------------

def test_jpeg_export_creates_file(tmp_path):
    pixels = _rgb_array()
    dest = tmp_path / "out.jpg"
    export_image(pixels, dest, "JPEG")
    assert dest.exists()


def test_jpeg_export_roundtrip_shape(tmp_path):
    pixels = _rgb_array(20, 30)
    dest = tmp_path / "out.jpg"
    export_image(pixels, dest, "JPEG")
    reloaded = load_image(dest)
    assert reloaded.pixels.shape == (20, 30, 3)


# ---------------------------------------------------------------------------
# §1.3 — PNG roundtrip
# ---------------------------------------------------------------------------

def test_png_export_creates_file(tmp_path):
    pixels = _rgb_array()
    dest = tmp_path / "out.png"
    export_image(pixels, dest, "PNG")
    assert dest.exists()


def test_png_export_roundtrip_shape(tmp_path):
    pixels = _rgb_array(20, 30)
    dest = tmp_path / "out.png"
    export_image(pixels, dest, "PNG")
    reloaded = load_image(dest)
    assert reloaded.pixels.shape == (20, 30, 3)


def test_png_export_roundtrip_pixel_exact(tmp_path):
    pixels = _rgb_array(20, 30)
    dest = tmp_path / "out.png"
    export_image(pixels, dest, "PNG")
    reloaded = load_image(dest)
    assert np.array_equal(pixels, reloaded.pixels)


# ---------------------------------------------------------------------------
# §1.4 — Flat RGB output (no alpha channel)
# ---------------------------------------------------------------------------

def test_jpeg_export_no_alpha(tmp_path):
    pixels = _rgb_array()
    dest = tmp_path / "out.jpg"
    export_image(pixels, dest, "JPEG")
    reloaded = load_image(dest)
    assert reloaded.pixels.shape[2] == 3


def test_png_export_no_alpha(tmp_path):
    pixels = _rgb_array()
    dest = tmp_path / "out.png"
    export_image(pixels, dest, "PNG")
    reloaded = load_image(dest)
    assert reloaded.pixels.shape[2] == 3


# ---------------------------------------------------------------------------
# §2.1 — DEFAULT_JPEG_QUALITY is 100
# ---------------------------------------------------------------------------

def test_default_jpeg_quality_is_100():
    assert DEFAULT_JPEG_QUALITY == 100


# ---------------------------------------------------------------------------
# §2.2 — jpeg_quality parameter accepts extreme values without error
# ---------------------------------------------------------------------------

def test_jpeg_export_quality_1_completes(tmp_path):
    pixels = _rgb_array()
    dest = tmp_path / "low.jpg"
    export_image(pixels, dest, "JPEG", jpeg_quality=1)
    assert dest.exists()


def test_jpeg_export_quality_100_completes(tmp_path):
    pixels = _rgb_array()
    dest = tmp_path / "high.jpg"
    export_image(pixels, dest, "JPEG", jpeg_quality=100)
    assert dest.exists()


# ---------------------------------------------------------------------------
# §3.1 — Source file checksum unchanged after export
# ---------------------------------------------------------------------------

def test_source_checksum_unchanged_after_jpeg_export(tmp_path):
    source = _write_jpeg(tmp_path / "source.jpg")
    before = _file_sha256(source)
    pixels = _rgb_array()
    export_image(pixels, tmp_path / "exported.jpg", "JPEG")
    assert _file_sha256(source) == before


def test_source_checksum_unchanged_after_png_export(tmp_path):
    source = _write_jpeg(tmp_path / "source.jpg")
    before = _file_sha256(source)
    pixels = _rgb_array()
    export_image(pixels, tmp_path / "exported.png", "PNG")
    assert _file_sha256(source) == before


# ---------------------------------------------------------------------------
# §5.1 — Atomic write: no partial file survives on failure
# ---------------------------------------------------------------------------

def test_no_partial_file_on_os_replace_failure(tmp_path):
    pixels = _rgb_array()
    dest = tmp_path / "out.jpg"
    with patch("os.replace", side_effect=OSError("simulated failure")):
        with pytest.raises(ImageIOError):
            export_image(pixels, dest, "JPEG")
    assert not dest.exists()


# ---------------------------------------------------------------------------
# §6 — Correctif : l'export JPEG par défaut reprend la qualité/subsampling
# de la source, au lieu de forcer qualité=100/subsampling=0 (taille gonflée
# sur un ré-export sans aucune modification)
# ---------------------------------------------------------------------------

def test_unedited_jpeg_reexport_stays_close_to_source_size(tmp_path):
    source_path = _write_gradient_jpeg(tmp_path / "source.jpg", quality=82, subsampling=2)
    source_size = source_path.stat().st_size

    session = load_image(source_path)
    dest = tmp_path / "reexported.jpg"
    quality, subsampling = resolve_jpeg_export_params(None, session.source)
    export_image(session.pixels, dest, "JPEG", jpeg_quality=quality, jpeg_subsampling=subsampling)

    reexported_size = dest.stat().st_size
    assert reexported_size <= source_size * 2

    forced_max_dest = tmp_path / "forced_max.jpg"
    export_image(session.pixels, forced_max_dest, "JPEG", jpeg_quality=100, jpeg_subsampling=0)
    assert reexported_size < forced_max_dest.stat().st_size


def test_explicit_jpeg_quality_override_still_applies(tmp_path):
    pixels = _gradient_array()
    low_dest = tmp_path / "low.jpg"
    high_dest = tmp_path / "high.jpg"
    export_image(pixels, low_dest, "JPEG", jpeg_quality=20)
    export_image(pixels, high_dest, "JPEG", jpeg_quality=95)
    assert low_dest.stat().st_size < high_dest.stat().st_size


def test_png_export_ignores_jpeg_quality_argument(tmp_path):
    pixels = _gradient_array()
    dest_a = tmp_path / "a.png"
    dest_b = tmp_path / "b.png"
    export_image(pixels, dest_a, "PNG", jpeg_quality=1)
    export_image(pixels, dest_b, "PNG", jpeg_quality=100)
    assert dest_a.read_bytes() == dest_b.read_bytes()


def test_resolve_jpeg_export_params_explicit_request_wins():
    source = ImageSource(
        identifier="id", path=None, name="n", width=1, height=1,
        image_format="JPEG", source_jpeg_quality=80, source_jpeg_subsampling=2,
    )
    quality, subsampling = resolve_jpeg_export_params(50, source)
    assert quality == 50
    assert subsampling == 2


def test_resolve_jpeg_export_params_falls_back_to_source():
    source = ImageSource(
        identifier="id", path=None, name="n", width=1, height=1,
        image_format="JPEG", source_jpeg_quality=80, source_jpeg_subsampling=2,
    )
    assert resolve_jpeg_export_params(None, source) == (80, 2)


def test_resolve_jpeg_export_params_no_source_and_no_request():
    assert resolve_jpeg_export_params(None, None) == (None, None)
