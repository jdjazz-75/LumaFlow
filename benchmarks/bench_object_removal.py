"""Harnais de mesure du moteur d'inpainting (feature 100, addon Suppression d'objets).

Depuis le pivot LaMa (specs/100-addon-object-removal-v1/research.md R3), ce script mesure le
pipeline ROI-recadree-puis-LaMa (le recadrage/clustering/composite de `engine.py` est inchange,
seul le remplissage a change). Le premier appel de la session paie le chargement du modele
(telechargement au tout premier lancement + `torch.jit.load`, ~1.3s mesure une fois le fichier
present sur disque) -- c'est exactement pourquoi `lama_backend.warmup()` tourne en tache de fond au
demarrage du serveur API, plutot que de laisser ce cout retomber sur le premier "Appliquer" reel.
`--reps 3` (le defaut) absorbe ce cout dans le minimum des repetitions comme n'importe quel autre
bruit de mesure.

Note memoire : `tracemalloc` ne voit que les allocations gerees par l'allocateur Python (numpy) --
les tenseurs torch passent par l'allocateur C++ de torch et n'apparaissent PAS dans `peak_mb`
ci-dessous ; ce chiffre sous-estime donc la memoire reelle du process depuis le pivot LaMa (a la
difference de l'ere PatchMatch, ou tout etait numpy).

Meme convention que `bench_pipeline.py` : les durees sont des `min` sur N repetitions, jamais des
moyennes (bruit machine ~40%, voir memoire perf-measurement-noise-floor).

Usage :
    python benchmarks/bench_object_removal.py speed             # cas de la table GO du plan
    python benchmarks/bench_object_removal.py quality            # Q1 (couleur), Q3 (determinisme), Q4 (bit-identique)
    python benchmarks/bench_object_removal.py speed --reps 3
    python benchmarks/bench_object_removal.py --json avant.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

import numpy

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lumaflow.addons.inpainting import inpaint_regions  # noqa: E402


def _textured_image(height: int, width: int, seed: int = 0) -> numpy.ndarray:
    """A more realistic synthetic photo than a pure analytic gradient: several octaves of
    band-limited noise (so local patches vary richly, the way real photo texture does) plus a
    MILD gradient (so global position still matters a little, without swamping local texture the
    way a single strong linear gradient does -- see research.md's note on the pure-gradient
    fixture's pathological interaction with SSD-only patch matching)."""
    rng = numpy.random.default_rng(seed)
    base = numpy.zeros((height, width), dtype=numpy.float32)
    scale = 1
    amplitude = 60.0
    while scale < max(height, width):
        h, w = max(1, height // scale), max(1, width // scale)
        octave = rng.normal(0, amplitude, size=(h, w)).astype(numpy.float32)
        octave_img = numpy.asarray(
            __import__("PIL.Image", fromlist=["Image"]).fromarray(
                numpy.clip(octave + 128, 0, 255).astype(numpy.uint8)
            ).resize((width, height), resample=0)
        ).astype(numpy.float32) - 128.0
        base += octave_img
        amplitude *= 0.55
        scale *= 2
    mild_gradient = numpy.linspace(-25, 25, width, dtype=numpy.float32)[None, :]
    gray = numpy.clip(140 + base + mild_gradient, 0, 255)
    image = numpy.stack([gray, gray * 0.92 + 12, gray * 1.05 - 8], axis=-1)
    return numpy.clip(image, 0, 255).astype(numpy.uint8)


def _disc_zone(height: int, width: int, area_fraction: float, cx_frac: float = 0.5, cy_frac: float = 0.5):
    radius = int(round(((area_fraction * height * width) / numpy.pi) ** 0.5))
    cx, cy = cx_frac * width, cy_frac * height
    n = 24
    angles = numpy.linspace(0, 2 * numpy.pi, n, endpoint=False)
    points = [((cx + radius * numpy.cos(a)) / width, (cy + radius * numpy.sin(a)) / height) for a in angles]
    yy, xx = numpy.mgrid[0:height, 0:width]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= radius * radius
    return points, mask


def _min_time(fn, reps: int) -> float:
    best = float("inf")
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


# Cibles revisees pour le moteur LaMa (research.md R3), avec une marge d'environ 2x sur le minimum
# mesure a chaud (modele deja charge) sur cette machine -- le recadrage ROI garde le cout de
# l'inference quasi constant quelle que soit la resolution de la photo source (12MP et 24MP ne
# different quasiment plus), a la difference du budget PatchMatch d'origine qui croissait avec la
# resolution. Mesures a chaud observees (reps=3) : 480px/2%=0.37s, 480px/8%=1.27s,
# 12MP/2%=3.34s, 12MP/8%=3.86s, 24MP/8%=4.93s.
_SPEED_CASES = [
    # (label, height, width, area_fraction, target_seconds)
    ("480px, trou 2%", 320, 480, 0.02, 0.8),
    ("480px, trou 8%", 320, 480, 0.08, 2.5),
    ("12MP, trou 2%", 3000, 4000, 0.02, 6.0),
    ("12MP, trou 8%", 3000, 4000, 0.08, 8.0),
    ("24MP, trou 8%", 4000, 6000, 0.08, 10.0),
]


def cmd_speed(reps: int, out: dict) -> bool:
    all_ok = True
    for label, height, width, area_fraction, target in _SPEED_CASES:
        image = _textured_image(height, width, seed=1)
        points, mask = _disc_zone(height, width, area_fraction)
        image[mask] = [255, 0, 255]
        tracemalloc.start()

        def run():
            return inpaint_regions(image, [points], dilation_pct=0.5, feather_pct=0.3, variant=0)

        elapsed = _min_time(run, reps)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak / (1024 * 1024)
        ok = elapsed <= target
        all_ok = all_ok and ok
        verdict = "OK" if ok else "DEPASSE"
        print(f"{label:20s} elapsed={elapsed:7.2f}s  cible<={target:5.1f}s  pic_memoire={peak_mb:7.1f}Mo  [{verdict}]")
        out.setdefault("speed", {})[label] = {"elapsed_s": elapsed, "target_s": target, "peak_mb": peak_mb, "ok": ok}
    return all_ok


def cmd_quality(reps: int, out: dict) -> bool:
    all_ok = True
    height, width = 400, 600
    image = _textured_image(height, width, seed=2)
    points, mask = _disc_zone(height, width, 0.05)
    magenta = image.copy()
    magenta[mask] = [255, 0, 255]

    result0 = inpaint_regions(magenta, [points], dilation_pct=0.5, feather_pct=0.3, variant=0)
    result0b = inpaint_regions(magenta, [points], dilation_pct=0.5, feather_pct=0.3, variant=0)
    result1 = inpaint_regions(magenta, [points], dilation_pct=0.5, feather_pct=0.3, variant=1)

    # Q1: no magenta left, distribution close to the surrounding ring.
    inside = result0[mask].astype(numpy.float32)
    dist = numpy.sqrt(((inside - numpy.array([255, 0, 255])) ** 2).sum(axis=1))
    q1 = bool(numpy.all(dist > 60))
    print(f"Q1 (plus de magenta dans la zone)            : {'OK' if q1 else 'ECHEC'} (min dist={dist.min():.1f})")

    # Q3: determinism.
    q3a = numpy.array_equal(result0, result0b)
    q3b = not numpy.array_equal(result0[mask], result1[mask])
    print(f"Q3a (meme variant -> meme resultat)          : {'OK' if q3a else 'ECHEC'}")
    print(f"Q3b (variant different -> resultat different): {'OK' if q3b else 'ECHEC'}")

    # Q4: bit-identical strictly outside the influence region (a generous ring well beyond
    # dilation+feather so this check is unambiguous regardless of their exact values).
    ys, xs = numpy.nonzero(mask)
    pad = int(round(0.06 * min(height, width))) + 20
    outer = numpy.ones((height, width), dtype=bool)
    outer[max(0, ys.min() - pad): ys.max() + pad, max(0, xs.min() - pad): xs.max() + pad] = False
    q4 = bool(numpy.array_equal(result0[outer], magenta[outer]))
    print(f"Q4 (bit-identique loin de la zone)           : {'OK' if q4 else 'ECHEC'}")

    ok = q1 and q3a and q3b and q4
    out["quality"] = {"q1": q1, "q3a": q3a, "q3b": q3b, "q4": q4}
    all_ok = all_ok and ok
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="all", choices=["all", "speed", "quality"])
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--json", type=str, default=None)
    args = parser.parse_args()

    out: dict = {}
    ok = True
    if args.command in ("all", "speed"):
        ok = cmd_speed(args.reps, out) and ok
    if args.command in ("all", "quality"):
        ok = cmd_quality(args.reps, out) and ok

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")

    print()
    print("VERDICT GLOBAL:", "GO" if ok else "A REEXAMINER (voir DEPASSE/ECHEC ci-dessus)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
