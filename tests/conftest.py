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
