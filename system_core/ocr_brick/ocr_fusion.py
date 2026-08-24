"""Conservative Mistral-structure + Yandex-text OCR fusion."""

from __future__ import annotations

import copy
import difflib
import math
import re
from pathlib import Path
from typing import Any

from .engines.mistral import layout_from_mistral_page
from .layout import group_lines, line_text


_NUMERIC_ONLY = re.compile(r"^[\s\d.,%+\-–—/()№]+$")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def needs_yandex_review(primary: dict[str, Any], scope: str) -> tuple[bool, str]:
    if scope == "all":
        return True, "scope_all"
    verification = primary.get("verification")
    if isinstance(verification, dict):
        status = str(verification.get("status") or "")
        if status in {"review", "insufficient", "error"} or not bool(verification.get("verified")):
            return True, f"tesseract_{status or 'not_verified'}"
        return False, "tesseract_pass"
    text = str(primary.get("text") or "")
    if not text.strip():
        return True, "empty_primary"
    # Without an independent local comparison, be conservative: a paid Yandex
    # pass explicitly selected for suspicious pages must not silently skip them.
    return True, "no_independent_verification"


def fuse_mistral_yandex(
    primary: dict[str, Any],
    yandex: dict[str, Any],
    _image_path: str | Path,
) -> dict[str, Any]:
    raw_page = primary.get("mistral_page")
    if not isinstance(raw_page, dict):
        return {"applied": False, "reason": "mistral_page_missing", "regions": []}
    yandex_words = [word for word in yandex.get("words") or [] if _valid_word(word)]
    if not yandex_words:
        return {"applied": False, "reason": "yandex_words_missing", "regions": []}

    native_regions = primary.get("regions")
    if isinstance(native_regions, list):
        regions = copy.deepcopy(native_regions)
    else:
        layout = layout_from_mistral_page(raw_page, page=int(primary.get("page") or 0))
        regions = copy.deepcopy(layout.to_dict().get("regions") or [])
    tesseract_words = [
        word for word in (primary.get("tesseract_2pass") or {}).get("words") or []
        if _valid_word(word)
    ]
    from .table_geometry import recover_physical_tables

    physical_geometry = recover_physical_tables(regions, _image_path, tesseract_words + yandex_words)
    coordinate_anchors = _anchor_table_cells_with_tesseract(regions, tesseract_words)
    decisions: list[dict[str, Any]] = []
    replaced = 0

    for region_index, region in enumerate(regions):
        region_type = str(region.get("region_type") or region.get("kind") or "")
        if region_type == "table":
            changed, table_decisions = _fuse_table(region, yandex_words, tesseract_words, region_index)
            replaced += changed
            decisions.extend(table_decisions)
            continue
        box = region.get("box")
        if not _valid_box(box) or not str(region.get("text") or "").strip():
            continue
        candidate_words = _words_in_rect(yandex_words, tuple(box))
        candidate = _words_text(candidate_words)
        selected, reason = _select_text(str(region.get("text") or ""), candidate)
        decision = {
            "region": region_index,
            "kind": region_type,
            "primary": str(region.get("text") or ""),
            "yandex": candidate,
            "selected_engine": "yandex" if selected else "mistral",
            "reason": reason,
            "box": list(box),
        }
        if selected:
            region["text"] = candidate
            replaced += 1
        decisions.append(decision)

    return {
        "version": 1,
        "applied": replaced > 0,
        "primary_engine": "mistral",
        "text_engine": "yandex",
        "structure_engine": "mistral",
        "replaced_items": replaced,
        "coordinate_anchors": coordinate_anchors,
        "physical_geometry": physical_geometry,
        "review_items": sum(
            1 for item in decisions
            if item.get("reason") in {
                "numeric_disagreement",
                "trusted_cell_coordinates_missing",
                "merged_cell_coordinate_review",
                "anchored_text_incomplete",
                "anchored_text_edge_mismatch",
                "anchored_text_mismatch",
                "physical_numeric_disagreement",
                "physical_text_disagreement",
            }
        ),
        "regions": regions,
        "text": _regions_text(regions),
        "decisions": decisions,
    }


def _fuse_table(
    region: dict[str, Any],
    words: list[dict[str, Any]],
    tesseract_words: list[dict[str, Any]],
    region_index: int,
) -> tuple[int, list[dict[str, Any]]]:
    rows, cols = int(region.get("rows") or 0), int(region.get("cols") or 0)
    if rows < 1 or cols < 1:
        return 0, []
    cells = list(region.get("cells") or [])
    cells_with_boxes = [cell for cell in cells if _has_trusted_cell_box(cell)]
    if not cells_with_boxes:
        return 0, [{
            "region": region_index,
            "kind": "table",
            "selected_engine": "mistral",
            "reason": "trusted_cell_coordinates_missing",
            "cells": len(cells),
        }]

    changed = 0
    decisions: list[dict[str, Any]] = []
    for cell in cells:
        row, col = int(cell.get("row") or 0), int(cell.get("col") or 0)
        rowspan, colspan = max(1, int(cell.get("rowspan") or 1)), max(1, int(cell.get("colspan") or 1))
        if row >= rows or col >= cols or not _has_trusted_cell_box(cell):
            continue
        rect = tuple(int(value) for value in cell["box"])
        candidate = _words_text(_words_in_rect(words, rect, inset=1.0))
        tesseract_candidate = _words_text(_words_in_rect(tesseract_words, rect, inset=1.0))
        primary_text = str(cell.get("text") or "")
        if cell.get("coordinate_source") == "physical_grid_verified":
            candidate = _clean_physical_cell_text(candidate)
            tesseract_candidate = _clean_physical_cell_text(tesseract_candidate)
            selected, reason = _select_physical_text(primary_text, candidate, tesseract_candidate)
        elif (
            cell.get("coordinate_source") == "tesseract_native_alignment"
            and (rowspan > 1 or colspan > 1)
        ):
            selected, reason = False, "merged_cell_coordinate_review"
        elif cell.get("coordinate_source") == "tesseract_native_alignment":
            selected, reason = _select_anchored_text(primary_text, candidate)
        else:
            selected, reason = _select_text(primary_text, candidate)
        if selected:
            cell["text"] = candidate
            changed += 1
        decisions.append({
            "region": region_index,
            "kind": "table_cell",
            "row": row,
            "col": col,
            "rowspan": rowspan,
            "colspan": colspan,
            "primary": primary_text,
            "yandex": candidate,
            "tesseract": tesseract_candidate,
            "selected_engine": "yandex" if selected else "mistral",
            "reason": reason,
            "box": list(rect),
        })
    return changed, decisions


def _select_text(primary: str, yandex: str) -> tuple[bool, str]:
    primary = " ".join(primary.split())
    yandex = " ".join(yandex.split())
    if not yandex:
        return False, "yandex_empty"
    if not primary:
        return True, "primary_empty"
    if primary.casefold() == yandex.casefold():
        return False, "equivalent"
    if _NUMERIC_ONLY.fullmatch(primary) and _NUMERIC_ONLY.fullmatch(yandex):
        if _canonical_numbers(primary) != _canonical_numbers(yandex):
            return False, "numeric_disagreement"
        return True, "numeric_agreement"
    ratio = len(yandex) / max(1, len(primary))
    if ratio < 0.50 or ratio > 2.5:
        return False, "implausible_length"
    if len(primary) > 40 and ratio < 0.72:
        return False, "incomplete_candidate"
    primary_cyr = len(_CYRILLIC.findall(primary))
    yandex_cyr = len(_CYRILLIC.findall(yandex))
    if primary_cyr and yandex_cyr < max(1, math.floor(primary_cyr * 0.25)):
        return False, "cyrillic_loss"
    primary_norm = _semantic_normalize(primary)
    yandex_norm = _semantic_normalize(yandex)
    similarity = difflib.SequenceMatcher(None, primary_norm, yandex_norm).ratio()
    primary_tokens = set(primary_norm.split())
    yandex_tokens = set(yandex_norm.split())
    token_overlap = len(primary_tokens & yandex_tokens) / max(1, min(len(primary_tokens), len(yandex_tokens)))
    if similarity < 0.50 and token_overlap < 0.35:
        return False, "semantic_mismatch"
    return True, "preferred_russian_ocr"


def _select_anchored_text(primary: str, yandex: str) -> tuple[bool, str]:
    """Apply stricter text checks to coordinates recovered through Tesseract."""
    selected, reason = _select_text(primary, yandex)
    if not selected:
        return selected, reason
    primary_norm = _semantic_normalize(primary)
    yandex_norm = _semantic_normalize(yandex)
    primary_tokens, yandex_tokens = primary_norm.split(), yandex_norm.split()
    if not primary_tokens or not yandex_tokens:
        return False, "anchored_text_incomplete"
    first_similarity = difflib.SequenceMatcher(None, primary_tokens[0], yandex_tokens[0]).ratio()
    last_similarity = difflib.SequenceMatcher(None, primary_tokens[-1], yandex_tokens[-1]).ratio()
    similarity = difflib.SequenceMatcher(None, primary_norm, yandex_norm).ratio()
    primary_set, yandex_set = set(primary_tokens), set(yandex_tokens)
    overlap = len(primary_set & yandex_set) / max(1, min(len(primary_set), len(yandex_set)))
    if first_similarity < 0.65 or last_similarity < 0.65:
        return False, "anchored_text_edge_mismatch"
    if similarity < 0.76 or overlap < 0.50:
        return False, "anchored_text_mismatch"
    return True, "tesseract_coordinate_consensus"


def _select_physical_text(primary: str, yandex: str, tesseract: str) -> tuple[bool, str]:
    """Select a text layer after physical cell boundaries are established."""
    primary_norm = _semantic_normalize(primary)
    yandex_norm = _semantic_normalize(yandex)
    tesseract_norm = _semantic_normalize(tesseract)
    if not yandex_norm:
        return False, "physical_yandex_empty"
    primary_numbers = _canonical_numbers(primary)
    yandex_numbers = _canonical_numbers(yandex)
    tesseract_numbers = _canonical_numbers(tesseract)
    numeric_cell = bool(primary_numbers or yandex_numbers or tesseract_numbers) and all(
        _NUMERIC_ONLY.fullmatch(value or "")
        for value in (primary, yandex, tesseract)
        if str(value or "").strip()
    )
    if numeric_cell:
        if tesseract_numbers and yandex_numbers == tesseract_numbers:
            return primary_norm != yandex_norm, "physical_numeric_consensus"
        if _numbers_with_trailing_line_artifact(yandex_numbers, tesseract_numbers):
            return primary_norm != yandex_norm, "physical_numeric_near_consensus"
        if primary_numbers and yandex_numbers == primary_numbers:
            return False, "physical_numeric_primary_agreement"
        return False, "physical_numeric_disagreement"
    if tesseract_norm:
        agreement = difflib.SequenceMatcher(None, yandex_norm, tesseract_norm).ratio()
        if agreement >= 0.45:
            return primary_norm != yandex_norm, "physical_yandex_tesseract_consensus"
    if primary_norm:
        agreement = difflib.SequenceMatcher(None, primary_norm, yandex_norm).ratio()
        if agreement >= 0.62:
            return primary_norm != yandex_norm, "physical_yandex_primary_consensus"
        return False, "physical_text_disagreement"
    return True, "physical_yandex_only"


def _clean_physical_cell_text(text: str) -> str:
    value = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", str(text or ""))
    value = re.sub(r"\s*\n\s*", " ", value)
    value = re.sub(r"(?:^|\s)[|_]+(?=\s|$)", " ", value)
    value = " ".join(value.split())
    latin_to_cyrillic = str.maketrans({
        "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н",
        "O": "О", "P": "Р", "C": "С", "T": "Т", "X": "Х", "Y": "У",
    })
    parts = []
    for token in value.split():
        letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", token)
        if letters and len(letters) <= 12 and letters.upper() == letters:
            token = token.translate(latin_to_cyrillic)
        parts.append(token)
    return " ".join(parts)


def _numbers_with_trailing_line_artifact(yandex: list[str], tesseract: list[str]) -> bool:
    if not yandex or len(yandex) != len(tesseract):
        return False
    return all(left == right or right == left + "1" for left, right in zip(yandex, tesseract))


def _canonical_numbers(text: str) -> list[str]:
    values = re.findall(r"\d[\d\s.,]*", text)
    return [re.sub(r"[\s.,]", "", value) for value in values]


def _semantic_normalize(text: str) -> str:
    value = str(text or "").casefold().replace("ё", "е")
    value = re.sub(r"(?<=\w)[\-–—]\s*(?=\w)", "", value)
    value = re.sub(r"[^0-9a-zа-я]+", " ", value)
    return " ".join(value.split())


def _words_in_rect(
    words: list[dict[str, Any]],
    rect: tuple[int, int, int, int],
    *,
    inset: float = 0.0,
) -> list[dict[str, Any]]:
    x, y, width, height = [float(value) for value in rect]
    x0, y0 = x + inset, y + inset
    x1, y1 = x + width - inset, y + height - inset
    selected = []
    for word in words:
        wx, wy, ww, wh = [float(value) for value in word["box"]]
        cx, cy = wx + ww / 2, wy + wh / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            selected.append(word)
    return selected


def _words_text(words: list[dict[str, Any]]) -> str:
    return "\n".join(line_text(line) for line in group_lines(list(words)) if line)


def _regions_text(regions: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for region in regions:
        if str(region.get("region_type") or region.get("kind") or "") == "table":
            rows = [["" for _ in range(int(region.get("cols") or 0))] for _ in range(int(region.get("rows") or 0))]
            for cell in region.get("cells") or []:
                row, col = int(cell.get("row") or 0), int(cell.get("col") or 0)
                if 0 <= row < len(rows) and 0 <= col < len(rows[row]):
                    rows[row][col] = str(cell.get("text") or "")
            chunks.extend("\t".join(row) for row in rows)
        elif str(region.get("text") or "").strip():
            chunks.append(str(region.get("text") or ""))
    return "\n".join(chunks)


def _valid_word(word: Any) -> bool:
    return isinstance(word, dict) and bool(str(word.get("text") or "").strip()) and _valid_box(word.get("box"))


def _valid_box(box: Any) -> bool:
    return isinstance(box, (list, tuple)) and len(box) == 4 and float(box[2]) >= 0 and float(box[3]) >= 0


def _has_trusted_cell_box(cell: Any) -> bool:
    """Accept provider cells or conservative Tesseract text anchors.

    Merely having a ``box`` is deliberately insufficient: an inferred CV grid
    must never become authority for automatic text replacement by accident.
    """
    if not isinstance(cell, dict) or not _valid_box(cell.get("box")):
        return False
    if cell.get("coordinate_source") == "provider_native":
        return True
    if cell.get("coordinate_source") == "physical_grid_verified":
        return float(cell.get("coordinate_confidence") or 0.0) >= 0.70
    return (
        cell.get("coordinate_source") == "tesseract_native_alignment"
        and float(cell.get("coordinate_confidence") or 0.0) >= 0.90
        and int(cell.get("coordinate_anchor_count") or 0) >= 1
    )


def _anchor_table_cells_with_tesseract(
    regions: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> int:
    """Attach unambiguous native Tesseract word geometry to Mistral cells.

    This does not reconstruct a grid.  A cell is anchored only by OCR tokens
    that occur exactly once inside the table and therefore identify their own
    position without guessing a row or column from drawn lines.
    """
    if not words:
        return 0
    anchored = 0
    for region in regions:
        if str(region.get("region_type") or region.get("kind") or "") != "table":
            continue
        table_box = region.get("box")
        table_words = _words_in_rect(words, tuple(table_box)) if _valid_box(table_box) else list(words)
        by_token: dict[str, list[dict[str, Any]]] = {}
        for word in table_words:
            token = _anchor_token(str(word.get("text") or ""))
            if token:
                by_token.setdefault(token, []).append(word)
        for cell in region.get("cells") or []:
            if _has_trusted_cell_box(cell):
                continue
            tokens = [_anchor_token(token) for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", str(cell.get("text") or ""))]
            unique: list[dict[str, Any]] = []
            seen: set[int] = set()
            for token in tokens:
                matches = by_token.get(token) or []
                if len(matches) != 1:
                    continue
                word = matches[0]
                marker = id(word)
                if marker not in seen:
                    unique.append(word)
                    seen.add(marker)
            # Two independent anchors are required, except for a unique long
            # word that is itself a sufficiently strong positional identity.
            strong_single = len(unique) == 1 and len(_anchor_token(str(unique[0].get("text") or ""))) >= 10
            if len(unique) < 2 and not strong_single:
                continue
            boxes = [word["box"] for word in unique]
            x0 = min(float(box[0]) for box in boxes)
            y0 = min(float(box[1]) for box in boxes)
            x1 = max(float(box[0]) + float(box[2]) for box in boxes)
            y1 = max(float(box[1]) + float(box[3]) for box in boxes)
            pad_x = max(3.0, (x1 - x0) * 0.03)
            pad_y = max(3.0, (y1 - y0) * 0.12)
            cell["box"] = [
                int(max(0.0, x0 - pad_x)), int(max(0.0, y0 - pad_y)),
                int((x1 - x0) + 2 * pad_x), int((y1 - y0) + 2 * pad_y),
            ]
            cell["coordinate_source"] = "tesseract_native_alignment"
            cell["coordinate_confidence"] = 1.0
            cell["coordinate_anchor_count"] = len(unique)
            anchored += 1
    return anchored


def _anchor_token(text: str) -> str:
    return re.sub(r"[^0-9a-zа-я]", "", str(text or "").casefold().replace("ё", "е"))
