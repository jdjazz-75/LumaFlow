"""Harnais de mesure du pipeline LumaFlow -- A/B isole, avant/apres chaque phase d'optimisation.

Raison d'etre (PERF-ZOOM-RENDER-PLAN.md:233-264) : une modification bit-identique, verte sur toute
la suite, s'est deja revelee 3 a 5x PLUS LENTE en mesure isolee et a du etre annulee. Bit-identique
ne prouve pas plus rapide -- il faut mesurer, et aucun harnais versionne ne le faisait jusqu'ici.

Trois mesures independantes :

  clicks      Compte les appels a `step.processor` par ligne pendant une sequence de clics
              scenarisee (select_vignette). C'est la mesure structurelle : un clic ne devrait
              declencher qu'un seul replay du pipeline, pas trois.
  primitives  Chronometre les primitives privees de film.py sur un enchainement
              Film -> Bleach Bypass -> B&W, en pleine resolution.
  render      Chronometre render_full_resolution (export / Zoom) de bout en bout.

Toutes les durees sont des `min` sur N repetitions, jamais des moyennes : sous l'ordonnanceur
Windows la moyenne mesure surtout le bruit des autres processus, le minimum mesure le code.

Usage :
    python benchmarks/bench_pipeline.py                     # tout, tailles par defaut
    python benchmarks/bench_pipeline.py clicks
    python benchmarks/bench_pipeline.py primitives --size 3000x2000 --reps 3
    python benchmarks/bench_pipeline.py --image ../exemples/Horseshoe.jpg
    python benchmarks/bench_pipeline.py --json avant.json   # puis diff apres modification
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import numpy
from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lumaflow.api import session as S  # noqa: E402

# Les primitives chronometrees, dans l'ordre du pipeline de `_apply_parametric_grade`. Ce sont des
# fonctions PRIVEES : si l'une disparait lors d'un refactor, `_instrument` l'ignore silencieusement
# plutot que de faire echouer tout le harnais.
_FILM_PRIMITIVES = (
    "_rgb_to_hsl",
    "_apply_tone_curve",
    "_apply_global_saturation",
    "_apply_hsl_saturation_by_hue",
    "_apply_hsl_luminance_by_hue",
    "_apply_color_chrome_effect",
    "_apply_color_chrome_blue",
    "_apply_hsl_hue_rotation",
    "_hsl_to_rgb",
    "_apply_temperature_tint",
    "_apply_split_tone",
    "_apply_clarity_sharpness",
    "_apply_grain",
    "_apply_black_clip",
    "_box_blur",
    "_zone_weights",
)

# Enchainement de reference : une ligne Film, une ligne Bleach Bypass, une ligne B&W -- exactement
# le scenario "je selectionne une vignette Film puis une vignette Bleach Bypass" qui motive ce
# harnais. Les cles sont celles de film._GRADES, pas les libelles affiches.
_CHAINED_LOOKS = ("velvia_pro", "titanium", "acros_pro")


def _load_film_module():
    """Charge film.py comme le fait le loader d'addons : par chemin, sans enregistrement dans
    sys.modules (voir loader.py:89-93). Instrumenter le module importe normalement ne fonctionnerait
    pas -- ce n'est pas le meme objet que celui que le pipeline execute."""
    path = _REPO_ROOT / "lumaflow" / "addons" / "builtin" / "film.py"
    spec = importlib.util.spec_from_file_location("film_bench", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _instrument(module, names: tuple[str, ...]) -> tuple[collections.Counter, collections.Counter]:
    """Enveloppe chaque fonction nommee pour compter les appels et cumuler leur duree."""
    counts: collections.Counter = collections.Counter()
    times: collections.Counter = collections.Counter()

    def make(original: Callable, name: str) -> Callable:
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                times[name] += time.perf_counter() - start
                counts[name] += 1

        return wrapper

    for name in names:
        original = getattr(module, name, None)
        if original is None:
            continue
        setattr(module, name, make(original, name))
    return counts, times


def _gradient_image(width: int, height: int) -> numpy.ndarray:
    """Meme recette de degrade lineaire uint8 que tests/test_zoom_render_performance.py:74-82 (et
    dupliquee dans test_zoom_before_cache.py / test_step_render_cache.py) -- reprise ici pour que
    les chiffres du harnais soient comparables a ceux du test `perf` deja en place."""
    rows = numpy.linspace(0, 255, height, dtype=numpy.float32)[:, None]
    cols = numpy.linspace(0, 255, width, dtype=numpy.float32)[None, :]
    red = numpy.broadcast_to(rows, (height, width))
    green = numpy.broadcast_to(cols, (height, width))
    blue = (rows + cols) / 2.0
    return numpy.stack([red, green, numpy.broadcast_to(blue, (height, width))], axis=-1).astype(numpy.uint8)


def _noise_image(width: int, height: int, seed: int = 7) -> numpy.ndarray:
    """Un degrade lineaire ne couvre qu'une fraction du cercle des teintes, donc laisse la plupart
    des fenetres cosinus par teinte a zero et sous-estime le cout reel de _apply_hsl_*_by_hue. Le
    bruit uniforme les sollicite toutes -- c'est le pire cas honnete."""
    rng = numpy.random.default_rng(seed)
    return (rng.random((height, width, 3)) * 255).astype(numpy.uint8)


def _write_temp_png(image: numpy.ndarray) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="lumaflow-bench-"))
    path = directory / "bench.png"
    Image.fromarray(image, mode="RGB").save(path)
    return path


def _source_image(args: argparse.Namespace, width: int, height: int) -> numpy.ndarray:
    if args.image:
        with Image.open(args.image) as handle:
            return numpy.asarray(handle.convert("RGB"), dtype=numpy.uint8).copy()
    return _noise_image(width, height) if args.noise else _gradient_image(width, height)


# --------------------------------------------------------------------------------------------
# Mesure 1 : appels processeur par clic
# --------------------------------------------------------------------------------------------


def bench_clicks(args: argparse.Namespace) -> dict[str, Any]:
    """Compte les appels a `step.processor` de chaque ligne pendant une sequence de clics.

    Un clic devrait replayer le pipeline UNE fois. Avant optimisation, chaque ligne est appelee 3
    fois (`_working_row_input`, `refresh_workflow`, `_compute_vignette_states` replaient chacun
    tout le pipeline), plus une fois par vignette pour les lignes visibles.
    """
    width, height = args.size
    image = _source_image(args, width, height)
    path = _write_temp_png(image)

    session = S.Session(id="bench")
    S.open_image(session, path)

    counts: collections.Counter = collections.Counter()
    times: collections.Counter = collections.Counter()

    def make(original: Callable, identifier: str) -> Callable:
        def wrapper(img, params):
            start = time.perf_counter()
            try:
                return original(img, params)
            finally:
                times[identifier] += time.perf_counter() - start
                counts[identifier] += 1

        return wrapper

    for step in session.pipeline._steps:
        if step.processor is not None:
            step.processor = make(step.processor, step.identifier)

    identifiers = [step.identifier for step in session.pipeline._steps]
    index_of = {name: position for position, name in enumerate(identifiers)}

    # Le scenario exact decrit dans la demande : Film, puis Bleach Bypass, puis un second clic dans
    # Bleach Bypass (la ligne Film est alors INCHANGEE et ne devrait plus rien couter).
    scenario = [
        ("film", "Velvia", "clic Film=Velvia"),
        ("bleach_bypass", "Titanium", "clic BleachBypass=Titanium"),
        ("bleach_bypass", "Loki", "re-clic BleachBypass=Loki (Film inchange)"),
        ("bw", "Acros", "clic B&W=Acros"),
    ]

    print(f"\n=== appels processeur par clic ({width}x{height}, working_image <= 480px) ===")
    print(f"lignes : {identifiers}\n")

    results: list[dict[str, Any]] = []
    for row_identifier, preset, label in scenario:
        if row_identifier not in index_of:
            continue
        counts.clear()
        times.clear()
        start = time.perf_counter()
        S.select_vignette(session, index_of[row_identifier], preset)
        wall = time.perf_counter() - start

        total = sum(counts.values())
        print(f"{label:<44} wall={wall:.3f}s  appels={total}")
        for name in identifiers:
            if counts[name]:
                print(f"      {name:<16} x{counts[name]:<4} {times[name]:6.3f}s")
        print()
        results.append(
            {
                "label": label,
                "wall_seconds": round(wall, 4),
                "total_processor_calls": total,
                "per_row": {name: counts[name] for name in identifiers if counts[name]},
            }
        )
    return {"size": [width, height], "clicks": results}


# --------------------------------------------------------------------------------------------
# Mesure 2 : primitives de film.py
# --------------------------------------------------------------------------------------------


def bench_primitives(args: argparse.Namespace) -> dict[str, Any]:
    """Chronometre chaque primitive privee de film.py sur l'enchainement de reference."""
    width, height = args.size
    image = _source_image(args, width, height)
    film = _load_film_module()
    counts, times = _instrument(film, _FILM_PRIMITIVES)

    print(f"\n=== primitives film.py ({image.shape[1]}x{image.shape[0]}, min sur {args.reps} reps) ===")

    results: list[dict[str, Any]] = []
    for depth in range(1, len(_CHAINED_LOOKS) + 1):
        looks = _CHAINED_LOOKS[:depth]
        best = float("inf")
        best_counts: dict[str, int] = {}
        best_times: dict[str, float] = {}
        for _ in range(args.reps):
            counts.clear()
            times.clear()
            start = time.perf_counter()
            current = image
            for look in looks:
                current = film.film_look(current, {"look": look, "intensity": 1.0})
            elapsed = time.perf_counter() - start
            if elapsed < best:
                best = elapsed
                best_counts = dict(counts)
                best_times = dict(times)

        print(f"\n  {' -> '.join(looks)} : {best:.3f}s")
        for name, _ in sorted(best_times.items(), key=lambda item: -item[1])[:8]:
            print(f"      {name:<30} x{best_counts[name]:<4} {best_times[name]:6.3f}s")
        results.append(
            {
                "looks": list(looks),
                "seconds": round(best, 4),
                "primitives": {
                    name: {"calls": best_counts[name], "seconds": round(value, 4)}
                    for name, value in best_times.items()
                },
            }
        )
    print()
    return {"size": [image.shape[1], image.shape[0]], "chains": results}


# --------------------------------------------------------------------------------------------
# Mesure 3 : render_full_resolution (export / Zoom)
# --------------------------------------------------------------------------------------------


def bench_render(args: argparse.Namespace) -> dict[str, Any]:
    """Chronometre le rendu pleine resolution -- le chemin de l'export et du Zoom.

    Le cache de prefixe (`step_render_cache`) est vide explicitement entre les repetitions : on
    mesure le cout de calcul, pas l'efficacite du cache (mesuree, elle, par `clicks`).
    """
    width, height = args.size
    image = _source_image(args, width, height)
    path = _write_temp_png(image)

    session = S.Session(id="bench-render")
    S.open_image(session, path)
    identifiers = [step.identifier for step in session.pipeline._steps]
    index_of = {name: position for position, name in enumerate(identifiers)}

    for row_identifier, preset in (("film", "Velvia"), ("bleach_bypass", "Titanium")):
        if row_identifier in index_of:
            S.select_vignette(session, index_of[row_identifier], preset)

    best = float("inf")
    for _ in range(args.reps):
        with session._row_before_lock:
            session.step_render_cache = {}
        start = time.perf_counter()
        result = S.render_full_resolution(session)
        elapsed = time.perf_counter() - start
        best = min(best, elapsed)

    print(f"\n=== render_full_resolution ({width}x{height}, Film=Velvia + BB=Titanium) ===")
    print(f"  cache froid, min sur {args.reps} reps : {best:.3f}s  -> {result.shape}\n")
    return {"size": [width, height], "render_full_resolution_seconds": round(best, 4)}


# --------------------------------------------------------------------------------------------


def _parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x")
        return int(width), int(height)
    except ValueError:
        raise argparse.ArgumentTypeError(f"taille invalide '{value}' -- attendu LARGEURxHAUTEUR, ex. 1600x1200")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "mesures",
        nargs="*",
        default=["clicks", "primitives", "render"],
        choices=["clicks", "primitives", "render"],
        help="mesures a executer (defaut : toutes)",
    )
    parser.add_argument("--size", type=_parse_size, default=(1600, 1200), help="taille de l'image de synthese")
    parser.add_argument("--reps", type=int, default=8, help="repetitions ; on retient le min (defaut 8)")
    parser.add_argument("--image", type=Path, help="vraie photo a utiliser au lieu de l'image de synthese")
    parser.add_argument(
        "--noise",
        action="store_true",
        help="image de bruit uniforme au lieu d'un degrade -- sollicite toutes les fenetres de teinte",
    )
    parser.add_argument("--json", type=Path, help="ecrit les resultats en JSON (pour diff avant/apres)")
    args = parser.parse_args(argv)

    runners = {"clicks": bench_clicks, "primitives": bench_primitives, "render": bench_render}
    report: dict[str, Any] = {}
    for name in args.mesures:
        report[name] = runners[name](args)

    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"resultats ecrits dans {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
