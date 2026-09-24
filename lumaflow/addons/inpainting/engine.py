# LumaFlow v1.1 (2026-09-24)
"""LaMa-backed inpainting driver (feature 100, addon Suppression d'objets).

Public entry point: `inpaint_regions(image, zones, dilation_pct, feather_pct, variant)`. Everything
below it is private; `lumaflow/addons/builtin/object_removal.py` is the only caller. This module
owns zone rasterization, clustering, region-of-interest sizing and the final feathered composite;
`lama_backend.py` owns the actual fill (a pretrained LaMa network, see that module's docstring).

**Pivot from PatchMatch to LaMa (2026-09-24)**: the original multi-scale PatchMatch engine (Barnes
2009 / Wexler 2007, pure numpy) is documented in `specs/100-addon-object-removal-v1/research.md` R1
(two real bugs found and fixed) and R2 (a verified, structural quality ceiling on dense
self-similar fine texture -- flat/blocky fills even with a correct nearest-neighbour field). A
direct side-by-side comparison against LaMa (Suvorov et al. 2021) on real photos confirmed LaMa does
not share this ceiling. See R3 for the full pivot rationale, the dependency cost (PyTorch + a
downloaded model checkpoint) and the revised performance budget. The old `kernels.py`
(PatchMatch's numpy primitives) is retired along with the pyramid/EM solve it backed; the
zone-rasterization/clustering/composite driver below is UNCHANGED, since none of it was specific to
PatchMatch.

Algorithm, per cluster of nearby zones (clusters let two far-apart zones each cost only their own
area, rather than one whole-image ROI -- see `_cluster_boxes`):

1. Rasterize the cluster's own zones, dilate their union by `dilation_pct` (the "Marge" the user
   controls) -- this is the actual hole to fill (and the ONLY footprint ever composited back, see
   step 4).
2. Crop a region of interest around that hole with a generous context margin (grown further if the
   valid-source area turns out too small relative to the hole). Before solving, dilate the hole a
   little further by a few pixels, deterministically seeded by `variant`, to build a separate
   SOLVE-TIME hole -- LaMa is a deterministic feed-forward network with no natural per-call
   randomness, so "Autre proposition" works by asking it to treat a slightly larger area as unknown
   instead (see `_solve_roi`); the composite in step 4 still only ever touches the TRUE (unjittered)
   footprint.
3. If the hole still covers most of its own ROI even after growing it (`_FALLBACK_HOLE_FRACTION`),
   there is not enough real content left for ANY method to work from -- fall back to a cheap
   weighted "push-pull" diffusion (Gortler et al.), a smooth but textureless placeholder (FR-011's
   "visible degradation, not silent failure"). Otherwise, hand the ROI to LaMa.
4. Composite: only pixels within the dilated-and-feathered hole are ever touched; a Gaussian-blurred
   alpha ramp blends the solved result back into the untouched original (FR-010/SC-002).
"""

from __future__ import annotations

from typing import Sequence

import numpy
from PIL import Image as PILImage, ImageDraw, ImageFilter

from lumaflow.addons.inpainting import lama_backend

# Used only to decide whether the ROI has "enough" real surrounding content (see the growth loop in
# `inpaint_regions`) -- not a search patch size like it was for PatchMatch, LaMa has no such notion.
_CONTEXT_PROBE_RADIUS = 2

# Long edge (pixels) a region of interest is downscaled to before LaMa inference, then upscaled back
# to the ROI's native resolution for compositing -- this is what keeps inference cost roughly
# constant regardless of the source photo's resolution (12MP vs 24MP barely matters once the ROI
# itself is capped). Tuned by the LaMa benchmark spike, research.md R3.
_LAMA_TARGET_LONG_EDGE = 512

# How far (pixels) "Autre proposition" is allowed to dilate the hole boundary FED TO THE SOLVER
# ONLY (never the true footprint used for the composite -- see the module docstring's step 2),
# seeded by `variant`. A crop-margin jitter was tried first and rejected: when a zone's region of
# interest already reaches the whole image (small photos, or a zone that is a large fraction of a
# small image), there is no room left to grow the margin, so that lever silently did nothing --
# dilating the SOLVE-TIME hole works regardless of how big the ROI already is, since it changes what
# the network is asked to treat as unknown, not how much surrounding context exists.
_VARIANT_HOLE_JITTER_PX = 6

# If, even after growing the region of interest, the hole still covers more than this fraction of
# its own ROI, there is not enough real content left to work from -- fall back to the plain
# push-pull diffusion alone (smooth but honest) rather than ask LaMa to hallucinate an ROI that is
# almost entirely mask (FR-011). LaMa is specifically designed for large masks, so this is looser
# than the PatchMatch-era threshold; still a defensive backstop for a near-whole-image zone.
_FALLBACK_HOLE_FRACTION = 0.9

_RNG_SALT = 0x4C554D41  # "LUMA" -- arbitrary constant, just keeps this engine's seed space distinct


def inpaint_regions(
    image: numpy.ndarray,
    zones: Sequence[Sequence[tuple[float, float]]],
    dilation_pct: float,
    feather_pct: float,
    variant: int,
) -> numpy.ndarray:
    """`image`: uint8 `(H, W, 3)`, never mutated. `zones`: a sequence of polygons, each a sequence
    of `(x, y)` fractions in `[0, 1]` (3+ points; the caller -- `object_removal.py` -- has already
    dropped degenerate zones). `dilation_pct`/`feather_pct`: percentages of `min(H, W)`. `variant`:
    an integer seed -- same inputs + same variant always produce the bit-identical output; changing
    only `variant` changes the result inside the holes, never outside them.

    Returns a NEW uint8 array. Pixels outside every zone's dilated-and-feathered footprint are
    copied from `image` unchanged (verified bit-identical by
    `tests/test_addon_object_removal.py`)."""
    if image.ndim != 3 or image.shape[2] != 3 or not zones:
        return image
    height, width = image.shape[:2]
    min_side = min(height, width)
    dilation_px = max(0, int(round(dilation_pct / 100.0 * min_side)))
    feather_px = max(0.0, feather_pct / 100.0 * min_side)

    boxes, masks = _zone_bboxes((height, width), zones, dilation_px)
    if not boxes:
        return image

    feather_radius = int(numpy.ceil(feather_px)) + 1
    gap = max(8, dilation_px + feather_radius + 4)
    groups = _cluster_boxes(boxes, gap)

    output = image.astype(numpy.float32, copy=True)
    for group_index, member_indices in enumerate(groups):
        cluster_hole_full = numpy.zeros((height, width), dtype=bool)
        y0 = min(boxes[i][0] for i in member_indices)
        y1 = max(boxes[i][1] for i in member_indices)
        x0 = min(boxes[i][2] for i in member_indices)
        x1 = max(boxes[i][3] for i in member_indices)
        for i in member_indices:
            by0, by1, bx0, bx1 = boxes[i]
            cluster_hole_full[by0:by1, bx0:bx1] |= masks[i]

        base_margin = max(
            0.75 * max(y1 - y0, x1 - x0), 0.04 * min_side, 8 * (2 * _CONTEXT_PROBE_RADIUS + 1)
        )
        margin = int(round(base_margin))
        ry0 = ry1 = rx0 = rx1 = 0
        roi_hole = None
        for _attempt in range(4):
            ry0, ry1 = max(0, y0 - margin), min(height, y1 + margin)
            rx0, rx1 = max(0, x0 - margin), min(width, x1 + margin)
            roi_hole = cluster_hole_full[ry0:ry1, rx0:rx1]
            hole_area = int(numpy.count_nonzero(roi_hole))
            valid_source_area = int(numpy.count_nonzero(~_dilate_bool(roi_hole, _CONTEXT_PROBE_RADIUS)))
            whole_image_reached = ry0 == 0 and rx0 == 0 and ry1 == height and rx1 == width
            if valid_source_area >= 3 * max(hole_area, 1) or whole_image_reached:
                break
            margin *= 2

        roi_image = output[ry0:ry1, rx0:rx1]
        hole_area = int(numpy.count_nonzero(roi_hole))
        roi_area = max(roi_hole.size, 1)

        rng = numpy.random.default_rng(numpy.random.SeedSequence([int(variant) & 0xFFFFFFFF, group_index, _RNG_SALT]))
        jitter_px = int(rng.integers(0, _VARIANT_HOLE_JITTER_PX + 1))
        solve_hole = _dilate_bool(roi_hole, jitter_px) if jitter_px else roi_hole

        if hole_area / roi_area > _FALLBACK_HOLE_FRACTION:
            solved = _push_pull_fill(roi_image, solve_hole)
        else:
            solved = _solve_roi(roi_image, solve_hole)

        alpha = _feather_alpha(roi_hole, feather_px)
        influence = _dilate_bool(roi_hole, feather_radius)
        region = output[ry0:ry1, rx0:rx1]
        blended = alpha[..., None] * solved + (1.0 - alpha[..., None]) * roi_image
        region[influence] = blended[influence]

    return numpy.clip(numpy.rint(output), 0, 255).astype(numpy.uint8)


def _solve_roi(roi_image: numpy.ndarray, roi_hole: numpy.ndarray) -> numpy.ndarray:
    """`roi_image`: float32 `(H, W, 3)` (already the live pixel values -- may include other,
    earlier-processed clusters' output where ROIs share context, which is fine, see
    `_cluster_boxes`'s docstring). Returns the solved float32 image at the ROI's own full
    resolution -- `lama_backend.run` handles the resize-down/pad/infer/upsize-back round trip."""
    if not numpy.any(roi_hole):
        return roi_image.astype(numpy.float32)
    return lama_backend.run(roi_image.astype(numpy.float32), roi_hole, _LAMA_TARGET_LONG_EDGE)


# ---------------------------------------------------------------------------
# Zone rasterization, dilation and clustering.
# ---------------------------------------------------------------------------


def _dilate_bool(mask: numpy.ndarray, radius: int) -> numpy.ndarray:
    """Square dilation by `radius` pixels -- separable (row pass, then column pass on the row
    result: `max` over a square window equals `max` over columns of the row-wise `max`), each pass
    a handful of shifted boolean-OR slices, O(N * radius) total. Simpler and no less correct for
    this addon's purpose than a polygon-outline-based circular dilation (the plan's original
    sketch) -- the difference between a square and a disc structuring element at these small radii
    (a few percent of the image's short side) is not visually distinguishable once feathered, a
    deliberate simplification recorded in research.md.

    NOT `PIL.ImageFilter.MaxFilter`, despite that being the obvious native-C first choice: measured
    in the Phase 0 spike, `MaxFilter`/`rankfilter` is a naive O(N * radius^2) rank filter with no
    separable fast path -- on a multi-megapixel region this dominated the ENTIRE addon's running
    time (research.md, R1) even at the small radii ("Marge") this addon actually uses. This
    numpy version outperforms it by roughly an order of magnitude at the sizes that matter here."""
    if radius <= 0:
        return mask
    height, width = mask.shape
    row_dilated = mask.copy()
    for d in range(1, radius + 1):
        row_dilated[:, d:] |= mask[:, : width - d]
        row_dilated[:, : width - d] |= mask[:, d:]
    out = row_dilated.copy()
    for d in range(1, radius + 1):
        out[d:, :] |= row_dilated[: height - d, :]
        out[: height - d, :] |= row_dilated[d:, :]
    return out


def _feather_alpha(hole: numpy.ndarray, feather_px: float) -> numpy.ndarray:
    """Gaussian-blurred ramp from the hard hole mask, floored at full opacity inside the hole
    itself (a blur alone can dip a thin hole's own center below 1.0) -- mirrors `light.py`'s
    `_polygon_mask` feathering intent, implemented via PIL's native (C-speed) blur instead of the
    hand-rolled `_box_blur` prefix-sum helper every other addon copies, since there is no cross-addon
    import constraint to work around here (this module is a normal package, not a `builtin/` addon
    file -- see the package docstring)."""
    if feather_px <= 0:
        return hole.astype(numpy.float32)
    image = PILImage.fromarray(hole.astype(numpy.uint8) * 255, mode="L")
    blurred = image.filter(ImageFilter.GaussianBlur(radius=feather_px))
    alpha = numpy.clip(numpy.asarray(blurred, dtype=numpy.float32) / 255.0, 0.0, 1.0)
    return numpy.maximum(alpha, hole.astype(numpy.float32))


def _zone_bboxes(
    shape: tuple[int, int], zones: Sequence[Sequence[tuple[float, float]]], dilation_px: int
) -> tuple[list[tuple[int, int, int, int]], list[numpy.ndarray]]:
    """Per-zone dilated mask (LOCAL to a small crop around the polygon, not full-image-sized -- see
    below) + its pixel bounding box `(y0, y1, x0, x1)` (half-open, ALREADY the dilated footprint's
    box). A zone whose dilated footprint is empty (should not happen for a validated 3+ vertex
    polygon, but a degenerate/near-zero-area one is possible) is silently dropped -- same "no shape
    at all" fallback `_read_mask`-style code in this codebase already uses.

    Rasterizes and dilates within a crop sized to the polygon's own bbox (+ `dilation_px` + a
    couple of pixels of slack), NOT the full `shape` canvas -- PIL's `MaxFilter` is a naive rank
    filter (cost grows with BOTH the canvas size AND the kernel size, not just the kernel), so
    running it over a multi-megapixel canvas for a dilation that only ever reaches a few percent of
    the image's short side outward from a small polygon was, empirically, the dominant cost of the
    whole addon at 12 MP+ (Phase 0 spike finding, see research.md) -- ~9s of an ~12s run, entirely
    inside this one call, before this fix. The returned mask/box pair is local; callers OR it into
    a full-size canvas via a cheap slice assignment instead."""
    height, width = shape
    boxes: list[tuple[int, int, int, int]] = []
    masks: list[numpy.ndarray] = []
    for points in zones:
        pixel_points = [(x * width, y * height) for x, y in points]
        xs_raw = [p[0] for p in pixel_points]
        ys_raw = [p[1] for p in pixel_points]
        pad = dilation_px + 2
        cx0 = max(0, int(numpy.floor(min(xs_raw))) - pad)
        cx1 = min(width, int(numpy.ceil(max(xs_raw))) + pad)
        cy0 = max(0, int(numpy.floor(min(ys_raw))) - pad)
        cy1 = min(height, int(numpy.ceil(max(ys_raw))) + pad)
        if cx1 <= cx0 or cy1 <= cy0:
            continue
        local_points = [(x - cx0, y - cy0) for x, y in pixel_points]
        canvas = PILImage.new("L", (cx1 - cx0, cy1 - cy0), 0)
        ImageDraw.Draw(canvas).polygon(local_points, fill=255)
        raw = numpy.asarray(canvas, dtype=numpy.uint8) > 127
        dilated = _dilate_bool(raw, dilation_px)
        ys, xs = numpy.nonzero(dilated)
        if ys.size == 0:
            continue
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        boxes.append((cy0 + y0, cy0 + y1, cx0 + x0, cx0 + x1))
        masks.append(dilated[y0:y1, x0:x1])
    return boxes, masks


def _cluster_boxes(boxes: list[tuple[int, int, int, int]], gap: int) -> list[list[int]]:
    """Union-find grouping of zone boxes: two zones merge into one cluster (one shared ROI, one
    shared solve) whenever their boxes come within `gap` pixels of each other -- `gap` is sized in
    `inpaint_regions` so that two SEPARATE clusters' influence regions (dilation + feather) can
    never touch, which is what lets each cluster read/write its own region-of-interest slice of
    `output` independently, in any order. `len(boxes) <= 8` (MAX_REMOVAL_ZONES), so the naive O(n^2)
    pairwise check is trivial."""
    n = len(boxes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    def close(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
        ay0, ay1, ax0, ax1 = a
        by0, by1, bx0, bx1 = b
        ay0, ax0, ay1, ax1 = ay0 - gap, ax0 - gap, ay1 + gap, ax1 + gap
        return not (ay1 <= by0 or by1 <= ay0 or ax1 <= bx0 or bx1 <= ax0)

    for i in range(n):
        for j in range(i + 1, n):
            if close(boxes[i], boxes[j]):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Push-pull diffusion -- the FR-011 near-whole-ROI-hole fallback.
# ---------------------------------------------------------------------------


def _push_pull_fill(image: numpy.ndarray, hole: numpy.ndarray) -> numpy.ndarray:
    """Gortler et al.'s push-pull: repeatedly weighted-downsample (push) a (value, coverage) pair
    down to a couple of pixels, then pull the coarse average back up, at each level preferring that
    level's OWN locally-known average over the coarser upsampled guess wherever one exists. A real
    (non-hole) pixel's weight is exactly 1 at the finest level, so it is returned EXACTLY unchanged
    (`imgs[0]/weights[0] == image` at every non-hole position) -- only hole pixels ever take the
    diffused value. Degenerate case (the ROI is entirely hole, e.g. a zone spanning the whole
    image): nothing to diffuse from, returns flat mid-grey rather than dividing by zero."""
    if not numpy.any(hole):
        return image.copy()
    if not numpy.any(~hole):
        return numpy.full_like(image, 128.0)

    weight = (~hole).astype(numpy.float32)
    shapes = [hole.shape]
    imgs = [image * weight[..., None]]
    weights = [weight]
    while min(shapes[-1]) > 2:
        h, w = shapes[-1]
        hp, wp = h + (h % 2), w + (w % 2)
        img = imgs[-1] if (hp, wp) == (h, w) else numpy.pad(imgs[-1], ((0, hp - h), (0, wp - w), (0, 0)), mode="edge")
        wgt = weights[-1] if (hp, wp) == (h, w) else numpy.pad(weights[-1], ((0, hp - h), (0, wp - w)), mode="edge")
        imgs.append(img.reshape(hp // 2, 2, wp // 2, 2, 3).sum(axis=(1, 3)))
        weights.append(wgt.reshape(hp // 2, 2, wp // 2, 2).sum(axis=(1, 3)))
        shapes.append((hp // 2, wp // 2))

    top_weight = weights[-1]
    if numpy.any(top_weight > 1e-6):
        filled = numpy.where(
            (top_weight > 1e-6)[..., None], imgs[-1] / numpy.maximum(top_weight, 1e-6)[..., None], 0.0
        )
    else:
        filled = numpy.full_like(imgs[-1], image.reshape(-1, 3)[~hole.reshape(-1)].mean(axis=0))

    for level in range(len(shapes) - 2, -1, -1):
        target_h, target_w = shapes[level]
        upsampled = numpy.repeat(numpy.repeat(filled, 2, axis=0), 2, axis=1)[:target_h, :target_w]
        known = weights[level] > 1e-6
        local = imgs[level] / numpy.maximum(weights[level], 1e-6)[..., None]
        filled = numpy.where(known[..., None], local, upsampled)
    return filled
