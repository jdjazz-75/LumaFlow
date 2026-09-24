# LumaFlow v1.0 (2026-08-07)
# Configuration pytest partagée : fixtures autouse (désactivation du délai de precompute), fixture
# image déterministe, découverte des fixtures RAW décodables et rapport de couverture RAW en fin de run.

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_FIXTURE_PNG = Path(__file__).parent / "fixtures" / "deterministic_8x8.png"


@pytest.fixture(autouse=True)
def _no_row_before_precompute_delay(monkeypatch):
    """FastAPI's TestClient runs BackgroundTasks synchronously before returning from client.post(...)
    (measured: a 0.5s background sleep adds ~0.5s to the client call itself) -- unlike real uvicorn,
    where the background precompute genuinely runs after the response reaches the browser. Without
    this, PERF-ZOOM-RENDER-PLAN.md étape 4's 0.4s debounce delay would tax every single test that
    hits the /activate or /select endpoint through the TestClient, for a delay whose only purpose is
    real-world arrow-key debouncing -- irrelevant to what those tests are checking. Dedicated étape 4
    tests (tests/test_row_before_precompute.py) monkeypatch this per-test where the delay itself
    matters, so zeroing it here globally doesn't reduce coverage."""
    import lumaflow.api.session as session_module

    monkeypatch.setattr(session_module, "_ROW_BEFORE_PRECOMPUTE_DELAY_S", 0.0)


# ---------------------------------------------------------------------------
# 100 — LaMa pivot (research.md R3): stub the real network by default so `pytest`
# stays fast/offline, matching this repo's `raw_fixture` precedent (a real dependency
# opted into explicitly, not paid by every test run).
# ---------------------------------------------------------------------------


def _stub_lama_run(roi_image, roi_hole, target_long_edge):
    """Deterministic, fast, numpy-only substitute for `lama_backend.run` -- fills the hole with the
    mean colour of the ROI's own non-hole pixels (or mid-grey if there are none), plus a small
    offset DERIVED FROM THE (SOLVE-TIME) HOLE'S OWN PIXEL COUNT, broadcast flat. The offset matters:
    `engine.py`'s "variant" mechanic works by dilating the hole passed to the solver by a few pixels
    (not by passing `variant` into the solve call itself, see `engine.py`'s module docstring), so
    two different variants typically differ only by a thin boundary ring of pixels -- a plain
    non-hole mean colour alone can land on the exact same rounded uint8 for two such
    barely-different holes on the same textured test image, which would make
    `..._different_variant_changes_only_inside`-style tests fail for a reason that has nothing to
    do with a real bug. Exercises the exact same call contract (shape/dtype in, shape/dtype out) so
    every test of `engine.py`'s cropping/clustering/compositing plumbing stays meaningful without
    needing torch or a downloaded model -- it is deliberately too crude to prove fill QUALITY, which
    is what the `model`-marked tests (real LaMa) are for instead."""
    import numpy

    if not numpy.any(~roi_hole):
        base = numpy.full(3, 128.0, dtype=numpy.float32)
    else:
        base = roi_image[~roi_hole].mean(axis=0)
    hole_seed = int(numpy.count_nonzero(roi_hole)) % 41
    offset = numpy.array([hole_seed, (hole_seed * 2) % 41, (hole_seed * 3) % 41], dtype=numpy.float32)
    fill = numpy.clip(base + offset, 0.0, 255.0)
    return numpy.broadcast_to(fill, roi_image.shape).astype(numpy.float32).copy()


@pytest.fixture(autouse=True)
def _stub_lama_backend_by_default(request, monkeypatch):
    if request.node.get_closest_marker("model") is not None:
        yield
        return
    from lumaflow.addons.inpainting import lama_backend

    monkeypatch.setattr(lama_backend, "run", _stub_lama_run)
    yield


@pytest.fixture
def deterministic_session():
    from lumaflow.engine.image_io import load_image

    assert _FIXTURE_PNG.exists(), (
        f"Deterministic fixture missing: {_FIXTURE_PNG}. "
        "Commit tests/fixtures/deterministic_8x8.png."
    )
    return load_image(_FIXTURE_PNG)


# ---------------------------------------------------------------------------
# 055 — shared RAW fixture discovery, coverage report, and non-destructiveness
# helper. Single source of truth for "is a real decodable RAW fixture
# available", superseding the ad hoc local helpers 052/053/054 each sketched
# independently in tests/test_image_load.py.
# ---------------------------------------------------------------------------

RAW_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "raw"
CORRUPTED_RAW_FIXTURE = RAW_FIXTURES_DIR / "corrupted.cr2"


def decodable_raw_fixtures() -> dict[str, Path]:
    if not RAW_FIXTURES_DIR.is_dir():
        return {}
    return {
        path.suffix.lower().lstrip("."): path
        for path in sorted(RAW_FIXTURES_DIR.glob("sample.*"))
    }


@contextmanager
def assert_file_unchanged(path: Path):
    sha_before = hashlib.sha256(path.read_bytes()).hexdigest()
    yield
    sha_after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sha_after == sha_before, f"{path} was modified during the test"


def pytest_terminal_summary(terminalreporter):
    from lumaflow.engine.raw_formats import RAW_EXTENSIONS

    fixtures = decodable_raw_fixtures()
    terminalreporter.write_sep("-", "RAW fixture coverage")
    for ext in sorted(RAW_EXTENSIONS):
        key = ext.lstrip(".")
        if key in fixtures:
            terminalreporter.write_line(f"{ext}: couverte (fixture décodable présente)")
        else:
            terminalreporter.write_line(
                f"{ext}: couverte uniquement par le chemin d'échec (aucune fixture décodable disponible)"
            )
