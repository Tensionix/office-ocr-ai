# imageops.py
# Deterministic CV stages for the preprocess pipeline. Pure functions: same
# input array + same params -> same output. No globals, no I/O side effects.
# These are the geometry/photometric fixes; character disambiguation is NOT here.
# EN comments only. UTF-8 without BOM.
#
# Uses OpenCV when available; falls back to PIL/NumPy for basic CPU operation.

from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    import cv2
except Exception:  # pragma: no cover - depends on local runtime packaging.
    cv2 = None


def preclean(
    img: np.ndarray,
    denoise: str = "weak",
    source_format: str = "jpeg",
    intent: str = "text",
    contrast_mode: str = "auto",
    unsharp_mode: str = "auto",
) -> np.ndarray:
    """CPU photometric cleanup for compressed scans before OCR/SR.

    This removes small JPEG speckles, stretches contrast, and sharpens glyph
    edges. It is intentionally deterministic and available without OpenCV.
    """
    if intent == "image":
        return img

    level = str(denoise or "none").strip().lower()
    fmt = str(source_format or "jpeg").strip().lower()
    pil = ImageOps.grayscale(_array_to_pil(img))

    if level in {"weak", "strong"} or fmt in {"jpg", "jpeg"}:
        pil = pil.filter(ImageFilter.MedianFilter(3))
    if level == "strong":
        pil = pil.filter(ImageFilter.MedianFilter(3))

    cutoff = 0.5 if level != "strong" else 1.0
    pil = ImageOps.autocontrast(pil, cutoff=cutoff)

    contrast_key = str(contrast_mode or "auto").strip().lower()
    if contrast_key == "auto":
        contrast = {
            "none": 1.10,
            "weak": 1.22,
            "strong": 1.34,
        }.get(level, 1.22)
    else:
        contrast = {
            "off": 1.00,
            "normal": 1.16,
            "medium": 1.24,
            "high": 1.38,
        }.get(contrast_key, 1.22)
    pil = ImageEnhance.Contrast(pil).enhance(contrast)

    sharp_key = str(unsharp_mode or "auto").strip().lower()
    if sharp_key == "auto":
        sharp_key = level
    unsharp = {
        "off": None,
        "none": (0.8, 100, 4),
        "weak": (1.0, 150, 3),
        "strong": (1.2, 210, 2),
    }.get(sharp_key, (1.0, 150, 3))
    if unsharp is not None:
        pil = pil.filter(ImageFilter.UnsharpMask(radius=unsharp[0], percent=unsharp[1], threshold=unsharp[2]))
    return np.asarray(pil.convert("RGB"))


def strip_vlines(img: np.ndarray, height_frac: float = 0.30) -> np.ndarray:
    """Remove full-page vertical printer/scanner streaks, keep text.

    A streak is a long connected vertical run. A tall, 1px-wide kernel isolates
    it while leaving short vertical strokes of letters (Н, П, Ш) intact, then we
    inpaint the streak away. TODO(codex): tune height_frac on real samples.
    """
    if cv2 is None:
        return _strip_vlines_numpy(img, height_frac=height_frac)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    bw = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 5
    )
    k_h = max(1, int(img.shape[0] * height_frac))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k_h))
    lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)
    lines = cv2.dilate(lines, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    src = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return cv2.inpaint(src, lines, 3, cv2.INPAINT_TELEA)


def _strip_vlines_numpy(img: np.ndarray, height_frac: float = 0.30) -> np.ndarray:
    """CPU fallback for page-long scanner streaks when OpenCV is unavailable."""
    arr = img.astype(np.uint8, copy=True)
    gray = arr if arr.ndim == 2 else np.asarray(_array_to_pil(arr).convert("L"))
    h, w = gray.shape[:2]
    if h <= 0 or w <= 0:
        return img

    dark_ratio = (gray < 220).mean(axis=0)
    window = min(7, max(3, (w // 400) | 1))
    smooth = np.convolve(dark_ratio, np.ones(window) / float(window), mode="same")
    threshold = max(0.0, min(0.95, float(height_frac)))
    strength_threshold = max(threshold + 0.05, 0.35)
    margin = max(2, int(w * 0.03))
    candidates = smooth >= threshold
    candidates[:margin] = False
    candidates[w - margin:] = False

    groups: list[tuple[int, int]] = []
    start: int | None = None
    for idx, value in enumerate(candidates):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            groups.append((start, idx))
            start = None
    if start is not None:
        groups.append((start, w))

    max_width = max(4, int(w * 0.025))
    for start, end in groups:
        if end <= start or (end - start) > max_width:
            continue
        if float(smooth[start:end].max()) < strength_threshold:
            continue
        left = max(0, start - 10)
        right = min(w, end + 10)
        ref_parts = []
        if left < start:
            ref_parts.append(arr[:, left:start])
        if end < right:
            ref_parts.append(arr[:, end:right])
        if not ref_parts:
            continue
        ref = np.concatenate(ref_parts, axis=1)
        fill = np.median(ref, axis=1).astype(np.uint8)
        arr[:, start:end] = fill[:, None] if arr.ndim == 2 else fill[:, None, :]
    return arr


def deskew(img: np.ndarray, max_angle: float = 15.0) -> np.ndarray:
    """Straighten small rotations via dominant text-line angle (Hough)."""
    if cv2 is None:
        return img
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
    if lines is None:
        return img
    angles = []
    for rho_theta in lines[:200]:
        theta = rho_theta[0][1]
        deg = (theta * 180.0 / np.pi) - 90.0  # relative to horizontal
        if abs(deg) <= max_angle:
            angles.append(deg)
    if not angles:
        return img
    angle = float(np.median(angles))
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def binarize(img: np.ndarray, block: int = 31, c: int = 15, cleanup: str = "weak") -> np.ndarray:
    """Adaptive threshold. Apply LAST, and only for Tesseract (see CleanConfig)."""
    if cv2 is None:
        pil = _array_to_pil(img)
        gray = ImageOps.autocontrast(ImageOps.grayscale(pil), cutoff=0.5)
        bw = _local_threshold(gray, block=block, c=c)
        mode = str(cleanup or "weak").strip().lower()
        if mode == "weak":
            bw = bw.filter(ImageFilter.MedianFilter(3))
        elif mode == "strong":
            bw = bw.filter(ImageFilter.MedianFilter(3))
            bw = bw.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
        return np.asarray(bw, dtype=np.uint8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    out = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, c
    )
    if str(cleanup or "").strip().lower() == "strong":
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        out = cv2.morphologyEx(out, cv2.MORPH_OPEN, kernel)
    return out


def png_encode(img: np.ndarray) -> bytes:
    if cv2 is None:
        out = BytesIO()
        _array_to_pil(img).save(out, format="PNG")
        return out.getvalue()
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return buf.tobytes()


def png_decode(data: bytes) -> np.ndarray:
    if cv2 is None:
        with Image.open(BytesIO(data)) as pil:
            return np.asarray(pil.convert("RGB"))
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not a decodable image")
    return img


def _array_to_pil(img: np.ndarray) -> Image.Image:
    if img.ndim == 2:
        return Image.fromarray(img.astype(np.uint8), mode="L")
    arr = img.astype(np.uint8)
    if cv2 is not None:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(arr, mode="RGB")


def _local_threshold(gray: Image.Image, block: int = 31, c: int = 15) -> Image.Image:
    window = max(3, int(block) | 1)
    radius = window // 2
    arr = np.asarray(gray, dtype=np.float32)
    padded = np.pad(arr, radius, mode="reflect")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    sums = (
        integral[window:, window:]
        - integral[:-window, window:]
        - integral[window:, :-window]
        + integral[:-window, :-window]
    )
    mean = sums / float(window * window)
    threshold = mean - float(c)
    bw = np.where(arr > threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(bw, mode="L")
