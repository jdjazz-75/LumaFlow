# LumaFlow v1.0 (2026-08-07)
# Suite d'intégration RAW consolidée (spec 055) : exerce load_image() de bout en bout sur la
# matrice extension x scénario (décodable, corrompu, format non pris en charge) et vérifie que les
# fichiers source ne sont jamais modifiés.

"""Consolidated RAW-input integration matrix (spec 055).

Distinct from tests/test_image_load.py's unit tests (each targeting one
internal function of 051-054): this module exercises load_image() end-to-end
across the extension x scenario matrix ({decodable, corrupted, unsupported
format}), so a regression in any link of the RAW chain fails visibly here
rather than only inside a scattered unit test.
"""
from __future__ import annotations

import pathlib

import pytest
from PIL import Image

from conftest import CORRUPTED_RAW_FIXTURE, assert_file_unchanged, decodable_raw_fixtures
from lumaflow.engine.errors import ErrorCategory, ImageIOError
from lumaflow.engine.image_io import load_image
from lumaflow.engine.raw_formats import RAW_EXTENSIONS


def _unsupported_format_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """A format Pillow *can* identify but that isn't JPEG/PNG — the genuine
    UNSUPPORTED_FORMAT path. Deliberately not a .txt file: an unidentifiable
    file raises CORRUPTED_FILE instead."""
    path = tmp_path / "photo.bmp"
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(path, format="BMP")
    return path


# ---------------------------------------------------------------------------
# US1 — a consolidated matrix fails visibly and precisely if any link
# (detection/decode/development) breaks.
# ---------------------------------------------------------------------------

@pytest.mark.raw_fixture
@pytest.mark.parametrize("extension,path", sorted(decodable_raw_fixtures().items()))
def test_decodable_raw_matrix(extension, path):
    with assert_file_unchanged(path):
        session = load_image(path)
    assert session.original is not None
    assert session.active is not None
    assert session.source is not None
    assert session.source.image_format.lower() == extension


def test_matrix_exercises_every_available_raw_extension():
    fixtures = decodable_raw_fixtures()
    if len(fixtures) < 2:
        pytest.skip(
            "Fewer than 2 decodable RAW fixtures available — FR-001's "
            "multi-extension coverage isn't exercised in this environment"
        )
    for ext in fixtures:
        assert f".{ext}" in RAW_EXTENSIONS
    assert len(set(fixtures.keys())) == len(fixtures)


def test_corrupted_raw_raises_raw_not_decodable():
    with assert_file_unchanged(CORRUPTED_RAW_FIXTURE):
        with pytest.raises(ImageIOError) as exc_info:
            load_image(CORRUPTED_RAW_FIXTURE)
    assert exc_info.value.category == ErrorCategory.RAW_NOT_DECODABLE


def test_unsupported_format_raises_unsupported_format(tmp_path):
    fixture = _unsupported_format_fixture(tmp_path)
    with assert_file_unchanged(fixture):
        with pytest.raises(ImageIOError) as exc_info:
            load_image(fixture)
    assert exc_info.value.category == ErrorCategory.UNSUPPORTED_FORMAT


# ---------------------------------------------------------------------------
# US2 — RAW error categories are distinct from JPEG/PNG's; the RAW suite
# doesn't interfere with the existing JPEG/PNG suite.
# ---------------------------------------------------------------------------

def test_raw_not_decodable_and_unsupported_format_share_no_common_message_substring(tmp_path):
    with pytest.raises(ImageIOError) as raw_exc:
        load_image(CORRUPTED_RAW_FIXTURE)

    with pytest.raises(ImageIOError) as format_exc:
        load_image(_unsupported_format_fixture(tmp_path))

    assert raw_exc.value.category != format_exc.value.category
    assert "non pris en charge" not in raw_exc.value.detail
    assert "RAW" not in format_exc.value.detail
