# preprocess.py
# The cleaning pipeline. clean_page() is a PURE function of (page bytes, cfg):
# same inputs -> identical output bytes (this is what makes the L1 cache correct).
# Stage order: strip_vlines -> SR(Vulkan) -> deskew -> conditional binarize.
# No globals, no magic paths. Dependencies (cache, sr) are injected.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

from pathlib import Path

from .cleanconfig import CleanConfig
from . import imageops


# --------------------------------------------------------------------------- #
# Source -> raster pages                                                       #
# --------------------------------------------------------------------------- #

def rasterize(source_path: str | Path, dpi: int = 300) -> list[bytes]:
    """Return one PNG (bytes) per page. Only the rasterizer knows about containers.

    - image -> single page, passthrough
    - pdf   -> page pixmaps   (TODO(codex): wire pymupdf/fitz; stub below)
    - docx/pptx -> extract embedded scan images; skip born-digital text
                   (TODO(codex): detect and handle)
    """
    p = Path(source_path)
    ext = p.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
        img = imageops.png_decode(p.read_bytes())
        return [imageops.png_encode(img)]
    if ext == ".pdf":
        import fitz

        with fitz.open(p) as doc:
            return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]
    raise ValueError(f"unsupported source type: {ext}")


# --------------------------------------------------------------------------- #
# Cleaning                                                                     #
# --------------------------------------------------------------------------- #

def _run_pipeline(page_png: bytes, cfg: CleanConfig, sr) -> bytes:
    """The actual transform. `sr` is an SRClient (or None if sr_scale==0)."""
    img = imageops.png_decode(page_png)

    img = imageops.preclean(
        img,
        denoise=cfg.denoise,
        source_format=cfg.source_format,
        intent=cfg.intent,
        contrast_mode=cfg.contrast,
        unsharp_mode=cfg.unsharp,
    )

    if cfg.strip_vlines:
        img = imageops.strip_vlines(img)

    if cfg.sr_scale and cfg.sr_scale > 0:
        if sr is None:
            raise RuntimeError("sr_scale>0 but no SR client provided")
        up = sr.enhance_bytes(
            imageops.png_encode(img),
            sr_model=cfg.sr_model_resolved(),
            denoise=cfg.denoise,
            scale=cfg.sr_scale,
        )
        img = imageops.png_decode(up)

    if cfg.deskew:
        img = imageops.deskew(img)

    if cfg.binarize_on():
        img = imageops.binarize(img, cleanup=cfg.denoise)

    return imageops.png_encode(img)


def clean_page(page_png: bytes, cfg: CleanConfig, cache=None, sr=None) -> bytes:
    """Return cleaned PNG bytes. Pure w.r.t. (page_png, cfg).

    Master bypass: cfg.enabled == False -> return the original bytes untouched.
    L1 cache (if provided) is keyed by raw page + cfg.canonical(); the enabled
    flag is part of canonical(), so raw-passthrough gets its own cache key.
    """
    if not cfg.enabled:
        return page_png  # hard global bypass: raw in = raw out

    key = cfg.canonical()
    if cache is not None:
        hit = cache.l1_get(page_png, key)
        if hit is not None:
            return hit

    out = _run_pipeline(page_png, cfg, sr)

    if cache is not None:
        cache.l1_put(page_png, key, out)
    return out
