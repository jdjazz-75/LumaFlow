# LumaFlow v1.0 (2026-08-25)
# Moteur de traitement par lot sans interface : nommage du fichier de sortie, application
# d'un pipeline deja construit a un fichier source, export du resultat.
"""Headless per-image batch processing (feature: traitement par lot, 2026-08-25).

Deliberately knows nothing about the workflow configuration, recipes or the addon index: it
takes an ALREADY-BUILT `Pipeline` and one source path, and returns an outcome. Building that
pipeline from a recipe is `lumaflow.api.batch_runs`' job (it needs the process-wide
WORKFLOW_CONFIG/ADDON_INDEX that live in `lumaflow.api.session`), which keeps this module in the
engine layer with the rest of the pure image machinery.

The contract that matters for a batch: **`process_one` never raises**. One unreadable file out of
200 must cost exactly one log line, not the whole run -- so every failure mode (missing file,
corrupted RAW, an addon blowing up mid-pipeline, a full disk) comes back as
`BatchItemOutcome(ok=False)` carrying a message already written in plain French, ready to be shown
in the batch window's journal without any further translation (unlike the interactive path, whose
raw messages are reformulated client-side by web/src/lib/errorMessages.ts).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lumaflow.engine.errors import ErrorCategory, ImageIOError
from lumaflow.engine.image_io import export_image, load_image, resolve_jpeg_export_params
from lumaflow.engine.pipeline import Pipeline, PipelineEngine


@dataclass(frozen=True)
class BatchItemOutcome:
    """One source file's fate. `output_path` is None whenever `ok` is False -- nothing was
    written. `message` is empty on success and a ready-to-display French sentence on failure."""

    source_path: Path
    output_path: Path | None
    ok: bool
    message: str = ""


# Timestamp format of an output file name: AA-MM-DD-HH-MM-SS (2-digit year first, so a directory
# listing sorted by name is also sorted chronologically per source/preset pair).
_TIMESTAMP_FORMAT = "%y-%m-%d-%H-%M-%S"


def output_extension(source_path: Path) -> str:
    """The extension a batch writes for `source_path`, "format deduced from the source": PNG stays
    PNG, everything else (JPEG, and every RAW format -- which cannot be written back) becomes JPEG.
    Extension-only, never opens the file, so an output name can be shown/logged even for a source
    that turns out to be unreadable."""
    return ".png" if source_path.suffix.lower() == ".png" else ".jpg"


def image_format_for(output_path: Path) -> str:
    """The PIL format name matching `output_path`'s own extension -- the counterpart of
    output_extension, kept next to it so the two can never drift apart."""
    return "PNG" if output_path.suffix.lower() == ".png" else "JPEG"


def resolve_output_path(source_path: Path, preset_path: Path, output_dir: Path, when: datetime) -> Path:
    """`<stem source>-<stem preset>-<AA-MM-DD-HH-MM-SS>.<ext>` (user's naming rule, 2026-08-25).

    The timestamp is what makes the name unique, so a batch never has to ask about overwriting an
    existing file: re-running the same list with the same preset a minute later writes a fresh set
    of files rather than replacing the previous one. Pure -- never touches the filesystem; see
    `unique_output_path` for the one case a second-granularity timestamp cannot separate."""
    stem = source_path.stem
    preset_stem = preset_path.stem
    timestamp = when.strftime(_TIMESTAMP_FORMAT)
    return output_dir / f"{stem}-{preset_stem}-{timestamp}{output_extension(source_path)}"


def unique_output_path(candidate: Path) -> Path:
    """`candidate` itself when free, else the same name with `-2`, `-3`... inserted before the
    extension.

    Safety net for the one collision a second-granularity timestamp cannot separate: the SAME
    source name, with the SAME preset, into the SAME directory, within the SAME second. Not
    theoretical -- measured on 2026-08-25, a 156-image run whose sources repeated wrote only 36
    distinct files, silently losing the rest. Reachable through the window as soon as two batches
    share a photo and an output directory. Nominal batches (distinct file names) never take this
    branch, so the requested naming rule is what the user actually sees.
    """
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while True:
        alternative = candidate.with_name(f"{stem}-{counter}{suffix}")
        if not alternative.exists():
            return alternative
        counter += 1


_IMAGE_IO_MESSAGES: dict[ErrorCategory, str] = {
    ErrorCategory.MISSING_FILE: "Fichier introuvable.",
    ErrorCategory.PERMISSION_DENIED: "Accès refusé à ce fichier ou dossier.",
    ErrorCategory.CORRUPTED_FILE: "Ce fichier image est corrompu ou illisible.",
    ErrorCategory.INVALID_PATH: "Chemin de destination invalide.",
    ErrorCategory.DISK_FULL: "Espace disque insuffisant pour écrire le résultat.",
    ErrorCategory.UNKNOWN: "Erreur inattendue lors de la lecture ou de l'écriture du fichier.",
}


def _image_io_message(exc: ImageIOError) -> str:
    """UNSUPPORTED_FORMAT and RAW_NOT_DECODABLE already carry a product-authored French sentence in
    `detail` (image_io.py), naming the offending format -- more informative than anything a generic
    per-category constant could say, so those are passed through as-is."""
    if exc.category in (ErrorCategory.UNSUPPORTED_FORMAT, ErrorCategory.RAW_NOT_DECODABLE) and exc.detail:
        return exc.detail
    return _IMAGE_IO_MESSAGES.get(exc.category, _IMAGE_IO_MESSAGES[ErrorCategory.UNKNOWN])


def process_one(
    source_path: Path,
    pipeline: Pipeline,
    output_path: Path,
    *,
    jpeg_quality: int | None = None,
) -> BatchItemOutcome:
    """Load -> run the pipeline at FULL resolution -> export. Never raises (see module docstring).

    Full resolution by construction: `PipelineEngine.run` is fed `image_session.original`, not the
    downscaled `working_image` the interactive filmstrip path uses (see
    lumaflow.api.session.Session.working_image) -- a batch has no preview to be fast for, only a
    final file to get right.
    """
    source_path = Path(source_path)
    output_path = Path(output_path)

    try:
        image_session = load_image(source_path)
    except ImageIOError as exc:
        return BatchItemOutcome(source_path, None, False, _image_io_message(exc))
    except Exception:
        return BatchItemOutcome(
            source_path, None, False, "Erreur inattendue lors de l'ouverture du fichier."
        )

    try:
        result = PipelineEngine().run(pipeline, image_session.original)
    except Exception:
        # PipelineEngine.run captures per-step exceptions into result.error; only a malformed
        # source array reaches this branch, which load_image already rules out. Guarded anyway --
        # this function's whole contract is that it never raises.
        return BatchItemOutcome(source_path, None, False, "Le traitement de cette image a échoué.")
    if result.error is not None:
        return BatchItemOutcome(
            source_path,
            None,
            False,
            f"Le traitement a échoué à l'étape « {result.error.step_identifier} ».",
        )

    quality, subsampling = resolve_jpeg_export_params(jpeg_quality, image_session.source)
    try:
        export_image(
            result.final,
            output_path,
            image_format_for(output_path),
            jpeg_quality=quality,
            jpeg_subsampling=subsampling,
        )
    except ImageIOError as exc:
        return BatchItemOutcome(source_path, None, False, _image_io_message(exc))
    except Exception:
        return BatchItemOutcome(
            source_path, None, False, "Erreur inattendue lors de l'écriture du fichier de sortie."
        )

    return BatchItemOutcome(source_path, output_path, True)
