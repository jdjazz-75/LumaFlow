# LumaFlow v1.0 (2026-09-24)
"""LaMa (Suvorov et al. 2021, "Resolution-robust Large Mask Inpainting with Fourier Convolutions",
WACV 2022) inference backend -- the fill engine `engine.py`'s `_solve_roi` calls into as of the
LaMa pivot (specs/100-addon-object-removal-v1/research.md R3). This module owns exactly two things:
loading the pretrained TorchScript checkpoint once per process, and the resize-down / mod-8-pad /
infer / unpad / resize-back numeric round trip around one inference call. Region-of-interest
cropping, clustering and the feathered composite all stay in `engine.py`, unchanged from the
PatchMatch era -- none of that was specific to the fill algorithm.

The checkpoint (`big-lama.pt`, ~200 Mo) is the same public TorchScript export the
`simple-lama-inpainting` PyPI package uses (github.com/enesmsahin/simple-lama-inpainting) --
reusing its release asset avoids re-exporting a checkpoint ourselves, but that package itself is
NOT a dependency (it pins `numpy<2.0`, incompatible with this project's numpy 2.4.2 -- verified in
session). It downloads once, lazily, into torch's own default hub cache
(`~/.cache/torch/hub/checkpoints/`, never inside this repo) and is never committed (same convention
as the RAW sample files -- see memory `raw-sample-files-location`).
"""

from __future__ import annotations

import os
import threading

import numpy
import torch
from PIL import Image as PILImage

_MODEL_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
_MODEL_FILENAME = "big-lama.pt"
_PAD_MODULO = 8

_model_lock = threading.Lock()
_model: torch.jit.ScriptModule | None = None
_device: torch.device | None = None


def _resolve_device() -> torch.device:
    global _device
    if _device is None:
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return _device


def _model_path() -> str:
    hub_dir = torch.hub.get_dir()
    model_dir = os.path.join(hub_dir, "checkpoints")
    os.makedirs(model_dir, exist_ok=True)
    return os.path.join(model_dir, _MODEL_FILENAME)


def _get_model() -> torch.jit.ScriptModule:
    """Lazy process-wide singleton -- the FastAPI server is a long-lived process (same pattern as
    `WORKFLOW_CONFIG`), so this loads (and downloads, if needed) at most once per run, not once per
    request. Guarded by a lock since FastAPI's sync endpoints run on a threadpool."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            path = _model_path()
            if not os.path.exists(path):
                torch.hub.download_url_to_file(_MODEL_URL, path, None, progress=False)
            device = _resolve_device()
            model = torch.jit.load(path, map_location=device)
            model.eval()
            model.to(device)
            _model = model
    return _model


def warmup() -> None:
    """Loads (downloading the checkpoint first if needed) synchronously -- call from a background
    thread at server startup so the first real "Appliquer" doesn't pay the download/JIT-load cost.
    Any failure here (e.g. no network on first run) is swallowed; the next real `run()` call will
    retry and surface the error to that request instead of crashing the server at startup."""
    try:
        _get_model()
    except Exception:
        pass


def _ceil_modulo(value: int, modulo: int) -> int:
    return value if value % modulo == 0 else (value // modulo + 1) * modulo


def _pad_to_modulo(array: numpy.ndarray, modulo: int) -> numpy.ndarray:
    height, width = array.shape[:2]
    out_h, out_w = _ceil_modulo(height, modulo), _ceil_modulo(width, modulo)
    pad_spec = [(0, out_h - height), (0, out_w - width)] + [(0, 0)] * (array.ndim - 2)
    return numpy.pad(array, pad_spec, mode="symmetric")


def _resize_long_edge(array: numpy.ndarray, target_long_edge: int, resample: int) -> numpy.ndarray:
    """Downscales (never upscales) so the longer side is at most `target_long_edge`, preserving
    aspect ratio. `array` is uint8, `(H, W, 3)` or `(H, W)`."""
    height, width = array.shape[:2]
    long_edge = max(height, width)
    if long_edge <= target_long_edge:
        return array
    scale = target_long_edge / long_edge
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))  # PIL wants (w, h)
    mode = "RGB" if array.ndim == 3 else "L"
    return numpy.asarray(PILImage.fromarray(array, mode=mode).resize(new_size, resample))


def run(roi_image: numpy.ndarray, roi_hole: numpy.ndarray, target_long_edge: int) -> numpy.ndarray:
    """`roi_image`: float32 `(H, W, 3)` in `[0, 255]`. `roi_hole`: bool `(H, W)`, True = pixels to
    fill. Returns solved float32 `(H, W, 3)` in `[0, 255]`, same shape as `roi_image` -- the caller
    (`engine.py`'s `_solve_roi`) handles cropping the ROI out of the working image and compositing
    the result back via the existing feathered-alpha blend; this function owns only the
    resize-down / mod-8-pad / infer / unpad / resize-back numeric round trip.

    Resizing to `target_long_edge` before inference (rather than running LaMa at the ROI's native
    resolution) is what keeps inference cost roughly constant regardless of the source photo's
    resolution -- a 12MP and a 24MP photo produce ROIs whose native size differs, but the network
    only ever sees a capped-size crop either way. Uses PIL for both resize steps, not cv2, to avoid
    adding a second new dependency on top of torch."""
    native_shape = roi_image.shape[:2]

    uint8_image = numpy.clip(numpy.rint(roi_image), 0, 255).astype(numpy.uint8)
    uint8_hole = (roi_hole.astype(numpy.uint8) * 255)

    small_image = _resize_long_edge(uint8_image, target_long_edge, PILImage.BICUBIC)
    small_hole = _resize_long_edge(uint8_hole, target_long_edge, PILImage.NEAREST) > 127

    padded_image = _pad_to_modulo(small_image, _PAD_MODULO)
    padded_hole = _pad_to_modulo(small_hole, _PAD_MODULO)

    image_tensor = torch.from_numpy(
        numpy.transpose(padded_image, (2, 0, 1)).astype(numpy.float32) / 255.0
    ).unsqueeze(0)
    mask_tensor = torch.from_numpy(padded_hole.astype(numpy.float32)[None, ...]).unsqueeze(0)
    mask_tensor = (mask_tensor > 0).float()

    device = _resolve_device()
    model = _get_model()
    with torch.inference_mode():
        output = model(image_tensor.to(device), mask_tensor.to(device))
        result = output[0].permute(1, 2, 0).detach().cpu().numpy()
    result_uint8 = numpy.clip(result * 255.0, 0, 255).astype(numpy.uint8)
    result_uint8 = result_uint8[: small_image.shape[0], : small_image.shape[1]]

    if result_uint8.shape[:2] != native_shape:
        result_uint8 = numpy.asarray(
            PILImage.fromarray(result_uint8, mode="RGB").resize(
                (native_shape[1], native_shape[0]), PILImage.BICUBIC
            )
        )
    return result_uint8.astype(numpy.float32)
