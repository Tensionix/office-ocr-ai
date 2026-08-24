# layout.py
# Reconstruct structure from a flat OCR word list (geometry only).
# Used by render_docx (lines -> paragraphs) and render_xlsx (rows x columns grid).
# HONEST LIMIT: a flat word list does not know "this is a table". These are
# coordinate heuristics. For reliable tables, feed structured regions from a
# layout engine (Surya / PP-Structure) instead of raw words. TODO(codex).
# No globals; pure functions. EN comments only. UTF-8 without BOM.

from __future__ import annotations

from typing import Any


def _cy(w: dict) -> float:
    x, y, bw, bh = w["box"]
    return y + bh / 2.0


def _h(w: dict) -> float:
    return float(w["box"][3])


def group_lines(words: list[dict], y_tol_factor: float = 0.6) -> list[list[dict]]:
    """Cluster words into text lines by vertical center proximity.
    y_tol scales with median glyph height so it adapts to font size."""
    ws = [w for w in words if w.get("text")]
    if not ws:
        return []
    heights = sorted(_h(w) for w in ws)
    med_h = heights[len(heights) // 2] or 1.0
    y_tol = med_h * y_tol_factor

    ws.sort(key=_cy)
    lines: list[list[dict]] = []
    current: list[dict] = [ws[0]]
    base = _cy(ws[0])
    for w in ws[1:]:
        if abs(_cy(w) - base) <= y_tol:
            current.append(w)
        else:
            lines.append(sorted(current, key=lambda d: d["box"][0]))
            current = [w]
            base = _cy(w)
    lines.append(sorted(current, key=lambda d: d["box"][0]))
    return lines


def lines_to_paragraphs(lines: list[list[dict]], gap_factor: float = 1.6) -> list[list[list[dict]]]:
    """Group consecutive lines into paragraphs by the vertical gap between them."""
    if not lines:
        return []
    def line_top(ln): return min(w["box"][1] for w in ln)
    def line_bot(ln): return max(w["box"][1] + w["box"][3] for w in ln)
    med_h = sorted(_h(w) for ln in lines for w in ln)
    med_h = med_h[len(med_h) // 2] if med_h else 1.0

    paras: list[list[list[dict]]] = []
    cur: list[list[dict]] = [lines[0]]
    for prev, ln in zip(lines, lines[1:]):
        gap = line_top(ln) - line_bot(prev)
        if gap > med_h * gap_factor:
            paras.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    paras.append(cur)
    return paras


def line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def cluster_columns(words: list[dict], x_tol_factor: float = 1.5) -> list[float]:
    """Return sorted x-boundaries between columns, from gaps in word x-starts.
    Heuristic only; works for clearly columnar tables. TODO(codex): replace with
    layout-engine column regions for robust results."""
    if not words:
        return []
    xs = sorted(w["box"][0] for w in words)
    widths = sorted(w["box"][2] for w in words)
    med_w = widths[len(widths) // 2] or 1.0
    tol = med_w * x_tol_factor
    bounds: list[float] = []
    for a, b in zip(xs, xs[1:]):
        if b - a > tol:
            bounds.append((a + b) / 2.0)
    return bounds


def build_grid(words: list[dict]) -> list[list[str]]:
    """Reconstruct a 2D table: rows by line clustering, columns by x-boundaries.
    Returns a list of rows; each row is a list of cell strings. Heuristic."""
    lines = group_lines(words)
    if not lines:
        return []
    bounds = cluster_columns(words)
    ncols = len(bounds) + 1

    def col_of(x: float) -> int:
        i = 0
        for b in bounds:
            if x >= b:
                i += 1
        return i

    grid: list[list[str]] = []
    for ln in lines:
        row = [""] * ncols
        for w in ln:
            c = col_of(w["box"][0])
            row[c] = (row[c] + " " + w["text"]).strip()
        grid.append(row)
    return grid
