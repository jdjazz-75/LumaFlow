# LumaFlow v1.0 (2026-08-25)
# Orchestration des traitements par lot : registre des executions en memoire, boucle
# sequentielle (lot par lot, image par image), progression, journal et demande d'arret.
"""Batch run orchestration (feature: traitement par lot, 2026-08-25).

The layer between the FastAPI endpoints (`lumaflow.api.app`) and the pure per-image engine
(`lumaflow.engine.batch`): resolves each batch's recipe into a pipeline through the very same
`build_pipeline_from_recipe` the interactive "Ouvrir une recette" path uses, then walks every file
of every batch in order, recording progress and one journal line per image.

Three deliberate choices:

- **Its own single-thread executor**, NOT app.py's `_DIALOG_EXECUTOR` and not FastAPI's
  `BackgroundTasks`. Sharing the dialog executor would freeze every native file dialog in the app
  for the whole duration of a run (minutes on a list of RAW files), and BackgroundTasks is tied to
  the lifetime of one request, which a run deliberately outlives -- the batch window can be closed
  and reopened while it keeps going.
- **One run at a time**, process-wide. Two concurrent full-resolution runs would compete for RAM
  and make the global percentage meaningless; `start_run` refuses instead (BatchAlreadyRunning).
- **Sequential**, one image after another. A batch has no latency requirement, and a deterministic
  journal order is worth more here than wall-clock time.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lumaflow.api.session import RecipeAddonsMissing, build_pipeline_from_recipe
from lumaflow.engine.batch import process_one, resolve_output_path, unique_output_path
from lumaflow.engine.pipeline import Pipeline, PipelineStep, StepParameters
from lumaflow.persistence.preferences import default_preferences_path, load_preferences
from lumaflow.persistence.recipe import RecipeIOError, RecipeValidationError, load_recipe


@dataclass(frozen=True)
class BatchSpec:
    """One user-defined "lot": a list of source images, the preset to apply to all of them, and
    where the results go."""

    files: tuple[Path, ...]
    preset_path: Path
    output_dir: Path


@dataclass(frozen=True)
class LogEntry:
    """One journal line -- always one per source file attempted, success or failure, so the journal
    accounts for every file the run claims to have processed."""

    index: int  # 1-based, across the WHOLE run (all batches), matching `total`
    total: int
    batch_index: int  # 0-based position of the owning batch
    file_name: str
    output_name: str
    ok: bool
    message: str


@dataclass
class BatchRun:
    id: str
    specs: tuple[BatchSpec, ...]
    batch_totals: tuple[int, ...]
    total: int
    jpeg_quality: int | None
    batch_done: list[int] = field(default_factory=list)
    done: int = 0
    success_count: int = 0
    error_count: int = 0
    state: str = "running"  # "running" | "stopped" | "finished"
    stop_requested: bool = False
    log: list[LogEntry] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class BatchAlreadyRunning(Exception):
    """A run is already in flight -- a second one is refused rather than queued or interleaved."""


class BatchValidationError(Exception):
    """A batch definition that cannot possibly succeed (no file, missing preset file, missing
    output directory) -- rejected up front rather than turned into one identical error line per
    image. `batch_index` is 0-based, or None when the whole submission is empty.

    `code` (i18n phase 4, 2026-09-03) distinguishes the 4 reasons machine-readably -- same
    convention as RecipeValidationError.reason / ImageIOError.category -- so the frontend catalog
    can translate the SPECIFIC cause instead of always falling back to this class's one French
    `message` (which stays the repli for any code the frontend catalog does not recognize)."""

    def __init__(self, message: str, code: str, batch_index: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.batch_index = batch_index


_RUNS: dict[str, BatchRun] = {}
_REGISTRY_LOCK = threading.Lock()
_ACTIVE_RUN_ID: str | None = None
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="batch-run")


def validate_specs(specs: list[BatchSpec]) -> None:
    """Everything checkable before a single pixel is decoded. Source files themselves are NOT
    checked for existence here -- one that vanished between selection and launch is a per-file
    error line (the batch keeps going), not a reason to refuse the whole run."""
    if not specs:
        raise BatchValidationError("Aucun lot à exécuter.", "no_batches")
    for index, spec in enumerate(specs):
        if not spec.files:
            raise BatchValidationError("Ce lot ne contient aucun fichier.", "empty_batch", index)
        if not spec.preset_path.is_file():
            raise BatchValidationError("Le preset de ce lot est introuvable.", "preset_not_found", index)
        if not spec.output_dir.is_dir():
            raise BatchValidationError("Le répertoire de sortie de ce lot est introuvable.", "output_dir_not_found", index)


def start_run(specs: list[BatchSpec]) -> BatchRun:
    """Validates, registers and schedules a run. Returns as soon as it is scheduled -- progress is
    read afterwards through `get_run`/`snapshot`."""
    validate_specs(specs)

    global _ACTIVE_RUN_ID
    with _REGISTRY_LOCK:
        if _ACTIVE_RUN_ID is not None:
            active = _RUNS.get(_ACTIVE_RUN_ID)
            if active is not None and active.state == "running":
                raise BatchAlreadyRunning("Un traitement par lot est déjà en cours.")
        batch_totals = tuple(len(spec.files) for spec in specs)
        run = BatchRun(
            id=uuid.uuid4().hex,
            specs=tuple(specs),
            batch_totals=batch_totals,
            total=sum(batch_totals),
            # Read once, at launch: changing Préférences > Général mid-run must not make the second
            # half of a lot come out at a different quality than the first.
            jpeg_quality=_export_jpeg_quality(),
            batch_done=[0] * len(specs),
        )
        _RUNS[run.id] = run
        _ACTIVE_RUN_ID = run.id

    _EXECUTOR.submit(_execute, run)
    return run


def get_run(run_id: str) -> BatchRun | None:
    with _REGISTRY_LOCK:
        return _RUNS.get(run_id)


def request_stop(run_id: str) -> bool:
    """Asks a run to stop after the image currently being processed. Returns False for an unknown
    run id. Stopping an already-finished run is a no-op that still returns True -- the caller only
    cares that the id was real."""
    run = get_run(run_id)
    if run is None:
        return False
    with run.lock:
        if run.state == "running":
            run.stop_requested = True
    return True


def snapshot(run: BatchRun) -> dict:
    """A consistent, plain-data copy of everything the batch window displays, taken under the run's
    own lock so a poll can never observe `done` and `log` from two different moments."""
    with run.lock:
        return {
            "run_id": run.id,
            "state": run.state,
            "total": run.total,
            "done": run.done,
            "success_count": run.success_count,
            "error_count": run.error_count,
            "global_percent": _percent(run.done, run.total),
            "batches": [
                {
                    "total": total,
                    "done": done,
                    "percent": _percent(done, total),
                }
                for total, done in zip(run.batch_totals, run.batch_done)
            ],
            "log": [
                {
                    "index": entry.index,
                    "total": entry.total,
                    "batch_index": entry.batch_index,
                    "file_name": entry.file_name,
                    "output_name": entry.output_name,
                    "ok": entry.ok,
                    "message": entry.message,
                }
                for entry in run.log
            ],
        }


def _percent(done: int, total: int) -> int:
    return round(done * 100 / total) if total > 0 else 0


def _export_jpeg_quality() -> int | None:
    try:
        return load_preferences(default_preferences_path()).export_jpeg_quality
    except Exception:
        # A batch must not be blocked by an unreadable preferences file -- export_image falls back
        # to the source's own estimated quality (then FALLBACK_JPEG_QUALITY) when given None.
        return None


def _clone_pipeline(pipeline: Pipeline) -> Pipeline:
    """A per-image copy of the batch's pipeline, so a hypothetical addon writing into the parameter
    dict it is handed cannot contaminate the NEXT image of the same lot. Cheap (a few dataclasses,
    no pixels) next to a full-resolution render, and strictly safer than sharing one instance."""
    clone = Pipeline()
    for step in pipeline._steps:
        clone.add_step(
            PipelineStep(
                identifier=step.identifier,
                parameters=StepParameters(values=dict(step.parameters.values)),
                processor=step.processor,
            )
        )
    return clone


def _record(run: BatchRun, batch_index: int, file_name: str, output_name: str, ok: bool, message: str) -> None:
    with run.lock:
        run.done += 1
        run.batch_done[batch_index] += 1
        if ok:
            run.success_count += 1
        else:
            run.error_count += 1
        run.log.append(
            LogEntry(
                index=run.done,
                total=run.total,
                batch_index=batch_index,
                file_name=file_name,
                output_name=output_name,
                ok=ok,
                message=message,
            )
        )


def _stop_requested(run: BatchRun) -> bool:
    with run.lock:
        return run.stop_requested


def _execute(run: BatchRun) -> None:
    """The run itself. Never raises: the executor thread swallowing an exception would leave the
    window polling a run stuck at "running" forever, so the finally block always settles the state."""
    global _ACTIVE_RUN_ID
    try:
        for batch_index, spec in enumerate(run.specs):
            if _stop_requested(run):
                break

            pipeline, recipe_error = _resolve_batch_pipeline(spec)
            for source_path in spec.files:
                if _stop_requested(run):
                    break
                if recipe_error is not None:
                    # The preset could not be resolved: every file of THIS batch fails identically,
                    # and the run moves on to the next batch. Logging one line per file (rather
                    # than a single batch-level line) keeps the journal's own count consistent with
                    # the progress gauges, which count files.
                    _record(run, batch_index, source_path.name, "", False, recipe_error)
                    continue
                output_path = unique_output_path(
                    resolve_output_path(source_path, spec.preset_path, spec.output_dir, datetime.now())
                )
                outcome = process_one(
                    source_path,
                    _clone_pipeline(pipeline),
                    output_path,
                    jpeg_quality=run.jpeg_quality,
                )
                _record(
                    run,
                    batch_index,
                    source_path.name,
                    outcome.output_path.name if outcome.output_path is not None else "",
                    outcome.ok,
                    outcome.message,
                )
    finally:
        with run.lock:
            run.state = "stopped" if run.stop_requested else "finished"
        with _REGISTRY_LOCK:
            if _ACTIVE_RUN_ID == run.id:
                _ACTIVE_RUN_ID = None


def _resolve_batch_pipeline(spec: BatchSpec) -> tuple[Pipeline | None, str | None]:
    """Loads and resolves a batch's preset ONCE, not once per image. Returns (pipeline, None) on
    success, or (None, message) with a ready-to-display French reason -- the same three failure
    categories the interactive recipe loader distinguishes."""
    try:
        recipe = load_recipe(spec.preset_path)
    except (RecipeValidationError, RecipeIOError):
        return None, "Ce fichier de preset est illisible ou corrompu."
    try:
        build = build_pipeline_from_recipe(recipe)
    except RecipeAddonsMissing:
        return None, "Ce preset référence des étapes absentes de la configuration actuelle."
    except Exception:
        return None, "Ce preset n'a pas pu être préparé pour le traitement."
    return build.pipeline, None
