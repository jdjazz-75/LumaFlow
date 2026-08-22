# LumaFlow v1.0 (2026-08-07)
# Teste load_image et la chaîne de décodage RAW : chargement JPEG/PNG (forme, détection de format
# basée contenu, métadonnées source, transparence PNG), détection qualité/sous-échantillonnage
# JPEG, classification et rejet des candidats RAW (décodable/corrompu), balance des blancs caméra
# avant démosaïçage, orientation EXIF, et persistance des métadonnées de capture.

"""Tests for F-005: load_image invariants — US1, US2, US3."""
from __future__ import annotations

import hashlib
import io
import pathlib

import numpy as np
import pytest
from PIL import Image

from lumaflow.engine.errors import ErrorCategory, ImageIOError
from lumaflow.engine.image_io import SUPPORTED_FORMATS, load_image


# ---------------------------------------------------------------------------
# Fixtures — small in-memory image bytes written to tmp_path
# ---------------------------------------------------------------------------

def _jpeg_bytes(width: int = 10, height: int = 8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(100, 150, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes(width: int = 10, height: int = 8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


def _bmp_bytes(width: int = 10, height: int = 8) -> bytes:
    """A format Pillow *can* identify but that isn't in SUPPORTED_FORMATS —
    exercises the UNSUPPORTED_FORMAT path (as opposed to CORRUPTED_FILE,
    which is what an unidentifiable file like plain text triggers)."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(50, 100, 200)).save(buf, format="BMP")
    return buf.getvalue()


def _rgba_png_bytes(width: int = 10, height: int = 8, alpha: int = 128) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGBA", (width, height), color=(100, 150, 200, alpha))
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gradient_image(width: int = 64, height: int = 64) -> Image.Image:
    """A non-flat image — flat solid colors compress away quality/subsampling
    differences and don't exercise quantization-table-based estimation."""
    arr = np.fromfunction(
        lambda y, x, c: (x * 4 + y * 2 + c * 60) % 256,
        (height, width, 3),
        dtype=np.int64,
    ).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _gradient_jpeg_bytes(*, quality: int, subsampling: int, width: int = 64, height: int = 64) -> bytes:
    buf = io.BytesIO()
    _gradient_image(width, height).save(buf, format="JPEG", quality=quality, subsampling=subsampling)
    return buf.getvalue()


def _file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 052 — RAW decoding fixture discovery. Delegates entirely to 055's shared
# conftest.py mechanism (decodable_raw_fixtures()) — the single source of
# truth for "is a real decodable RAW fixture available"; this wrapper exists
# only so 052/053/054's own call sites (a single Path, not a dict) don't need
# rewriting.
# ---------------------------------------------------------------------------

from conftest import decodable_raw_fixtures

_FIRST_DECODABLE_RAW_FIXTURE = next(iter(decodable_raw_fixtures().values()), None)
_NO_DECODABLE_RAW_FIXTURE = _FIRST_DECODABLE_RAW_FIXTURE is None
_SKIP_NO_RAW_FIXTURE = pytest.mark.skipif(
    _NO_DECODABLE_RAW_FIXTURE,
    reason="No decodable RAW fixture in tests/fixtures/raw/ (see README.md there)",
)


# ---------------------------------------------------------------------------
# US1 — Open a JPEG or PNG image (§1, §2, §5)
# ---------------------------------------------------------------------------

def test_jpeg_loads_correct_shape(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes(10, 8))
    session = load_image(p)
    assert session.pixels.shape == (8, 10, 3)
    assert session.pixels.dtype == np.uint8


def test_png_loads_correct_shape(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_png_bytes(12, 6))
    session = load_image(p)
    assert session.pixels.shape == (6, 12, 3)
    assert session.pixels.dtype == np.uint8


def test_jpg_and_jpeg_extensions_produce_equal_pixels(tmp_path):
    data = _jpeg_bytes(10, 8)
    p_jpg = tmp_path / "img.jpg"
    p_jpeg = tmp_path / "img.jpeg"
    p_jpg.write_bytes(data)
    p_jpeg.write_bytes(data)
    s1 = load_image(p_jpg)
    s2 = load_image(p_jpeg)
    assert np.array_equal(s1.pixels, s2.pixels)


def test_content_based_format_detection_jpeg(tmp_path):
    """JPEG bytes in a .png file → format is JPEG (content wins)."""
    p = tmp_path / "trick.png"
    p.write_bytes(_jpeg_bytes())
    session = load_image(p)
    assert session.source.image_format == "JPEG"


def test_content_based_format_detection_png(tmp_path):
    """PNG bytes in a .jpg file → format is PNG (content wins)."""
    p = tmp_path / "trick.jpg"
    p.write_bytes(_png_bytes())
    session = load_image(p)
    assert session.source.image_format == "PNG"


def test_1x1_jpeg_loads_without_error(tmp_path):
    p = tmp_path / "tiny.jpg"
    p.write_bytes(_jpeg_bytes(1, 1))
    session = load_image(p)
    assert session.pixels.shape == (1, 1, 3)


def test_1x1_png_loads_without_error(tmp_path):
    p = tmp_path / "tiny.png"
    p.write_bytes(_png_bytes(1, 1))
    session = load_image(p)
    assert session.pixels.shape == (1, 1, 3)


def test_pixels_hwc_order_matches_source_dimensions(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes(width=30, height=20))
    session = load_image(p)
    h, w, _ = session.pixels.shape
    assert h == session.source.height
    assert w == session.source.width


def test_pixels_has_no_alpha_channel_jpeg(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes())
    assert load_image(p).pixels.shape[2] == 3


def test_pixels_has_no_alpha_channel_png(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_png_bytes())
    assert load_image(p).pixels.shape[2] == 3


def test_source_file_checksum_unchanged_after_load(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes())
    sha_before = _file_sha256(p)
    load_image(p)
    assert _file_sha256(p) == sha_before


def test_no_extra_files_created_after_load(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_png_bytes())
    load_image(p)
    assert list(tmp_path.iterdir()) == [p]


def test_supported_formats_constant():
    assert SUPPORTED_FORMATS == ["JPEG", "PNG"]


# ---------------------------------------------------------------------------
# US2 — Source metadata preserved after load (§3)
# ---------------------------------------------------------------------------

def test_source_path_is_absolute_and_resolved(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes())
    session = load_image(p)
    assert session.source.path == p.resolve()
    assert session.source.path.is_absolute()


def test_source_name_is_filename_with_extension(tmp_path):
    p = tmp_path / "myimage.jpg"
    p.write_bytes(_jpeg_bytes())
    session = load_image(p)
    assert session.source.name == "myimage.jpg"


def test_source_dimensions_match_pillow_size_jpeg(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes(width=15, height=9))
    session = load_image(p)
    with Image.open(p) as pil:
        expected_w, expected_h = pil.size
    assert session.source.width == expected_w
    assert session.source.height == expected_h


def test_source_dimensions_match_pillow_size_png(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_png_bytes(width=7, height=13))
    session = load_image(p)
    with Image.open(p) as pil:
        expected_w, expected_h = pil.size
    assert session.source.width == expected_w
    assert session.source.height == expected_h


def test_source_image_format_jpeg(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes())
    assert load_image(p).source.image_format == "JPEG"


def test_source_image_format_png(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_png_bytes())
    assert load_image(p).source.image_format == "PNG"


def test_image_source_is_frozen(tmp_path):
    import dataclasses
    p = tmp_path / "img.jpg"
    p.write_bytes(_jpeg_bytes())
    session = load_image(p)
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.source.width = 9999


# ---------------------------------------------------------------------------
# US3 — Accept PNG with transparency (§4)
# ---------------------------------------------------------------------------

def test_rgba_png_loads_without_error(tmp_path):
    p = tmp_path / "rgba.png"
    p.write_bytes(_rgba_png_bytes(alpha=128))
    session = load_image(p)
    assert session.pixels.shape[2] == 3


def test_rgba_png_loads_deterministically(tmp_path):
    p = tmp_path / "rgba.png"
    p.write_bytes(_rgba_png_bytes(alpha=64))
    s1 = load_image(p)
    s2 = load_image(p)
    assert np.array_equal(s1.pixels, s2.pixels)


def test_fully_transparent_png_becomes_all_white(tmp_path):
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), color=(0, 0, 0, 0)).save(buf, format="PNG")
    p = tmp_path / "transparent.png"
    p.write_bytes(buf.getvalue())
    session = load_image(p)
    assert np.all(session.pixels == 255)


def test_alpha_stripped_in_transparency_cases(tmp_path):
    p = tmp_path / "rgba.png"
    p.write_bytes(_rgba_png_bytes(alpha=200))
    assert load_image(p).pixels.shape[2] == 3


# ---------------------------------------------------------------------------
# Source JPEG quality/subsampling detection (correctif taille d'export gonflée)
# ---------------------------------------------------------------------------

def test_source_jpeg_quality_is_estimated(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_gradient_jpeg_bytes(quality=80, subsampling=2))
    session = load_image(p)
    assert session.source.source_jpeg_quality == 80


def test_source_jpeg_subsampling_detected_444(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_gradient_jpeg_bytes(quality=85, subsampling=0))
    session = load_image(p)
    assert session.source.source_jpeg_subsampling == 0


def test_source_jpeg_subsampling_detected_420(tmp_path):
    p = tmp_path / "img.jpg"
    p.write_bytes(_gradient_jpeg_bytes(quality=85, subsampling=2))
    session = load_image(p)
    assert session.source.source_jpeg_subsampling == 2


def test_source_jpeg_quality_and_subsampling_none_for_png(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_png_bytes())
    session = load_image(p)
    assert session.source.source_jpeg_quality is None
    assert session.source.source_jpeg_subsampling is None


# ---------------------------------------------------------------------------
# US1 (051) — a RAW-extension file is classified as a RAW candidate, never
# reaching Pillow, and rejected with a dedicated RAW_NOT_DECODABLE message.
# ---------------------------------------------------------------------------

def test_cr2_file_raises_raw_not_decodable(tmp_path):
    p = tmp_path / "photo.cr2"
    p.write_bytes(b"arbitrary bytes, not a real RAW file")
    with pytest.raises(ImageIOError) as exc_info:
        load_image(p)
    assert exc_info.value.category == ErrorCategory.RAW_NOT_DECODABLE


def test_nef_file_raises_raw_not_decodable(tmp_path):
    p = tmp_path / "photo.nef"
    p.write_bytes(b"arbitrary bytes, not a real RAW file")
    with pytest.raises(ImageIOError) as exc_info:
        load_image(p)
    assert exc_info.value.category == ErrorCategory.RAW_NOT_DECODABLE


@pytest.mark.parametrize("suffix", [".cr2", ".Cr2", ".CR2"])
def test_raw_extension_case_variants_all_classified_as_raw(tmp_path, suffix):
    p = tmp_path / f"photo{suffix}"
    p.write_bytes(b"arbitrary bytes")
    with pytest.raises(ImageIOError) as exc_info:
        load_image(p)
    assert exc_info.value.category == ErrorCategory.RAW_NOT_DECODABLE


def test_empty_raw_file_still_classified_as_raw_candidate(tmp_path):
    p = tmp_path / "empty.cr2"
    p.write_bytes(b"")
    with pytest.raises(ImageIOError) as exc_info:
        load_image(p)
    assert exc_info.value.category == ErrorCategory.RAW_NOT_DECODABLE


def test_load_image_never_opens_raw_file_with_pillow(tmp_path, monkeypatch):
    p = tmp_path / "photo.cr2"
    p.write_bytes(b"arbitrary bytes")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("Image.open must not be called for a RAW candidate")

    monkeypatch.setattr("lumaflow.engine.image_io.Image.open", _fail_if_called)
    with pytest.raises(ImageIOError):
        load_image(p)


def test_decode_raw_applies_camera_white_balance_before_demosaic(monkeypatch):
    """Regression guard for the two successive color-cast bugs (2026-08-04,
    red then green): LibRaw applies white balance *before* demosaic, as an
    input to its own interpolation algorithm — a gain multiplied in
    afterward (053's old approach) cannot reproduce the same colors,
    confirmed empirically against real Canon/Nikon/Sony files (see
    raw_decode.py's amendment 2). decode_raw() must therefore resolve the
    real as-shot gains itself and pass them as `user_wb` to its own single
    `postprocess()` call. This test needs no real RAW fixture: it only
    asserts decode_raw()'s postprocess() call parameters, not its pixel
    output."""
    from lumaflow.engine import raw_decode

    captured_kwargs = {}

    class _FakeRaw:
        camera_whitebalance = [2351.0, 1024.0, 1382.0, 1024.0]

        def postprocess(self, **kwargs):
            captured_kwargs.update(kwargs)
            return np.zeros((2, 2, 3), dtype=np.uint16)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(raw_decode.rawpy, "imread", lambda path: _FakeRaw())

    raw_decode.decode_raw(pathlib.Path("irrelevant.cr2"))

    red, green, blue, _ = _FakeRaw.camera_whitebalance
    expected_user_wb = [red / green, 1.0, blue / green, 1.0]
    assert captured_kwargs["user_wb"] == pytest.approx(expected_user_wb)
    assert captured_kwargs["use_camera_wb"] is False
    assert captured_kwargs["use_auto_wb"] is False


def test_decode_raw_requests_linear_16bit_scene_referred_output(monkeypatch):
    """Pins the three parameters that define decode_raw()'s output as linear,
    scene-referred, 16-bit. Nothing asserted these before, which is precisely
    how the "RAW files open far too dark" bug survived: `gamma=(1, 1)` plus
    `no_auto_bright=True` produce linear light, and until 053 gained a real
    tone stage (2026-08-21) nothing downstream ever applied a transfer
    function — the pixels reached the screen as if they were sRGB-encoded.
    Changing any of these three without changing raw_develop.py's tone chain
    to match will silently mis-expose every RAW again."""
    from lumaflow.engine import raw_decode

    captured_kwargs = {}

    class _FakeRaw:
        camera_whitebalance = [2351.0, 1024.0, 1382.0, 1024.0]

        def postprocess(self, **kwargs):
            captured_kwargs.update(kwargs)
            return np.zeros((2, 2, 3), dtype=np.uint16)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(raw_decode.rawpy, "imread", lambda path: _FakeRaw())

    raw_decode.decode_raw(pathlib.Path("irrelevant.cr2"))

    assert captured_kwargs["gamma"] == (1, 1)
    assert captured_kwargs["no_auto_bright"] is True
    assert captured_kwargs["output_bps"] == 16


def test_decode_raw_falls_back_to_identity_white_balance_without_metadata(monkeypatch):
    """Without valid camera_whitebalance metadata, decode_raw() must still
    pass an explicit identity user_wb — leaving it unset would silently fall
    back to rawpy's non-neutral "daylight" white balance (the original,
    first amendment's bug)."""
    from lumaflow.engine import raw_decode

    captured_kwargs = {}

    class _FakeRaw:
        camera_whitebalance = [0, 0, 0, 0]

        def postprocess(self, **kwargs):
            captured_kwargs.update(kwargs)
            return np.zeros((2, 2, 3), dtype=np.uint16)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(raw_decode.rawpy, "imread", lambda path: _FakeRaw())

    raw_decode.decode_raw(pathlib.Path("irrelevant.cr2"))

    assert captured_kwargs["user_wb"] == [1.0, 1.0, 1.0, 1.0]
    assert captured_kwargs["use_camera_wb"] is False
    assert captured_kwargs["use_auto_wb"] is False


# ---------------------------------------------------------------------------
# US2 (051) — the RAW rejection is distinct from, and does not regress, the
# pre-existing UNSUPPORTED_FORMAT rejection for genuinely unknown formats.
# ---------------------------------------------------------------------------

def test_bmp_file_still_raises_unsupported_format_unchanged(tmp_path):
    p = tmp_path / "photo.bmp"
    p.write_bytes(_bmp_bytes())
    with pytest.raises(ImageIOError) as exc_info:
        load_image(p)
    assert exc_info.value.category == ErrorCategory.UNSUPPORTED_FORMAT
    assert "Format d'image non pris en charge" in exc_info.value.detail


def test_raw_and_unsupported_format_messages_share_no_common_rejection_label(tmp_path):
    raw_path = tmp_path / "photo.cr2"
    raw_path.write_bytes(b"arbitrary bytes")
    bmp_path = tmp_path / "photo.bmp"
    bmp_path.write_bytes(_bmp_bytes())

    with pytest.raises(ImageIOError) as raw_exc:
        load_image(raw_path)
    with pytest.raises(ImageIOError) as bmp_exc:
        load_image(bmp_path)

    assert raw_exc.value.category != bmp_exc.value.category
    assert "non pris en charge" not in raw_exc.value.detail
    assert "RAW" not in bmp_exc.value.detail


# ---------------------------------------------------------------------------
# US1 (052) — a decodable RAW candidate produces a valid, usable session
# (skipif no real decodable fixture is present -- see tests/fixtures/raw/README.md).
# ---------------------------------------------------------------------------

@_SKIP_NO_RAW_FIXTURE
def test_decode_raw_returns_uint16_hwc_rgb_array():
    """uint16 since decode_raw()'s amendment 3 (2026-08-21): its output is
    linear light, and 8 bits of linear is not enough precision to survive the
    sRGB encoding develop_initial() applies on top of it."""
    from lumaflow.engine.raw_decode import decode_raw

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    result = decode_raw(fixture)
    assert result.dtype == np.uint16
    assert result.ndim == 3
    assert result.shape[2] == 3


@_SKIP_NO_RAW_FIXTURE
def test_load_image_on_decodable_raw_produces_identical_original_and_active():
    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    session = load_image(fixture)
    assert np.array_equal(session.original, session.active)
    assert session.source.image_format == fixture.suffix.lstrip(".").upper()


@_SKIP_NO_RAW_FIXTURE
def test_load_image_on_decodable_raw_leaves_source_file_untouched():
    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    sha_before = _file_sha256(fixture)
    load_image(fixture)
    assert _file_sha256(fixture) == sha_before


# ---------------------------------------------------------------------------
# US2 (052) — a corrupted/fake RAW candidate always fails cleanly with
# RAW_NOT_DECODABLE, no crash, no fixture required.
# ---------------------------------------------------------------------------

_CORRUPTED_RAW_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "raw" / "corrupted.cr2"


def test_load_image_on_corrupted_raw_raises_raw_not_decodable_no_crash():
    with pytest.raises(ImageIOError) as exc_info:
        load_image(_CORRUPTED_RAW_FIXTURE)
    assert exc_info.value.category == ErrorCategory.RAW_NOT_DECODABLE


def test_load_image_on_corrupted_raw_leaves_source_file_untouched():
    sha_before = _file_sha256(_CORRUPTED_RAW_FIXTURE)
    with pytest.raises(ImageIOError):
        load_image(_CORRUPTED_RAW_FIXTURE)
    assert _file_sha256(_CORRUPTED_RAW_FIXTURE) == sha_before


# ---------------------------------------------------------------------------
# US3 (052) — a RAW-origin session exposes the same structural access
# pattern as a JPEG-origin session (no distinct downstream treatment).
# ---------------------------------------------------------------------------

@_SKIP_NO_RAW_FIXTURE
def test_raw_origin_session_has_same_structural_access_as_jpeg_origin(tmp_path):
    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    raw_session = load_image(fixture)

    jpeg_path = tmp_path / "img.jpg"
    jpeg_path.write_bytes(_jpeg_bytes())
    jpeg_session = load_image(jpeg_path)

    for attr in ("original", "active", "source"):
        assert hasattr(raw_session, attr)
        assert type(getattr(raw_session, attr)) is type(getattr(jpeg_session, attr))


# ---------------------------------------------------------------------------
# US1 (053) — a decoded RAW displays with plausible colors/exposure, using
# camera metadata for white balance when available (skipif no fixture).
# ---------------------------------------------------------------------------

@_SKIP_NO_RAW_FIXTURE
def test_develop_initial_produces_plausible_display_brightness(tmp_path):
    """The previous form of this test only asserted "not entirely 0" and "not
    entirely 255", which a single non-black pixel satisfies — it passed
    happily throughout the period when every RAW opened at a median luminance
    of 6-54/255. The band below is what a display-referred render actually
    looks like: measured 87-165 across 12 Canon/Nikon/Sony files, against
    45-180 for the cameras' own embedded JPEGs."""
    from lumaflow.engine.raw_decode import decode_raw
    from lumaflow.engine.raw_develop import develop_initial

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    base_pixels = decode_raw(fixture)
    developed, params = develop_initial(fixture, base_pixels)

    assert not np.all(developed == 0)
    assert not np.all(developed == 255)

    median_luminance = float(np.median(developed.mean(axis=2)))
    assert 60.0 <= median_luminance <= 190.0, (
        f"median luminance {median_luminance:.1f}/255 is outside the plausible "
        f"display-referred band (exposure gain was {params.exposure_gain_ev:+.2f} EV)"
    )


@_SKIP_NO_RAW_FIXTURE
def test_develop_initial_uses_metadata_white_balance_when_valid():
    import rawpy

    from lumaflow.engine.raw_decode import decode_raw
    from lumaflow.engine.raw_develop import develop_initial

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    with rawpy.imread(str(fixture)) as raw:
        camera_wb = raw.camera_whitebalance

    if not camera_wb or len(camera_wb) < 3 or min(camera_wb[:3]) <= 0:
        pytest.skip("Fixture has no valid camera_whitebalance metadata to compare against")

    red, green, blue = camera_wb[0], camera_wb[1], camera_wb[2]
    expected_gains = (red / green, 1.0, blue / green)

    base_pixels = decode_raw(fixture)
    _, params = develop_initial(fixture, base_pixels)
    assert params.white_balance_source == "metadata"
    assert params.white_balance_gains == pytest.approx(expected_gains)


@_SKIP_NO_RAW_FIXTURE
def test_load_image_on_raw_uses_develop_initial_pipeline_output():
    """decode_raw() now applies white balance itself (2026-08-04 amendment 2
    to raw_decode.py), so its output may legitimately be pixel-identical to
    the final session for a well-exposed photo — develop_initial()'s only
    remaining job, the exposure safeguard, is a no-op unless the image is
    degenerate. The older assertion here ("differs from raw decode output")
    no longer holds and would be testing an accident, not a contract. What's
    actually guaranteed: load_image()'s RAW branch runs the real
    develop_initial() pipeline (oriented consistently) and records the
    resolved gains."""
    from lumaflow.engine.raw_decode import decode_raw
    from lumaflow.engine.raw_develop import develop_initial
    from lumaflow.engine.raw_metadata import apply_orientation, orientation_flip_code

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    base_pixels = decode_raw(fixture)
    developed, _ = develop_initial(fixture, base_pixels)
    expected = apply_orientation(developed, orientation_flip_code(fixture))

    session = load_image(fixture)
    assert np.array_equal(session.original, expected)
    assert session.source.raw_white_balance_gains is not None


# ---------------------------------------------------------------------------
# US2 (053) — a RAW-developed session flows through the standard workflow
# exactly like a JPEG/PNG session, with no addon needing RAW-specific
# handling (skipif no fixture).
# ---------------------------------------------------------------------------

@_SKIP_NO_RAW_FIXTURE
def test_raw_developed_session_structural_shape_matches_jpeg_after_development(tmp_path):
    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    raw_session = load_image(fixture)

    jpeg_path = tmp_path / "img.jpg"
    jpeg_path.write_bytes(_jpeg_bytes())
    jpeg_session = load_image(jpeg_path)

    for attr in ("original", "active", "source"):
        assert hasattr(raw_session, attr)
        assert type(getattr(raw_session, attr)) is type(getattr(jpeg_session, attr))
    assert raw_session.source.raw_white_balance_gains is not None
    assert jpeg_session.source.raw_white_balance_gains is None


# ---------------------------------------------------------------------------
# US3 (053) — missing/unreadable white-balance metadata falls back to the
# documented neutral gains and still produces a usable result. Fully
# mock-based, no fixture required.
# ---------------------------------------------------------------------------

def test_develop_initial_falls_back_on_invalid_camera_whitebalance(monkeypatch):
    """White-balance metadata resolution now lives in raw_decode.py (2026-08-04
    amendment 2) — develop_initial() calls it a second time (header-only,
    cheap) purely for RawDevelopmentParams reporting, so the fake rawpy.imread
    to patch is raw_decode's, not raw_develop's."""
    from lumaflow.engine import raw_decode, raw_develop

    class _FakeRaw:
        camera_whitebalance = [0, 0, 0, 0]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(raw_decode.rawpy, "imread", lambda path: _FakeRaw())

    base_pixels = np.full((8, 8, 3), 11796, dtype=np.uint16)  # linear 0.18
    developed, params = raw_develop.develop_initial(pathlib.Path("irrelevant.cr2"), base_pixels)
    assert params.white_balance_source == "fallback"
    assert params.white_balance_gains == raw_develop.DEFAULT_WHITE_BALANCE_GAINS
    assert developed.dtype == np.uint8
    assert developed.shape == (8, 8, 3)


def test_develop_initial_falls_back_when_rawpy_imread_raises(monkeypatch):
    from lumaflow.engine import raw_decode, raw_develop

    def _raise(path):
        raise RuntimeError("simulated unreadable metadata")

    monkeypatch.setattr(raw_decode.rawpy, "imread", _raise)

    base_pixels = np.full((8, 8, 3), 11796, dtype=np.uint16)  # linear 0.18
    developed, params = raw_develop.develop_initial(pathlib.Path("irrelevant.cr2"), base_pixels)
    assert params.white_balance_source == "fallback"
    assert developed.dtype == np.uint8
    assert developed.shape == (8, 8, 3)


# ---------------------------------------------------------------------------
# US1 (053, amendment 2 of 2026-08-21) — the display transfer function and the
# bounded auto-exposure that together fixed "RAW files open far too dark".
# Fully synthetic: a uint16 linear array stands in for decode_raw()'s output,
# so these run in CI where no real RAW file is committed.
# ---------------------------------------------------------------------------

def test_tone_curve_applies_the_srgb_transfer_function():
    """The bug was the *absence* of any transfer function: linear light went
    to the screen as if it were sRGB-encoded. These are the textbook sRGB
    reference points at unity gain — 18% mid-gray must land near middle of
    the 8-bit range, not near the bottom (it used to arrive at ~46)."""
    from lumaflow.engine.raw_develop import _build_tone_lut

    lut = _build_tone_lut(1.0)
    assert int(lut[0]) == 0
    assert int(lut[round(0.18 * 65535)]) == 118  # sRGB OETF(0.18) * 255
    assert int(lut[round(0.50 * 65535)]) == 188  # sRGB OETF(0.50) * 255
    assert np.all(np.diff(lut.astype(int)) >= 0), "tone curve must be monotonic"


def test_tone_curve_shoulder_keeps_highlight_headroom_at_unity_gain():
    """The soft shoulder exists so the exposure gain cannot slam highlights
    into a hard clip. At unity gain nothing in the input domain should reach
    255 — if this ever hits 255 the shoulder has been flattened away."""
    from lumaflow.engine.raw_develop import _build_tone_lut

    assert int(_build_tone_lut(1.0).max()) < 255


def test_tone_lut_matches_the_direct_computation_exactly():
    """`_build_tone_lut` is a 23x speedup over evaluating the same math across
    a full-resolution array (0.18s vs 4.10s on a 6080x4044 file). It is only
    legitimate if it is *exactly* the same function, at every gain."""
    from lumaflow.engine.raw_develop import _build_tone_lut, _tone_transfer

    rng = np.random.default_rng(0)
    sample = rng.integers(0, 65536, size=(64, 64, 3), dtype=np.uint16)

    for gain in (1.0, 1.7, 4.0):
        via_lut = _build_tone_lut(gain)[sample]
        direct = _tone_transfer(sample.astype(np.float32) / 65535.0, gain) * 255.0
        direct = np.clip(np.round(direct), 0, 255).astype(np.uint8)
        assert np.array_equal(via_lut, direct), f"LUT diverges from direct math at gain {gain}"


def test_auto_exposure_gain_never_darkens_and_is_capped_at_2ev():
    """The RAW already carries the exposure the photographer chose, so the
    auto-exposure only ever rescues under-exposure. Normalizing every image
    onto a fixed mid-gray target was measured and is worse (mean error 27.6
    against the camera JPEGs, versus 20.2 for this bounded form) because it
    flattens a deliberately dark frame up and a bright one down."""
    from lumaflow.engine.raw_develop import _GAIN_MAX, _GAIN_MIN, _auto_exposure_gain

    nearly_black = np.full((32, 32, 3), 200, dtype=np.uint16)
    already_bright = np.full((32, 32, 3), 59000, dtype=np.uint16)

    assert _auto_exposure_gain(nearly_black) == pytest.approx(_GAIN_MAX)  # +2 EV ceiling
    assert _auto_exposure_gain(already_bright) == pytest.approx(_GAIN_MIN)  # never darkens
    assert _GAIN_MIN == 1.0 and _GAIN_MAX == 4.0


def test_develop_initial_reports_the_exposure_gain_it_applied(monkeypatch):
    from lumaflow.engine import raw_decode, raw_develop

    def _raise(path):
        raise RuntimeError("simulated unreadable metadata")

    monkeypatch.setattr(raw_decode.rawpy, "imread", _raise)

    already_bright = np.full((32, 32, 3), 59000, dtype=np.uint16)
    _, params = raw_develop.develop_initial(pathlib.Path("irrelevant.cr2"), already_bright)
    assert params.exposure_gain_ev == pytest.approx(0.0)


def test_develop_initial_rejects_8bit_input():
    """Guards the 052/053 contract: 8-bit input would be silently interpreted
    on the wrong scale (a value of 128 read as linear 0.002 instead of 0.5),
    mis-exposing the whole image rather than failing."""
    from lumaflow.engine.raw_develop import develop_initial

    with pytest.raises(ValueError, match="uint16"):
        develop_initial(pathlib.Path("irrelevant.cr2"), np.full((8, 8, 3), 128, dtype=np.uint8))


def test_load_image_raw_fallback_path_end_to_end_with_no_fixture(monkeypatch):
    from lumaflow.engine import image_io, raw_decode

    synthetic = np.full((8, 8, 3), 11796, dtype=np.uint16)  # linear 0.18
    monkeypatch.setattr(image_io, "decode_raw", lambda path: synthetic)

    def _raise(path):
        raise RuntimeError("simulated unreadable metadata")

    monkeypatch.setattr(raw_decode.rawpy, "imread", _raise)

    fixture = pathlib.Path(__file__).parent / "fixtures" / "raw_candidate.cr2"
    session = load_image(fixture)
    assert session.source.raw_white_balance_source == "fallback"


# ---------------------------------------------------------------------------
# US1 (054) — camera model, lens, and capture date are preserved when
# present in the RAW file's EXIF data (skipif no fixture with known EXIF).
# ---------------------------------------------------------------------------

@_SKIP_NO_RAW_FIXTURE
def test_extract_raw_metadata_matches_pillow_exif_directly(tmp_path):
    from PIL import ExifTags, Image as PILImage

    from lumaflow.engine.raw_metadata import extract_raw_metadata

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    try:
        with PILImage.open(fixture) as pil_image:
            exif = pil_image.getexif()
            make = exif.get(271)
            model = exif.get(272)
            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except Exception:
                exif_ifd = {}
    except Exception:
        # Some RAW variants (e.g. certain Sony ARW files) aren't identifiable
        # by Pillow at all, even though extract_raw_metadata() itself handles
        # this gracefully (never raises, degrades to None fields) — nothing
        # to compare against here.
        pytest.skip("Fixture is not directly openable by Pillow, nothing to compare against")

    if not (make or model):
        pytest.skip("Fixture has no Make/Model EXIF tags to compare against")

    metadata = extract_raw_metadata(fixture)
    if model and str(model).strip().startswith(str(make or "").strip()):
        assert metadata.camera_model == str(model).strip()
    else:
        assert metadata.camera_model == f"{make} {model}".strip()

    if exif_ifd.get(42036):
        assert metadata.lens_model == exif_ifd.get(42036)
    if exif_ifd.get(36867):
        assert metadata.capture_date == exif_ifd.get(36867)


@_SKIP_NO_RAW_FIXTURE
def test_load_image_on_raw_populates_metadata_matching_standalone_extraction():
    from lumaflow.engine.raw_metadata import extract_raw_metadata

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    expected = extract_raw_metadata(fixture)
    session = load_image(fixture)
    assert session.source.raw_camera_model == expected.camera_model
    assert session.source.raw_lens_model == expected.lens_model
    assert session.source.raw_capture_date == expected.capture_date


def test_extract_raw_metadata_partial_metadata_no_fabricated_values(monkeypatch):
    """Mock-based rather than fixture-gated (deviating slightly from the task's literal
    wording): a real "partial EXIF" RAW fixture can't be authored any more reliably than a
    full one, and mocking PIL directly exercises the exact same per-field independence in
    extract_raw_metadata() unconditionally, mirroring the US3 mocking approach below."""
    from lumaflow.engine import raw_metadata

    class _FakeExif(dict):
        def get_ifd(self, ifd):
            return {}  # Exif sub-IFD empty: LensModel and DateTimeOriginal both absent

    class _FakePilImage:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def getexif(self):
            return _FakeExif({271: "Canon", 272: "EOS R5", 306: "2026:01:01 10:00:00"})

    monkeypatch.setattr(raw_metadata.Image, "open", lambda path: _FakePilImage())

    metadata = raw_metadata.extract_raw_metadata(pathlib.Path("irrelevant.cr2"))
    assert metadata.camera_model == "Canon EOS R5"
    assert metadata.lens_model is None
    assert metadata.capture_date == "2026:01:01 10:00:00"


# ---------------------------------------------------------------------------
# US2 (054) — a RAW file displays with the correct orientation. Core logic
# (apply_orientation) is unit-tested with synthetic arrays, no fixture
# needed; end-to-end display correctness is skipif-gated.
# ---------------------------------------------------------------------------

def _mark_top_left(shape=(4, 8, 3)) -> np.ndarray:
    arr = np.zeros(shape, dtype=np.uint8)
    arr[0, 0] = [255, 0, 0]
    return arr


def test_apply_orientation_flip_code_0_returns_pixels_unchanged():
    from lumaflow.engine.raw_metadata import apply_orientation

    arr = _mark_top_left()
    result = apply_orientation(arr, 0)
    assert result is arr


def test_apply_orientation_flip_code_3_rotates_180_degrees():
    from lumaflow.engine.raw_metadata import apply_orientation

    arr = _mark_top_left()
    result = apply_orientation(arr, 3)
    assert result.shape == (4, 8, 3)
    # 180 deg: top-left corner moves to bottom-right (H-1, W-1) — direction-agnostic.
    assert np.array_equal(result[3, 7], [255, 0, 0])
    assert result[0, 0].sum() == 0


def test_apply_orientation_flip_code_5_rotates_90_counterclockwise():
    from lumaflow.engine.raw_metadata import apply_orientation

    arr = _mark_top_left()
    result = apply_orientation(arr, 5)
    assert result.shape == (8, 4, 3)
    # Empirically verified numpy.rot90(k=1) mapping: top-left -> bottom-left of new shape.
    assert np.array_equal(result[7, 0], [255, 0, 0])


def test_apply_orientation_flip_code_6_rotates_90_clockwise():
    from lumaflow.engine.raw_metadata import apply_orientation

    arr = _mark_top_left()
    result = apply_orientation(arr, 6)
    assert result.shape == (8, 4, 3)
    # Empirically verified numpy.rot90(k=-1) mapping: top-left -> top-right of new shape.
    assert np.array_equal(result[0, 3], [255, 0, 0])


def test_apply_orientation_unknown_flip_code_passthrough():
    from lumaflow.engine.raw_metadata import apply_orientation

    arr = _mark_top_left()
    result = apply_orientation(arr, 99)
    assert result is arr


def test_orientation_flip_code_returns_0_for_unreadable_path():
    from lumaflow.engine.raw_metadata import orientation_flip_code

    assert orientation_flip_code(pathlib.Path("does_not_exist.cr2")) == 0


@_SKIP_NO_RAW_FIXTURE
def test_decode_raw_no_longer_auto_rotates(tmp_path):
    """Confirms 054's amendment to 052: decode_raw()'s user_flip=0 means orientation is
    054's exclusive responsibility, never applied implicitly by rawpy/LibRaw."""
    import rawpy as rawpy_module

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    with rawpy_module.imread(str(fixture)) as raw:
        flip_code = raw.sizes.flip

    if flip_code not in (3, 5, 6):
        pytest.skip("Fixture has no non-trivial orientation to distinguish auto-rotation from none")

    from lumaflow.engine.raw_decode import decode_raw
    from lumaflow.engine.raw_metadata import apply_orientation

    raw_output = decode_raw(fixture)
    manually_oriented = apply_orientation(raw_output, flip_code)
    # If decode_raw already auto-rotated, applying the rotation again would double-rotate,
    # producing a different shape/content than session's actual (correctly oriented) output.
    session = load_image(fixture)
    assert manually_oriented.shape == session.original.shape


# ---------------------------------------------------------------------------
# US3 (054) — missing/corrupted EXIF/orientation data never blocks opening.
# Fully mock-based, no fixture required.
# ---------------------------------------------------------------------------

def test_extract_raw_metadata_returns_all_none_when_pil_open_raises(monkeypatch):
    from lumaflow.engine import raw_metadata

    def _raise(path):
        raise RuntimeError("simulated unreadable EXIF")

    monkeypatch.setattr(raw_metadata.Image, "open", _raise)

    metadata = raw_metadata.extract_raw_metadata(pathlib.Path("irrelevant.cr2"))
    assert metadata.camera_model is None
    assert metadata.lens_model is None
    assert metadata.capture_date is None


def test_orientation_flip_code_returns_0_when_rawpy_imread_raises(monkeypatch):
    from lumaflow.engine import raw_metadata

    def _raise(path):
        raise RuntimeError("simulated unreadable orientation metadata")

    monkeypatch.setattr(raw_metadata.rawpy, "imread", _raise)

    assert raw_metadata.orientation_flip_code(pathlib.Path("irrelevant.cr2")) == 0


def test_load_image_raw_degraded_metadata_path_end_to_end_with_no_fixture(monkeypatch):
    from lumaflow.engine import image_io, raw_decode, raw_metadata

    synthetic = np.full((8, 8, 3), 11796, dtype=np.uint16)  # linear 0.18
    monkeypatch.setattr(image_io, "decode_raw", lambda path: synthetic)

    def _raise(path):
        raise RuntimeError("simulated unreadable metadata")

    monkeypatch.setattr(raw_decode.rawpy, "imread", _raise)
    monkeypatch.setattr(raw_metadata.Image, "open", _raise)
    monkeypatch.setattr(raw_metadata.rawpy, "imread", _raise)

    fixture = pathlib.Path(__file__).parent / "fixtures" / "raw_candidate.cr2"
    session = load_image(fixture)
    assert session.source.raw_camera_model is None
    assert session.source.raw_lens_model is None
    assert session.source.raw_capture_date is None


# ---------------------------------------------------------------------------
# US4 (054) — metadata recorded at open time is retrievable unchanged later,
# without re-decoding the source file (skipif no fixture with known EXIF).
# ---------------------------------------------------------------------------

@_SKIP_NO_RAW_FIXTURE
def test_raw_metadata_fields_identical_across_repeated_reads():
    from lumaflow.engine.pipeline import Pipeline, PipelineEngine

    fixture = _FIRST_DECODABLE_RAW_FIXTURE
    session = load_image(fixture)

    first_read = (
        session.source.raw_camera_model,
        session.source.raw_lens_model,
        session.source.raw_capture_date,
    )

    PipelineEngine().run(Pipeline(), session.active)

    second_read = (
        session.source.raw_camera_model,
        session.source.raw_lens_model,
        session.source.raw_capture_date,
    )
    assert first_read == second_read
