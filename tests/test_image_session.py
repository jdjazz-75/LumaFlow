# LumaFlow v1.0 (2026-08-07)
# Teste ImageSession/ImageSource : invariant d'intégrité de l'image d'origine (non mutable, isolée
# des remplacements et de l'entrée appelante), accesseurs active/pixels, et stabilité de
# l'identifiant de session (après remplacement, après suppression du fichier source).

from __future__ import annotations

import pathlib
import tempfile
import uuid

import numpy
import pytest
from PIL import Image

from lumaflow.engine.image_io import load_image
from lumaflow.engine.image_session import ImageSession, ImageSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pixels(h: int = 8, w: int = 8) -> numpy.ndarray:
    return numpy.zeros((h, w, 3), dtype=numpy.uint8)


def _make_session() -> ImageSession:
    pixels = _make_pixels()
    source = ImageSource(
        identifier=uuid.uuid4().hex,
        path=None,
        name="test.png",
        width=8,
        height=8,
        image_format="PNG",
    )
    return ImageSession.create(pixels, source)


def _write_png(path: pathlib.Path, h: int = 8, w: int = 4) -> None:
    arr = numpy.zeros((h, w, 3), dtype=numpy.uint8)
    arr[0, 0] = [255, 128, 0]
    Image.fromarray(arr, "RGB").save(path, format="PNG")


def _write_jpeg(path: pathlib.Path, h: int = 8, w: int = 4) -> None:
    arr = numpy.full((h, w, 3), 128, dtype=numpy.uint8)
    Image.fromarray(arr, "RGB").save(path, format="JPEG", quality=100, subsampling=0)


# ---------------------------------------------------------------------------
# US1 — Source Integrity Invariant
# ---------------------------------------------------------------------------

def test_original_unchanged_after_n_replacements():
    session = _make_session()
    snapshot = session.original.copy()
    for i in range(5):
        new_pixels = numpy.full((8, 8, 3), i * 10, dtype=numpy.uint8)
        session.replace_active(new_pixels)
        assert numpy.array_equal(session.original, snapshot), (
            f"session.original was mutated after replacement {i + 1}"
        )


def test_original_write_raises():
    session = _make_session()
    with pytest.raises(ValueError):
        session.original[0, 0, 0] = 42


def test_original_isolated_from_caller_input():
    arr = numpy.full((8, 8, 3), 99, dtype=numpy.uint8)
    source = ImageSource(
        identifier=uuid.uuid4().hex,
        path=None,
        name="",
        width=8,
        height=8,
        image_format="PNG",
    )
    session = ImageSession.create(arr, source)
    arr[0, 0, 0] = 0
    assert session.original[0, 0, 0] == 99, (
        "session.original was affected by mutation of the array passed to create()"
    )


# ---------------------------------------------------------------------------
# US2 — Active / pixels accessors + replace_active
# ---------------------------------------------------------------------------

def test_active_equals_original_before_replacement():
    session = _make_session()
    assert numpy.array_equal(session.active, session.original)


def test_replace_active_state_change():
    session = _make_session()
    new_pixels = numpy.full((8, 8, 3), 77, dtype=numpy.uint8)
    session.replace_active(new_pixels)
    assert numpy.array_equal(session.active, new_pixels)


def test_original_unchanged_after_replace_active():
    session = _make_session()
    snapshot = session.original.copy()
    session.replace_active(numpy.full((8, 8, 3), 33, dtype=numpy.uint8))
    assert numpy.array_equal(session.original, snapshot)


def test_pixels_aliases_active():
    session = _make_session()
    assert session.pixels is session.active
    session.replace_active(numpy.full((8, 8, 3), 11, dtype=numpy.uint8))
    assert session.pixels is session.active


def test_replace_active_invalid_dtype_raises():
    session = _make_session()
    with pytest.raises(ValueError):
        session.replace_active(numpy.zeros((8, 8, 3), dtype=numpy.float32))


def test_replace_active_invalid_ndim_raises():
    session = _make_session()
    with pytest.raises(ValueError):
        session.replace_active(numpy.zeros((8, 8), dtype=numpy.uint8))


def test_replace_active_invalid_channels_raises():
    session = _make_session()
    with pytest.raises(ValueError):
        session.replace_active(numpy.zeros((8, 8, 4), dtype=numpy.uint8))


# ---------------------------------------------------------------------------
# US3 — Source metadata + identifier stability
# ---------------------------------------------------------------------------

def test_jpeg_session_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "sample.jpg"
        _write_jpeg(path)
        session = load_image(path)
        assert session.source.image_format == "JPEG"
        assert session.source.width == 4
        assert session.source.height == 8
        assert session.source.identifier, "identifier must be non-empty"
        assert len(session.source.identifier) == 32


def test_png_session_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "sample.png"
        _write_png(path)
        session = load_image(path)
        assert session.source.image_format == "PNG"
        assert session.source.width == 4
        assert session.source.height == 8
        assert session.source.identifier, "identifier must be non-empty"
        assert len(session.source.identifier) == 32


def test_in_memory_session_no_path():
    pixels = _make_pixels()
    source = ImageSource(
        identifier=uuid.uuid4().hex,
        path=None,
        name="",
        width=8,
        height=8,
        image_format="PNG",
    )
    session = ImageSession.create(pixels, source)
    assert session.source.path is None
    assert session.source.identifier


def test_identifier_stable_after_replace_active():
    session = _make_session()
    original_id = session.source.identifier
    session.replace_active(numpy.full((8, 8, 3), 50, dtype=numpy.uint8))
    assert session.source.identifier == original_id


def test_identifier_stable_after_source_file_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "temp.png"
        _write_png(path)
        session = load_image(path)
        saved_id = session.source.identifier
    # TemporaryDirectory is gone; identifier must still be accessible
    assert session.source.identifier == saved_id
