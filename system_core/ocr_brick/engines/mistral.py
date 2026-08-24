# engines/mistral.py
# Mistral OCR 4 adapter. Uses the dedicated /v1/ocr endpoint and preserves
# Markdown, typed blocks, tables and page confidence without an SDK dependency.

from __future__ import annotations

import base64
import json
import random
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from .base import OcrResult
from .regions import Cell, FigureRegion, LayoutResult, TableRegion, TextRegion


_OCR_URL = "https://api.mistral.ai/v1/ocr"
_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504, 520, 522, 524}


class MistralOCRAdapter:
    kind = "mistral"
    provides_layout = True

    def __init__(
        self,
        api_key_file: str | Path,
        *,
        timeout: float = 180.0,
        max_attempts: int = 4,
    ) -> None:
        self.api_key_file = Path(api_key_file)
        self.timeout = float(timeout)
        self.max_attempts = max(1, int(max_attempts))
        self.last_usage: dict[str, Any] = {}
        self.last_page: dict[str, Any] = {}

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        payload = self._process(clean_png_path, params)
        page = self._first_page(payload)
        text = _page_markdown(page)
        self._validate_text(text)
        return OcrResult(
            kind="mistral",
            text=text,
            words=[],
            may_rewrite=False,
            engine="mistral",
        )

    def analyze_layout(self, clean_png_path: str, page: int = 0, params: dict | None = None) -> LayoutResult:
        call_params = dict(params or {})
        call_params["include_blocks"] = True
        call_params.setdefault("table_format", "html")
        payload = self._process(clean_png_path, call_params)
        raw_page = self._first_page(payload)
        return layout_from_mistral_page(raw_page, page=page, usage_info=self.last_usage)


    def _process(self, image_path: str, params: dict) -> dict[str, Any]:
        key_file = Path(str(params.get("api_key_file") or self.api_key_file))
        api_key = _read_key(key_file)
        if not api_key:
            raise RuntimeError(f"Mistral API key is empty or missing: {key_file}")

        model = str(params.get("model") or "mistral-ocr-4-0").strip()
        image = Path(image_path)
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        data_url = f"data:{mime};base64,{base64.b64encode(image.read_bytes()).decode('ascii')}"
        body = {
            "model": model,
            "document": {"type": "image_url", "image_url": data_url},
            "include_blocks": bool(params.get("include_blocks", True)),
            "table_format": str(params.get("table_format") or "html"),
            "confidence_scores_granularity": str(params.get("confidence_granularity") or "word"),
            "extract_header": bool(params.get("extract_header", False)),
            "extract_footer": bool(params.get("extract_footer", False)),
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.post(
                    _OCR_URL,
                    headers=headers,
                    json=body,
                    timeout=(min(20.0, self.timeout), self.timeout),
                )
                if response.status_code in _TRANSIENT_STATUSES and attempt < self.max_attempts:
                    _sleep_before_retry(response, attempt)
                    continue
                if response.status_code >= 400:
                    detail = response.text[:1000].replace(api_key, "[redacted]")
                    raise RuntimeError(f"Mistral OCR failed with HTTP {response.status_code}: {detail}")
                decoded = response.content.decode("utf-8", "strict")
                payload = json.loads(decoded)
                if not isinstance(payload, dict):
                    raise ValueError("Mistral OCR returned a non-object JSON response")
                page = self._first_page(payload)
                self._validate_text(str(page.get("markdown") or ""))
                self.last_usage = payload.get("usage_info") if isinstance(payload.get("usage_info"), dict) else {}
                self.last_page = page
                return payload
            except (requests.ConnectionError, requests.Timeout, UnicodeError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                time.sleep(min(20.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.35))
        raise RuntimeError(f"Mistral OCR failed after {self.max_attempts} attempts: {last_error}") from last_error

    @staticmethod
    def _first_page(payload: dict[str, Any]) -> dict[str, Any]:
        pages = payload.get("pages")
        if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
            raise RuntimeError("Mistral OCR response contains no pages")
        return pages[0]

    @staticmethod
    def _validate_text(text: str) -> None:
        if "\ufffd" in text:
            raise UnicodeError("Mistral OCR response contains Unicode replacement characters")


def layout_from_mistral_page(
    raw_page: dict[str, Any],
    *,
    page: int = 0,
    usage_info: dict[str, Any] | None = None,
) -> LayoutResult:
    """Convert a saved OCR 4 page to the common layout model without an API call."""
    width, height = _dimensions(raw_page)
    result = LayoutResult(
        page=page,
        width=width,
        height=height,
        engine="mistral",
        metadata={
            "confidence_scores": raw_page.get("confidence_scores") or {},
            "usage_info": dict(usage_info or {}),
        },
    )
    tables = _tables_by_id(raw_page.get("tables"))

    for block in raw_page.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "text").strip().lower()
        box = _block_box(block, width, height)
        content = str(block.get("content") or "").strip()
        if block_type == "table":
            table = tables.get(str(block.get("table_id") or block.get("id") or ""))
            table_content = _table_content(table) or content
            parsed = _parse_html_table(table_content, box)
            if parsed is not None:
                result.regions.append(parsed)
            elif table_content:
                result.regions.append(TextRegion(text=table_content, box=box, kind="table"))
            continue
        if block_type == "image":
            result.regions.append(FigureRegion(box=box))
            continue
        if not content:
            continue
        kind = {
            "title": "heading",
            "caption": "caption",
            "equation": "equation",
            "header": "header",
            "footer": "footer",
            "signature": "signature",
            "list": "list",
            "code": "code",
            "references": "references",
            "aside_text": "aside_text",
        }.get(block_type, "paragraph")
        result.regions.append(TextRegion(text=content, box=box, kind=kind))
    return result


def _read_key(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def _sleep_before_retry(response: requests.Response, attempt: int) -> None:
    retry_after = response.headers.get("Retry-After", "")
    delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else min(20.0, 1.5 * (2 ** (attempt - 1)))
    time.sleep(delay + random.uniform(0.0, 0.35))


def _dimensions(page: dict[str, Any]) -> tuple[int, int]:
    dims = page.get("dimensions") if isinstance(page.get("dimensions"), dict) else {}
    width = int(float(dims.get("width") or dims.get("pixel_width") or 0))
    height = int(float(dims.get("height") or dims.get("pixel_height") or 0))
    return width, height


def _block_box(block: dict[str, Any], width: int, height: int):
    try:
        x0 = float(block.get("top_left_x", 0))
        y0 = float(block.get("top_left_y", 0))
        x1 = float(block.get("bottom_right_x", x0))
        y1 = float(block.get("bottom_right_y", y0))
    except (TypeError, ValueError):
        return None
    # OCR 4 API currently returns pixel coordinates. Retain compatibility with
    # deployments that may normalize them to the 0..1 range.
    if width > 0 and height > 0 and max(abs(x0), abs(x1), abs(y0), abs(y1)) <= 1.5:
        x0, x1 = x0 * width, x1 * width
        y0, y1 = y0 * height, y1 * height
    return (int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))


def _tables_by_id(raw: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for index, table in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("id") or table.get("table_id") or f"table-{index}")
        out[table_id] = table
    return out


def _table_content(table: dict[str, Any] | None) -> str:
    if not table:
        return ""
    return str(table.get("content") or table.get("html") or table.get("markdown") or "").strip()


def _page_markdown(page: dict[str, Any]) -> str:
    """Return self-contained UTF-8 Markdown instead of unresolved OCR attachments."""
    text = _repair_cp1251_utf8_mojibake(str(page.get("markdown") or ""))
    for table_id, table in _tables_by_id(page.get("tables")).items():
        content = _table_content(table)
        if not content:
            continue
        link = f"[{table_id}]({table_id})"
        if link in text:
            text = text.replace(link, content)
        elif content not in text:
            text = f"{text.rstrip()}\n\n{content}".strip()
    return text.strip()


def _repair_cp1251_utf8_mojibake(text: str) -> str:
    """Repair UTF-8 bytes decoded as CP1251 only when the evidence is strong."""
    markers = ("Рџ", "РЎ", "Рё", "Рµ", "Р°", "РЅ", "С‚", "СЂ", "СЏ", "СЊ")
    before = sum(text.count(marker) for marker in markers)
    if before < 3:
        return text
    try:
        candidate = text.encode("cp1251", "strict").decode("utf-8", "strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    after = sum(candidate.count(marker) for marker in markers)
    return candidate if after * 3 < before else text


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int, int]]] = []
        self._row: list[tuple[str, int, int]] | None = None
        self._cell: list[str] | None = None
        self._rowspan = 1
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            values = {str(k).lower(): str(v) for k, v in attrs}
            self._rowspan = max(1, int(values.get("rowspan", "1") or 1))
            self._colspan = max(1, int(values.get("colspan", "1") or 1))
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell).split())
            self._row.append((text, self._rowspan, self._colspan))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _parse_html_table(content: str, box) -> TableRegion | None:
    if "<table" not in content.lower():
        return None
    parser = _TableParser()
    parser.feed(content)
    if not parser.rows:
        return None
    occupied: set[tuple[int, int]] = set()
    cells: list[Cell] = []
    max_col = 0
    for row_index, row in enumerate(parser.rows):
        col = 0
        for text, rowspan, colspan in row:
            while (row_index, col) in occupied:
                col += 1
            cells.append(Cell(text=text, row=row_index, col=col, rowspan=rowspan, colspan=colspan))
            for rr in range(row_index, row_index + rowspan):
                for cc in range(col, col + colspan):
                    occupied.add((rr, cc))
            col += colspan
            max_col = max(max_col, col)
    return TableRegion(rows=len(parser.rows), cols=max_col, cells=cells, box=box)
