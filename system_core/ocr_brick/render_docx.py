# render_docx.py
# Render brick: OcrResult word boxes -> editable DOCX (paragraphs).
# Uses python-docx (the right fit for the Audion Python stack). Carries the docx
# gotchas that matter here: one paragraph per paragraph (never embed "\n"),
# Cyrillic-safe font, explicit table widths IF tables are emitted.
# Table reconstruction from a FLAT word list is unreliable -> left as a guarded
# stub; feed layout-engine regions for real tables. TODO(codex).
# No globals; pure-ish (writes the file path it is given). EN comments only.
# UTF-8 without BOM.  Requires: python-docx.

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt

import layout


def _set_default_font(doc: Document, font_name: str = "DejaVu Sans", size_pt: int = 11) -> None:
    # DejaVu Sans / Arial both cover Cyrillic; the project should ensure the font
    # is installed on the target machine, else Word substitutes. TODO(codex): pick
    # the project's standard Cyrillic font.
    style = doc.styles["Normal"]
    style.font.name = font_name
    style.font.size = Pt(size_pt)


def render_docx(out_path: str | Path,
                pages: list[list[dict]],
                font_name: str = "DejaVu Sans",
                page_break_between: bool = True) -> Path:
    """pages = [ [word_dict, ...], ... ] one list of words per page.
    word_dict = {"text": str, "box": [x,y,w,h], "confidence": float}."""
    doc = Document()
    _set_default_font(doc, font_name)

    for pi, words in enumerate(pages):
        if pi > 0 and page_break_between:
            doc.add_page_break()
        lines = layout.group_lines(words)
        paras = layout.lines_to_paragraphs(lines)
        for para_lines in paras:
            # join the lines of a paragraph with spaces; one docx paragraph object
            text = " ".join(layout.line_text(ln) for ln in para_lines)
            if text.strip():
                doc.add_paragraph(text)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def render_docx_with_tables(out_path: str | Path, pages_regions: list) -> Path:
    """Preferred path when a layout engine provides typed regions (Surya).
    `pages_regions` is a list of LayoutResult. Delegates to render_regions, which
    emits paragraphs/headings and REAL docx tables with explicit widths/spans."""
    import render_regions
    return render_regions.regions_to_docx(out_path, pages_regions)
