# LumaFlow v1.0 (2026-08-25)
# Tests de l'orchestration et des endpoints de traitement par lot : cycle complet, progression
# par lot et globale, journal, arret, validation des lots et refus d'execution concurrente.
"""Feature: traitement par lot (2026-08-25) -- `lumaflow.api.batch_runs` + the /batch/* endpoints.

Runs are executed on a background thread, so every test that needs a finished run polls
`_wait_until_settled` rather than assuming the POST already did the work.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import threading
import time

import pytest
from fastapi.testclient import TestClient

from lumaflow.api import app as api_app
from lumaflow.api import batch_runs
from lumaflow.api.app import app

FIXTURE_IMAGE = pathlib.Path(__file__).parent / "fixtures" / "deterministic_8x8.png"
SETTLE_TIMEOUT_S = 30.0


class _FakeTkRoot:
    """Same rationale as test_api_session_wiring.py's own copy: no dialog test here exercises Tk
    itself, and real Tk() create/destroy cycling at pytest's rate is a documented source of
    spurious TclError failures on this machine (memory `tkinter-dialog-threadpool-crash`)."""

    def withdraw(self) -> None:
        pass

    def attributes(self, *args, **kwargs) -> None:
        pass

    def destroy(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fake_tk(monkeypatch):
    monkeypatch.setattr(api_app, "Tk", _FakeTkRoot)


@pytest.fixture(autouse=True)
def _clean_run_registry():
    """The run registry and its "one at a time" latch are process-wide module state -- a run left
    behind by one test would make the next one fail with 409 for no reason."""
    yield
    _wait_for_idle()
    with batch_runs._REGISTRY_LOCK:
        batch_runs._RUNS.clear()
        batch_runs._ACTIVE_RUN_ID = None


def _wait_for_idle(timeout: float = SETTLE_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with batch_runs._REGISTRY_LOCK:
            active_id = batch_runs._ACTIVE_RUN_ID
        if active_id is None:
            return
        time.sleep(0.02)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def slow_processing(monkeypatch):
    """Makes "is the run still going?" deterministic instead of a race against the clock.

    The 8x8 test fixture renders in milliseconds, so a test that starts a run and immediately
    expects it to be mid-flight (stop, concurrent-run refusal) would be betting on the executor
    thread being slower than the test thread. This slows each image down and, more importantly,
    hands back an Event signalling that the FIRST image has actually started -- so the test can
    wait for a real state instead of guessing. Returns that Event."""
    started = threading.Event()
    real_process_one = batch_runs.process_one

    def slow(*args, **kwargs):
        started.set()
        time.sleep(0.05)
        return real_process_one(*args, **kwargs)

    monkeypatch.setattr(batch_runs, "process_one", slow)
    return started


@pytest.fixture
def preset_path(tmp_path) -> pathlib.Path:
    """A real, loadable preset over the current workflow rows -- Velvia on the Film row, neutral
    everywhere else."""
    path = tmp_path / "velvia-doux.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "steps": [
                    {"step_identifier": "film", "thumbnail_identifier": "Velvia", "parameters": {"look": "Velvia"}},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def sources(tmp_path) -> list[pathlib.Path]:
    paths = []
    for index in range(3):
        destination = tmp_path / f"IMG_{index}.png"
        shutil.copyfile(FIXTURE_IMAGE, destination)
        paths.append(destination)
    return paths


@pytest.fixture
def output_dir(tmp_path) -> pathlib.Path:
    directory = tmp_path / "sortie"
    directory.mkdir()
    return directory


def _start(client, batches: list[dict]):
    return client.post("/batch/runs", json={"batches": batches})


def _batch(files, preset_path, output_dir) -> dict:
    return {
        "files": [str(path) for path in files],
        "preset_path": str(preset_path),
        "output_dir": str(output_dir),
    }


def _wait_until_settled(client, run_id: str, timeout: float = SETTLE_TIMEOUT_S) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/batch/runs/{run_id}").json()
        if payload["state"] != "running":
            return payload
        time.sleep(0.02)
    raise AssertionError(f"Batch run {run_id} never settled within {timeout}s")


# --- Nominal run ---


def test_run_processes_every_file_and_reaches_100_percent(client, sources, preset_path, output_dir):
    started = _start(client, [_batch(sources, preset_path, output_dir)])
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    final = _wait_until_settled(client, run_id)

    assert final["state"] == "finished"
    assert final["done"] == final["total"] == 3
    assert final["success_count"] == 3
    assert final["error_count"] == 0
    assert final["global_percent"] == 100
    assert final["batches"] == [{"total": 3, "done": 3, "percent": 100}]


def test_run_writes_one_file_per_source_following_the_naming_rule(client, sources, preset_path, output_dir):
    run_id = _start(client, [_batch(sources, preset_path, output_dir)]).json()["run_id"]
    _wait_until_settled(client, run_id)

    written = sorted(path.name for path in output_dir.iterdir())
    assert len(written) == 3
    for index, name in enumerate(written):
        # <stem source>-<stem preset>-<AA-MM-DD-HH-MM-SS>.<ext>
        assert name.startswith(f"IMG_{index}-velvia-doux-")
        assert name.endswith(".png")  # PNG source stays PNG
        timestamp = name[len(f"IMG_{index}-velvia-doux-") : -len(".png")]
        assert len(timestamp.split("-")) == 6


def test_journal_has_one_line_per_file_with_running_index(client, sources, preset_path, output_dir):
    run_id = _start(client, [_batch(sources, preset_path, output_dir)]).json()["run_id"]
    final = _wait_until_settled(client, run_id)

    assert [entry["index"] for entry in final["log"]] == [1, 2, 3]
    assert all(entry["total"] == 3 for entry in final["log"])
    assert all(entry["ok"] for entry in final["log"])
    assert [entry["file_name"] for entry in final["log"]] == ["IMG_0.png", "IMG_1.png", "IMG_2.png"]
    assert all(entry["output_name"] for entry in final["log"])


def test_several_batches_have_their_own_progress_and_a_shared_global_one(
    client, sources, preset_path, output_dir, tmp_path
):
    second_output = tmp_path / "sortie-2"
    second_output.mkdir()
    run_id = _start(
        client,
        [
            _batch(sources, preset_path, output_dir),
            _batch(sources[:1], preset_path, second_output),
        ],
    ).json()["run_id"]

    final = _wait_until_settled(client, run_id)

    assert final["total"] == 4
    assert final["batches"] == [
        {"total": 3, "done": 3, "percent": 100},
        {"total": 1, "done": 1, "percent": 100},
    ]
    assert final["global_percent"] == 100
    assert [entry["batch_index"] for entry in final["log"]] == [0, 0, 0, 1]
    assert len(list(second_output.iterdir())) == 1


def test_every_success_produces_its_own_file_even_when_sources_repeat(
    client, sources, preset_path, output_dir
):
    """Regression, measured 2026-08-25: two batches sharing a photo and an output directory
    complete within the same second, so the timestamp alone cannot separate their output names --
    a 156-image run wrote only 36 files, silently losing the rest. Every success must map to
    exactly one file on disk."""
    second_batch_files = sources  # deliberately the SAME sources, into the SAME directory
    run_id = _start(
        client,
        [
            _batch(sources, preset_path, output_dir),
            _batch(second_batch_files, preset_path, output_dir),
        ],
    ).json()["run_id"]

    final = _wait_until_settled(client, run_id)

    assert final["success_count"] == 6
    assert len(list(output_dir.iterdir())) == 6
    # Each journal line names the file it actually wrote, so the journal stays a true record.
    written = {path.name for path in output_dir.iterdir()}
    assert {entry["output_name"] for entry in final["log"]} == written


# --- Failures: one bad file costs one line, not the run ---


def test_an_unreadable_file_fails_alone_and_the_run_continues(
    client, sources, preset_path, output_dir, tmp_path
):
    broken = tmp_path / "corrompu.png"
    broken.write_bytes(b"pas une image")
    files = [broken, *sources]

    run_id = _start(client, [_batch(files, preset_path, output_dir)]).json()["run_id"]
    final = _wait_until_settled(client, run_id)

    assert final["state"] == "finished"
    assert final["done"] == 4
    assert final["success_count"] == 3
    assert final["error_count"] == 1
    assert final["global_percent"] == 100  # progress counts attempted files, failures included

    failed = final["log"][0]
    assert failed["ok"] is False
    assert failed["file_name"] == "corrompu.png"
    assert failed["message"]
    assert len(list(output_dir.iterdir())) == 3


def test_a_missing_source_file_fails_alone(client, sources, preset_path, output_dir, tmp_path):
    run_id = _start(
        client, [_batch([tmp_path / "jamais-existe.png", *sources], preset_path, output_dir)]
    ).json()["run_id"]
    final = _wait_until_settled(client, run_id)

    assert final["error_count"] == 1
    assert final["success_count"] == 3


def test_an_unreadable_preset_fails_its_whole_batch_without_stopping_the_next_one(
    client, sources, preset_path, output_dir, tmp_path
):
    corrupt_preset = tmp_path / "casse.json"
    corrupt_preset.write_text("{ pas du json", encoding="utf-8")
    second_output = tmp_path / "sortie-2"
    second_output.mkdir()

    run_id = _start(
        client,
        [
            _batch(sources, corrupt_preset, output_dir),
            _batch(sources, preset_path, second_output),
        ],
    ).json()["run_id"]
    final = _wait_until_settled(client, run_id)

    assert final["error_count"] == 3
    assert final["success_count"] == 3
    # One line per file, so the journal's own count still matches the gauges.
    assert [entry["ok"] for entry in final["log"]] == [False, False, False, True, True, True]
    assert list(output_dir.iterdir()) == []
    assert len(list(second_output.iterdir())) == 3


def test_a_preset_referencing_unknown_rows_fails_its_batch_clearly(
    client, sources, output_dir, tmp_path
):
    stale_preset = tmp_path / "ancien.json"
    stale_preset.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "steps": [{"step_identifier": "exposure", "thumbnail_identifier": "plus1", "parameters": {}}],
            }
        ),
        encoding="utf-8",
    )

    run_id = _start(client, [_batch(sources, stale_preset, output_dir)]).json()["run_id"]
    final = _wait_until_settled(client, run_id)

    assert final["error_count"] == 3
    assert "configuration actuelle" in final["log"][0]["message"]


# --- Stop ---


def test_stop_ends_the_run_and_keeps_progress_and_journal_readable(
    client, sources, preset_path, output_dir, slow_processing
):
    run_id = _start(client, [_batch(sources * 10, preset_path, output_dir)]).json()["run_id"]
    assert slow_processing.wait(SETTLE_TIMEOUT_S), "the run never started processing"

    stopped = client.post(f"/batch/runs/{run_id}/stop")
    assert stopped.status_code == 200

    final = _wait_until_settled(client, run_id)
    assert final["state"] == "stopped"
    assert 0 < final["done"] < final["total"]
    # Whatever it got through is still accounted for -- the journal survives the stop.
    assert len(final["log"]) == final["done"]


def test_stopping_an_unknown_run_is_a_404(client):
    assert client.post("/batch/runs/inconnu/stop").status_code == 404


def test_polling_an_unknown_run_is_a_404(client):
    assert client.get("/batch/runs/inconnu").status_code == 404


# --- Validation, before a single pixel is decoded ---


def test_a_run_without_any_batch_is_rejected(client):
    response = _start(client, [])
    assert response.status_code == 400
    assert response.json()["detail"]["category"] == "invalid_batch"


def test_a_batch_without_any_file_is_rejected_and_points_at_it(client, preset_path, output_dir):
    response = _start(client, [_batch([], preset_path, output_dir)])
    assert response.status_code == 400
    assert response.json()["detail"]["batch_index"] == 0


def test_a_missing_preset_file_is_rejected(client, sources, output_dir, tmp_path):
    response = _start(client, [_batch(sources, tmp_path / "absent.json", output_dir)])
    assert response.status_code == 400
    assert "preset" in response.json()["detail"]["message"].lower()


def test_a_missing_output_directory_is_rejected(client, sources, preset_path, tmp_path):
    response = _start(client, [_batch(sources, preset_path, tmp_path / "absent")])
    assert response.status_code == 400
    assert "sortie" in response.json()["detail"]["message"].lower()


def test_a_second_run_is_refused_while_one_is_still_going(
    client, sources, preset_path, output_dir, slow_processing
):
    first = _start(client, [_batch(sources * 20, preset_path, output_dir)])
    assert first.status_code == 200
    assert slow_processing.wait(SETTLE_TIMEOUT_S), "the run never started processing"

    second = _start(client, [_batch(sources, preset_path, output_dir)])
    assert second.status_code == 409
    assert second.json()["detail"]["category"] == "batch_already_running"

    client.post(f"/batch/runs/{first.json()['run_id']}/stop")
    _wait_until_settled(client, first.json()["run_id"])


def test_a_new_run_is_accepted_once_the_previous_one_finished(client, sources, preset_path, output_dir):
    first = _start(client, [_batch(sources[:1], preset_path, output_dir)])
    _wait_until_settled(client, first.json()["run_id"])

    second = _start(client, [_batch(sources[:1], preset_path, output_dir)])
    assert second.status_code == 200
    _wait_until_settled(client, second.json()["run_id"])


# --- Native dialogs ---


def test_batch_files_dialog_returns_every_chosen_path(client, monkeypatch, sources):
    monkeypatch.setattr(
        api_app.filedialog, "askopenfilenames", lambda **kwargs: tuple(str(path) for path in sources)
    )
    response = client.get("/dialogs/select-batch-files")
    assert response.status_code == 200
    assert response.json() == {"paths": [str(path) for path in sources]}


def test_batch_files_dialog_returns_an_empty_list_when_cancelled(client, monkeypatch):
    monkeypatch.setattr(api_app.filedialog, "askopenfilenames", lambda **kwargs: ())
    assert client.get("/dialogs/select-batch-files").json() == {"paths": []}


def test_batch_files_dialog_uses_the_same_filters_as_opening_a_photo(client, monkeypatch):
    captured: dict = {}

    def fake_ask(**kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr(api_app.filedialog, "askopenfilenames", fake_ask)
    client.get("/dialogs/select-batch-files")

    assert captured["filetypes"] == api_app.IMAGE_FILE_TYPES


def test_batch_output_directory_dialog_returns_the_chosen_directory(client, monkeypatch, output_dir):
    monkeypatch.setattr(api_app.filedialog, "askdirectory", lambda **kwargs: str(output_dir))
    assert client.get("/dialogs/select-batch-output-directory").json() == {"path": str(output_dir)}


def test_batch_output_directory_dialog_returns_null_when_cancelled(client, monkeypatch):
    monkeypatch.setattr(api_app.filedialog, "askdirectory", lambda **kwargs: "")
    assert client.get("/dialogs/select-batch-output-directory").json() == {"path": None}
