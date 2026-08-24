# render_pdf.py
# Render brick: build a SEARCHABLE PDF from page images + OcrResult word boxes.
# Visual layer = the recognized image (so boxes line up by construction).
# Text layer  = invisible text (render mode 3) positioned per word box.
# Cyrillic REQUIRES a registered TTF: reportlab's built-in fonts lack Cyrillic
# glyphs and would render boxes. Pass a font path (e.g. DejaVuSans.ttf).
# No globals, no magic paths. EN comments only. UTF-8 without BOM.
#
# Requires: reportlab. Coordinates: image pixels (top-left origin) -> PDF points
# (bottom-left origin), so y is flipped.

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from . import imageops


_FONT_NAME = "OCRCyr"


def _register_font(font_path: str | Path) -> str:
    fp = Path(font_path)
    if not fp.is_file():
        raise FileNotFoundError(
            f"Cyrillic TTF required for searchable text layer: {fp} "
            "(bundle e.g. DejaVuSans.ttf with the brick)")
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(fp)))
    return _FONT_NAME


def _page(c: canvas.Canvas, image_png: bytes, words: Iterable[dict],
          font_name: str, dpi: int) -> None:
    img = imageops.png_decode(image_png)
    h_px, w_px = img.shape[:2]
    scale = 72.0 / float(dpi)          # pixels -> PDF points
    w_pt, h_pt = w_px * scale, h_px * scale

    c.setPageSize((w_pt, h_pt))
    # visual layer: the exact image the OCR saw
    c.drawImage(ImageReader(_bytes_io(image_png)), 0, 0, width=w_pt, height=h_pt)

    # invisible, selectable text on top
    c.setFont(font_name, 1)            # size set per-word below
    for wd in words:
        txt = wd.get("text", "")
        box = wd.get("box")
        if not txt or not box:
            continue
        x, y, bw, bh = box             # pixels, top-left origin
        size = max(1.0, bh * scale)
        x_pt = x * scale
        y_pt = h_pt - (y + bh) * scale  # flip y to PDF origin
        c.setFont(font_name, size)
        c.setFillAlpha(0.0)            # belt-and-suspenders with render mode 3
        tobj = c.beginText(x_pt, y_pt)
        tobj.setTextRenderMode(3)      # invisible but searchable/copyable
        tobj.textLine(txt)
        c.drawText(tobj)
    c.showPage()


def render_searchable_pdf(out_path: str | Path,
                          pages: list[tuple[bytes, list[dict]]],
                          font_path: str | Path,
                          dpi: int = 300) -> Path:
    """pages = [(image_png_bytes, [word_dict, ...]), ...] in order.
    word_dict = {"text": str, "box": [x,y,w,h], "confidence": float}.
    Returns the written PDF path."""
    font_name = _register_font(font_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out))
    for image_png, words in pages:
        _page(c, image_png, words, font_name, dpi)
    c.save()
    return out


def _bytes_io(data: bytes):
    import io
    return io.BytesIO(data)
