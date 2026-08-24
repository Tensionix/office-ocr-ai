"""Recover physical table cells from ruled scan geometry.

The detector uses only long raster lines for the base grid.  It never derives
columns from OCR text similarity.  OCR words are used solely to identify a
numbering row (1..N), which separates complex headers from ordinary data rows.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def recover_physical_tables(
    regions: list[dict[str, Any]],
    image_path: str | Path,
    tesseract_words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    path = Path(image_path)
    if not path.is_file():
        return []
    with Image.open(path) as image:
        gray = np.asarray(image.convert("L"))
    reports: list[dict[str, Any]] = []
    for index, region in enumerate(regions):
        if str(region.get("region_type") or region.get("kind") or "") != "table":
            continue
        reports.append(_recover_one(region, gray, tesseract_words, index))
    return reports


def _recover_one(
    region: dict[str, Any],
    gray: np.ndarray,
    words: list[dict[str, Any]],
    region_index: int,
) -> dict[str, Any]:
    box = region.get("box")
    if not _valid_box(box):
        return {"region": region_index, "applied": False, "reason": "table_box_missing"}
    x, y, width, height = [int(value) for value in box]
    pad = max(12, min(32, round(min(width, height) * 0.015)))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1 = min(gray.shape[1], x + width + pad + 1)
    y1 = min(gray.shape[0], y + height + pad + 1)
    dark = gray[y0:y1, x0:x1] < 180
    xs = [value + x0 for value in _line_centers(dark.mean(axis=0), 0.25)]
    ys = [value + y0 for value in _line_centers(dark.mean(axis=1), 0.30)]
    rows, cols = len(ys) - 1, len(xs) - 1
    expected_rows = int(region.get("rows") or 0)
    if rows < 1 or cols < 1:
        return {"region": region_index, "applied": False, "reason": "physical_grid_missing"}
    if expected_rows and rows != expected_rows:
        return {
            "region": region_index, "applied": False, "reason": "physical_row_count_mismatch",
            "physical_rows": rows, "structure_rows": expected_rows,
        }

    numbering_row, numbering_score = _numbering_row(words, xs, ys)
    if numbering_row is None:
        return {
            "region": region_index, "applied": False, "reason": "numbering_row_unverified",
            "physical_rows": rows, "physical_cols": cols,
        }

    parent = list(range(rows * cols))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    # Only header rows may contain merged cells.  Broken or faint data-row
    # separators therefore cannot accidentally merge two records.
    for row in range(numbering_row):
        for col in range(cols - 1):
            coverage = _vertical_separator_coverage(dark, xs[col + 1] - x0, ys[row] - y0, ys[row + 1] - y0)
            if coverage < 0.50:
                union(row * cols + col, row * cols + col + 1)
    for row in range(numbering_row - 1):
        for col in range(cols):
            coverage = _horizontal_separator_coverage(dark, ys[row + 1] - y0, xs[col] - x0, xs[col + 1] - x0)
            if coverage < 0.50:
                union(row * cols + col, (row + 1) * cols + col)

    components: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for row in range(rows):
        for col in range(cols):
            components[find(row * cols + col)].append((row, col))
    if any(not _rectangular(cells) for cells in components.values()):
        return {
            "region": region_index, "applied": False, "reason": "non_rectangular_merge",
            "physical_rows": rows, "physical_cols": cols,
        }

    original_cells = list(region.get("cells") or [])
    by_origin = {(int(cell.get("row") or 0), int(cell.get("col") or 0)): cell for cell in original_cells}
    physical_cells: list[dict[str, Any]] = []
    for component in sorted(components.values(), key=lambda cells: min(cells)):
        row0 = min(row for row, _ in component)
        row1 = max(row for row, _ in component) + 1
        col0 = min(col for _, col in component)
        col1 = max(col for _, col in component) + 1
        original = by_origin.get((row0, col0)) or {}
        physical_cells.append({
            "text": str(original.get("text") or ""),
            "mistral_text": str(original.get("text") or ""),
            "row": row0,
            "col": col0,
            "rowspan": row1 - row0,
            "colspan": col1 - col0,
            "box": [xs[col0], ys[row0], xs[col1] - xs[col0], ys[row1] - ys[row0]],
            "coordinate_source": "physical_grid_verified",
            "coordinate_confidence": round(numbering_score, 4),
        })

    region["rows"] = rows
    region["cols"] = cols
    region["cells"] = physical_cells
    region["box"] = [xs[0], ys[0], xs[-1] - xs[0], ys[-1] - ys[0]]
    region["geometry_source"] = "raster_lines+tesseract_numbering"
    region["physical_grid"] = {
        "x_boundaries": xs,
        "y_boundaries": ys,
        "numbering_row": numbering_row,
        "numbering_score": round(numbering_score, 4),
    }
    return {
        "region": region_index,
        "applied": True,
        "reason": "physical_grid_verified",
        "rows": rows,
        "cols": cols,
        "cells": len(physical_cells),
        "numbering_row": numbering_row,
        "numbering_score": round(numbering_score, 4),
    }


def _line_centers(projection: np.ndarray, threshold: float) -> list[int]:
    indices = np.flatnonzero(projection >= threshold)
    if not len(indices):
        return []
    groups: list[tuple[int, int]] = []
    start = previous = int(indices[0])
    for raw in indices[1:]:
        value = int(raw)
        if value > previous + 5:
            groups.append((start, previous))
            start = value
        previous = value
    groups.append((start, previous))
    return [round((start + end) / 2) for start, end in groups]


def _numbering_row(
    words: list[dict[str, Any]],
    xs: list[int],
    ys: list[int],
) -> tuple[int | None, float]:
    cols = len(xs) - 1
    best_row, best_score = None, 0.0
    for row in range(len(ys) - 1):
        matched = 0
        for col in range(cols):
            values = []
            for word in words:
                box = word.get("box")
                if not _valid_box(box):
                    continue
                wx, wy, ww, wh = [float(value) for value in box]
                cx, cy = wx + ww / 2, wy + wh / 2
                if xs[col] <= cx <= xs[col + 1] and ys[row] <= cy <= ys[row + 1]:
                    values.extend(int(token) for token in re.findall(r"\d+", str(word.get("text") or "")))
            if col + 1 in values:
                matched += 1
        score = matched / max(1, cols)
        if score > best_score:
            best_row, best_score = row, score
    return (best_row, best_score) if best_score >= 0.70 else (None, best_score)


def _vertical_separator_coverage(dark: np.ndarray, x: int, y0: int, y1: int) -> float:
    sample = dark[max(0, y0 + 4):max(0, y1 - 4), max(0, x - 3):x + 4]
    return float(sample.mean(axis=0).max()) if sample.size else 1.0


def _horizontal_separator_coverage(dark: np.ndarray, y: int, x0: int, x1: int) -> float:
    sample = dark[max(0, y - 3):y + 4, max(0, x0 + 4):max(0, x1 - 4)]
    return float(sample.mean(axis=1).max()) if sample.size else 1.0


def _rectangular(cells: list[tuple[int, int]]) -> bool:
    rows = [row for row, _ in cells]
    cols = [col for _, col in cells]
    return (max(rows) - min(rows) + 1) * (max(cols) - min(cols) + 1) == len(cells)


def _valid_box(box: Any) -> bool:
    return isinstance(box, (list, tuple)) and len(box) == 4 and float(box[2]) >= 0 and float(box[3]) >= 0
