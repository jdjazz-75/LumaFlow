# LumaFlow v1.0 (2026-08-25)
# Tests du moteur de traitement par lot sans interface : regle de nommage des fichiers de
# sortie, export nominal, et contrat "process_one ne leve jamais" sur chaque mode d'echec.
"""Feature: traitement par lot (2026-08-25) -- `lumaflow.engine.batch`.

The invariant every test here defends is the one the whole feature rests on: **one bad file must
cost one log line, never the run**. So the failure cases are as important as the nominal one.
"""
from __future__ import annotations

import pathlib
from datetime import datetime

import numpy
import pytest
from PIL import Image

from lumaflow.engine.batch import (
    BatchItemOutcome,
    image_format_for,
    output_extension,
    process_one,
    resolve_output_path,
    unique_output_path,
)
from lumaflow.engine.pipeline import Pipeline, PipelineStep, StepParameters

FIXTURE_IMAGE = pathlib.Path(__file__).parent / "fixtures" / "deterministic_8x8.png"
WHEN = datetime(2026, 8, 25, 14, 32, 7)


def _identity_pipeline() -> Pipeline:
    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="passthrough"))
    return pipeline


def _darkening_pipeline() -> Pipeline:
    """A pipeline that visibly changes pixels, so an export test can prove the RESULT was written
    rather than a copy of the source."""
    pipeline = Pipeline()
    pipeline.add_step(
        PipelineStep(
            identifier="halve",
            parameters=StepParameters(values={}),
            processor=lambda image, _params: (image // 2).astype(numpy.uint8),
        )
    )
    return pipeline


def _exploding_pipeline() -> Pipeline:
    def boom(_image, _params):
        raise RuntimeError("addon interne cassé")

    pipeline = Pipeline()
    pipeline.add_step(PipelineStep(identifier="film", processor=boom))
    return pipeline


# --- Naming rule: <stem source>-<stem preset>-<AA-MM-DD-HH-MM-SS>.<ext> ---


def test_output_path_follows_the_naming_rule(tmp_path):
    result = resolve_output_path(
        pathlib.Path("D:/photos/IMG_0431.JPG"), pathlib.Path("C:/presets/velvia-doux.json"), tmp_path, WHEN
    )
    assert result == tmp_path / "IMG_0431-velvia-doux-26-08-25-14-32-07.jpg"


def test_output_timestamp_is_year_first_so_names_sort_chronologically(tmp_path):
    """AA-MM-DD-HH-MM-SS, not MM-AA-DD (user correction, 2026-08-25): two runs of the same source/
    preset must sort in time order when the directory is sorted by name."""
    earlier = resolve_output_path(
        FIXTURE_IMAGE, pathlib.Path("p.json"), tmp_path, datetime(2026, 8, 25, 9, 0, 0)
    )
    later = resolve_output_path(
        FIXTURE_IMAGE, pathlib.Path("p.json"), tmp_path, datetime(2026, 12, 3, 9, 0, 0)
    )
    assert earlier.name < later.name


def test_png_source_stays_png_and_everything_else_becomes_jpeg():
    assert output_extension(pathlib.Path("a.png")) == ".png"
    assert output_extension(pathlib.Path("a.PNG")) == ".png"
    assert output_extension(pathlib.Path("a.jpg")) == ".jpg"
    assert output_extension(pathlib.Path("a.jpeg")) == ".jpg"
    # RAW cannot be written back -- a batch over RAW files produces JPEG.
    assert output_extension(pathlib.Path("a.cr2")) == ".jpg"
    assert output_extension(pathlib.Path("a.NEF")) == ".jpg"
    assert output_extension(pathlib.Path("a.arw")) == ".jpg"


def test_image_format_matches_the_extension_the_naming_rule_produces():
    assert image_format_for(pathlib.Path("x.png")) == "PNG"
    assert image_format_for(pathlib.Path("x.jpg")) == "JPEG"


def test_a_free_name_is_used_as_is(tmp_path):
    candidate = tmp_path / "IMG-preset-26-08-25-14-32-07.jpg"
    assert unique_output_path(candidate) == candidate


def test_a_taken_name_gets_a_counter_rather_than_overwriting(tmp_path):
    """The one collision a second-granularity timestamp cannot separate (same source name, same
    preset, same directory, same second). Measured for real on 2026-08-25: a 156-image run whose
    sources repeated wrote only 36 files before this guard existed."""
    candidate = tmp_path / "IMG-preset-26-08-25-14-32-07.jpg"
    candidate.write_bytes(b"deja la")

    assert unique_output_path(candidate) == tmp_path / "IMG-preset-26-08-25-14-32-07-2.jpg"


def test_the_counter_keeps_climbing_while_names_are_taken(tmp_path):
    candidate = tmp_path / "IMG-preset-26-08-25-14-32-07.jpg"
    candidate.write_bytes(b"x")
    (tmp_path / "IMG-preset-26-08-25-14-32-07-2.jpg").write_bytes(b"x")
    (tmp_path / "IMG-preset-26-08-25-14-32-07-3.jpg").write_bytes(b"x")

    assert unique_output_path(candidate) == tmp_path / "IMG-preset-26-08-25-14-32-07-4.jpg"


# --- Nominal run ---


def test_process_one_writes_the_processed_result(tmp_path):
    output_path = tmp_path / "out.png"
    outcome = process_one(FIXTURE_IMAGE, _darkening_pipeline(), output_path)

    assert outcome.ok is True
    assert outcome.message == ""
    assert outcome.output_path == output_path
    assert output_path.is_file()

    source_pixels = numpy.asarray(Image.open(FIXTURE_IMAGE).convert("RGB"), dtype=numpy.uint8)
    written_pixels = numpy.asarray(Image.open(output_path).convert("RGB"), dtype=numpy.uint8)
    assert numpy.array_equal(written_pixels, source_pixels // 2)


def test_process_one_exports_at_full_source_resolution(tmp_path):
    """A batch has no preview to keep fast -- unlike the interactive filmstrip path, which renders
    on a downscaled working copy (see Session.working_image), it must write the real thing."""
    output_path = tmp_path / "out.png"
    process_one(FIXTURE_IMAGE, _identity_pipeline(), output_path)

    with Image.open(FIXTURE_IMAGE) as source, Image.open(output_path) as written:
        assert written.size == source.size


def test_process_one_writes_jpeg_when_the_output_path_says_jpeg(tmp_path):
    output_path = tmp_path / "out.jpg"
    outcome = process_one(FIXTURE_IMAGE, _identity_pipeline(), output_path, jpeg_quality=90)

    assert outcome.ok is True
    with Image.open(output_path) as written:
        assert written.format == "JPEG"


def test_process_one_leaves_the_source_file_untouched(tmp_path):
    from tests.conftest import assert_file_unchanged

    with assert_file_unchanged(FIXTURE_IMAGE):
        process_one(FIXTURE_IMAGE, _darkening_pipeline(), tmp_path / "out.png")


# --- Failure modes: never raise, always a clear French message, nothing written ---


@pytest.mark.parametrize(
    "make_source",
    [
        pytest.param(lambda tmp: tmp / "absent.png", id="missing_file"),
        pytest.param(lambda tmp: _write_bytes(tmp / "broken.png", b"pas une image"), id="corrupted_file"),
        pytest.param(lambda tmp: _write_bytes(tmp / "unsupported.gif", b"GIF89a"), id="unsupported_format"),
    ],
)
def test_unreadable_source_is_a_clean_failure(tmp_path, make_source):
    source = make_source(tmp_path)
    output_path = tmp_path / "out.png"

    outcome = process_one(source, _identity_pipeline(), output_path)

    assert isinstance(outcome, BatchItemOutcome)
    assert outcome.ok is False
    assert outcome.output_path is None
    assert outcome.message  # a real sentence, not an empty string
    assert not output_path.exists()


def test_addon_failure_mid_pipeline_names_the_step_without_leaking_the_exception(tmp_path):
    output_path = tmp_path / "out.png"

    outcome = process_one(FIXTURE_IMAGE, _exploding_pipeline(), output_path)

    assert outcome.ok is False
    assert "film" in outcome.message
    assert "RuntimeError" not in outcome.message and "cassé" not in outcome.message
    assert not output_path.exists()


def test_unwritable_destination_is_a_clean_failure(tmp_path):
    outcome = process_one(FIXTURE_IMAGE, _identity_pipeline(), tmp_path / "absent-dir" / "out.png")

    assert outcome.ok is False
    assert outcome.output_path is None
    assert outcome.message


def test_a_failure_does_not_prevent_the_next_file(tmp_path):
    """The whole point of the outcome-instead-of-exception contract: the caller's loop survives."""
    broken = _write_bytes(tmp_path / "broken.png", b"pas une image")

    outcomes = [
        process_one(broken, _identity_pipeline(), tmp_path / "a.png"),
        process_one(FIXTURE_IMAGE, _identity_pipeline(), tmp_path / "b.png"),
    ]

    assert [outcome.ok for outcome in outcomes] == [False, True]
    assert (tmp_path / "b.png").is_file()


def _write_bytes(path: pathlib.Path, content: bytes) -> pathlib.Path:
    path.write_bytes(content)
    return path
