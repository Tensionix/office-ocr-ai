from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_paths import INPUT_DIR, OUTPUT_DIR, ensure_project_dirs, iter_project_files, normalized_source_relative_path
from core.tesseract_runtime import OPTIONAL_INSTALL_COMMAND, configure_pytesseract, pytesseract_config, runtime_summary

from extract_to_md import (
    CONFIG_API_KEY_GEMINI_FILE,
    CONFIG_API_KEY_OPENAI_FILE,
    get_api_key,
    gemini_model_failover_chain,
    init_gemini_client,
    init_openai_client,
    resolve_model,
)
from providers.gemini_provider import call_markdown_vision as gemini_call_markdown_vision
from providers.openai_provider import call_markdown_vision as openai_call_markdown_vision

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


SUPPORTED_INPUTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
COORDINATE_MARKER_RE = re.compile(r"\b[XYNE]\b|широт|долгот|север|восток", re.IGNORECASE)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[\s,.]\d+)?")
TABLE_SIGNAL_RE = re.compile(r"(\d+[,.]\d+|\d+\s+\d+|[|;\t])")
LOCAL_OCR_LIMITED_REASON = (
    "Tesseract not found; local OCR is limited. Page queued for manual review. "
    f"Install optional portable component with {OPTIONAL_INSTALL_COMMAND}."
)


@dataclass
class ReviewItem:
    source: str
    relative_source: str
    page: int
    kind: str
    reason: str
    text: str = ""
    confidence: float | None = None
    bbox: list[int] | None = None
    crop_path: str = ""
    resolver_status: str = "not_requested"
    resolver_result: dict[str, object] | None = None


@dataclass
class WorkbenchStats:
    files: int = 0
    pages: int = 0
    vector_text_pages: int = 0
    ocr_pages: int = 0
    review_items: int = 0
    coordinate_rows: int = 0
    tesseract_available: bool = False
    ai_provider: str = "none"
    ai_mode: str = "off"
    ai_resolved: int = 0
    ai_errors: int = 0
    safe_autofix_candidates: int = 0


def project_rel(path: Path) -> str:
    try:
        return path.relative_to(INPUT_DIR).as_posix()
    except ValueError:
        return path.name


def output_base_for(source: Path) -> Path:
    rel = normalized_source_relative_path(source)
    return OUTPUT_DIR / rel.with_suffix("")


def report_base_for(report_dir: Path, source: Path) -> Path:
    rel = normalized_source_relative_path(source).with_suffix("")
    return report_dir / "sources" / rel


def safe_float(value: object, default: float = -1.0) -> float:
    try:
        if value is None:
            return default
        result = float(str(value).strip())
        if math.isnan(result):
            return default
        return result
    except Exception:
        return default


def is_coordinate_like(text: str) -> bool:
    numbers = NUMBER_RE.findall(text)
    return len(numbers) >= 2 and bool(COORDINATE_MARKER_RE.search(text))


def is_table_like(text: str) -> bool:
    numbers = NUMBER_RE.findall(text)
    return len(numbers) >= 3 or bool(TABLE_SIGNAL_RE.search(text))


def detect_tesseract() -> tuple[bool, str]:
    try:
        configure_pytesseract()
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, (
            "Tesseract not found; local Workbench OCR is limited. "
            f"Install optional portable component with {OPTIONAL_INSTALL_COMMAND}. "
            f"Detail: pytesseract/tesseract setup failed: {exc}"
        )
    return runtime_summary()


def image_from_pdf_page(pdf_path: Path, page_index: int, dpi: int):
    import fitz
    from PIL import Image

    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def iter_image_frames(path: Path):
    from PIL import Image

    with Image.open(path) as img:
        frames = getattr(img, "n_frames", 1)
        for index in range(frames):
            img.seek(index)
            yield index, img.convert("RGB").copy()


def vector_pdf_text_pages(path: Path) -> list[tuple[int, str]]:
    if path.suffix.lower() != ".pdf":
        return []
    try:
        import fitz
    except Exception:
        return []

    pages: list[tuple[int, str]] = []
    with fitz.open(str(path)) as doc:
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append((index, text))
    return pages


def pdf_page_count(path: Path) -> int:
    try:
        import fitz

        with fitz.open(str(path)) as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def save_crop(image, bbox: list[int], target: Path) -> str:
    left, top, right, bottom = bbox
    width, height = image.size
    pad = 8
    crop_box = (
        max(0, left - pad),
        max(0, top - pad),
        min(width, right + pad),
        min(height, bottom + pad),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    image.crop(crop_box).save(target)
    return str(target)


def save_page_preview(image, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    preview = image.copy()
    preview.thumbnail((1600, 1600))
    preview.save(target)
    return str(target)


def run_tesseract(image, *, lang: str, psm: int, oem: int) -> tuple[str, list[dict[str, object]]]:
    configure_pytesseract()
    import pytesseract
    from pytesseract import Output

    config = pytesseract_config(psm=psm, oem=oem)
    text = pytesseract.image_to_string(image, lang=lang, config=config)
    data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=Output.DICT)
    words: list[dict[str, object]] = []
    count = len(data.get("text", []))
    for index in range(count):
        word = str(data["text"][index] or "").strip()
        if not word:
            continue
        conf = safe_float(data.get("conf", [])[index], default=-1)
        left = int(data.get("left", [0])[index])
        top = int(data.get("top", [0])[index])
        width = int(data.get("width", [0])[index])
        height = int(data.get("height", [0])[index])
        words.append(
            {
                "text": word,
                "confidence": conf,
                "bbox": [left, top, left + max(1, width), top + max(1, height)],
            }
        )
    return text.strip(), words


def resolver_disabled_result(item: ReviewItem, *, status: str, reason: str) -> dict[str, object]:
    item.resolver_status = status
    item.resolver_result = {
        "visible_text": None,
        "confidence": 0.0 if item.confidence is None else max(0.0, min(1.0, item.confidence / 100.0)),
        "reason": reason,
        "safe_to_autofix": False,
    }
    return item.resolver_result


def resolver_stub(item: ReviewItem, *, ai_provider: str, ai_mode: str) -> dict[str, object]:
    if ai_mode == "off" or ai_provider == "none":
        item.resolver_status = "disabled"
    elif ai_mode == "review-only":
        item.resolver_status = f"queued_for_{ai_provider}"
    else:
        item.resolver_status = "queued_for_safe_autofix"

    item.resolver_result = {
        "visible_text": None,
        "confidence": 0.0 if item.confidence is None else max(0.0, min(1.0, item.confidence / 100.0)),
        "reason": item.reason,
        "safe_to_autofix": False,
    }
    return item.resolver_result


def resolver_key_available(ai_provider: str) -> tuple[bool, str]:
    if ai_provider == "openai":
        key = get_api_key(CONFIG_API_KEY_OPENAI_FILE)
        return bool(key), "OpenAI key found" if key else f"OpenAI key not found: {CONFIG_API_KEY_OPENAI_FILE}"
    if ai_provider == "gemini":
        key = get_api_key(CONFIG_API_KEY_GEMINI_FILE)
        return bool(key), "Gemini key found" if key else f"Gemini key not found: {CONFIG_API_KEY_GEMINI_FILE}"
    return False, "AI provider is disabled."


def normalize_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    if text and not text.lstrip().startswith("{"):
        left = text.find("{")
        right = text.rfind("}")
        if left != -1 and right != -1 and right > left:
            text = text[left : right + 1]
    return text.strip()


def normalize_resolver_result(raw: dict[str, object], item: ReviewItem) -> dict[str, object]:
    visible_text = raw.get("visible_text")
    if visible_text is not None:
        visible_text = " ".join(str(visible_text).split()).strip() or None

    confidence = safe_float(raw.get("confidence"), default=0.0)
    if confidence > 1.0 and confidence <= 100.0:
        confidence = confidence / 100.0
    confidence = max(0.0, min(1.0, confidence))

    reason = str(raw.get("reason") or "").strip()
    if not reason:
        reason = "Resolver returned a structured result."

    safe_to_autofix = bool(raw.get("safe_to_autofix", False))
    if not visible_text or confidence < 0.85:
        safe_to_autofix = False
    if item.kind == "ocr_engine_missing":
        safe_to_autofix = False

    return {
        "visible_text": visible_text,
        "confidence": confidence,
        "reason": reason,
        "safe_to_autofix": safe_to_autofix,
    }


def build_resolver_prompt(item: ReviewItem) -> str:
    return (
        "You are a repair-only OCR resolver for one small crop from an office document.\n"
        "Return only a JSON object with this exact schema:\n"
        '{"visible_text": string|null, "confidence": number, "reason": string, "safe_to_autofix": boolean}\n'
        "Rules:\n"
        "- Read only characters that are visually present in the image crop.\n"
        "- Do not infer names, coordinates, numbers, or table values from context.\n"
        "- Use null when the crop is too unclear or not enough visual evidence is present.\n"
        "- confidence must be from 0.0 to 1.0.\n"
        "- safe_to_autofix may be true only for an unambiguous short correction.\n\n"
        f"Source: {item.relative_source}\n"
        f"Page: {item.page}\n"
        f"Heuristic kind: {item.kind}\n"
        f"Heuristic reason: {item.reason}\n"
        f"Local OCR text: {item.text or '[empty]'}\n"
        f"Local OCR confidence: {item.confidence if item.confidence is not None else '[unknown]'}\n"
    )


def call_openai_resolver(item: ReviewItem, *, model: str) -> dict[str, object]:
    client = init_openai_client()
    resolved_model = resolve_model("openai", model)
    crop = Path(item.crop_path)
    doc_hash = hashlib.sha256(f"{item.relative_source}|{item.page}|{item.kind}|{item.text}".encode("utf-8")).hexdigest()
    raw, _usage, _tier = openai_call_markdown_vision(
        client,
        model=resolved_model,
        instructions="Resolve a doubtful OCR crop and return only a strict JSON object.",
        user_prompt=build_resolver_prompt(item),
        image_paths=[str(crop)],
        reasoning_effort="minimal",
        max_output_tokens=700,
        timeout_sec=75.0,
        max_retries=3,
        service_tier="auto",
        use_idempotency=True,
        doc_hash=doc_hash,
        chunk_index=0,
        verbosity="low",
    )
    return normalize_resolver_result(json.loads(normalize_json_text(raw)), item)


def call_gemini_resolver(item: ReviewItem, *, model: str) -> dict[str, object]:
    client = init_gemini_client()
    resolved_model = resolve_model("gemini", model)
    raw, _usage, _route = gemini_call_markdown_vision(
        client,
        model=resolved_model,
        model_chain=gemini_model_failover_chain(model, resolved_model),
        system_instruction="Resolve a doubtful OCR crop and return only a strict JSON object.",
        user_prompt=build_resolver_prompt(item),
        image_paths=[item.crop_path],
        temperature=0.0,
        timeout_sec=75.0,
        deadline_monotonic=time.monotonic() + 75.0,
        max_retries=3,
        sleep_after_sec=0.0,
    )
    return normalize_resolver_result(json.loads(normalize_json_text(raw)), item)


def resolve_review_items(
    items: list[ReviewItem],
    *,
    ai_provider: str,
    ai_mode: str,
    model: str,
    resolver_limit: int,
) -> dict[str, int]:
    counts = {"resolved": 0, "errors": 0, "safe_autofix_candidates": 0}
    if ai_mode == "off" or ai_provider == "none":
        for item in items:
            resolver_disabled_result(item, status="disabled", reason="AI resolver is disabled.")
        return counts

    key_available, key_note = resolver_key_available(ai_provider)
    print(f"[RESOLVER] {ai_provider}: {key_note}; crop limit={resolver_limit}")
    if not key_available:
        for item in items:
            resolver_disabled_result(item, status=f"queued_for_{ai_provider}", reason=key_note)
        return counts

    attempted = 0
    for item in items:
        crop = Path(item.crop_path) if item.crop_path else None
        if not crop or not crop.exists():
            resolver_disabled_result(item, status="manual_review_no_crop", reason="No crop is available for AI resolver.")
            continue
        if item.kind == "ocr_engine_missing":
            resolver_disabled_result(
                item,
                status="manual_review_needs_local_ocr",
                reason="Whole-page OCR is intentionally not sent to the repair-only resolver.",
            )
            continue
        if resolver_limit >= 0 and attempted >= resolver_limit:
            resolver_stub(item, ai_provider=ai_provider, ai_mode=ai_mode)
            continue

        attempted += 1
        try:
            if ai_provider == "openai":
                result = call_openai_resolver(item, model=model)
            elif ai_provider == "gemini":
                result = call_gemini_resolver(item, model=model)
            else:
                raise RuntimeError(f"Unsupported resolver provider: {ai_provider}")

            item.resolver_result = result
            if result.get("visible_text"):
                counts["resolved"] += 1
                item.resolver_status = "resolved_review"
            else:
                item.resolver_status = "unresolved_review"

            if ai_mode == "auto-fix-safe" and bool(result.get("safe_to_autofix", False)):
                counts["safe_autofix_candidates"] += 1
                item.resolver_status = "safe_autofix_candidate"
            elif ai_mode != "auto-fix-safe":
                result["safe_to_autofix"] = False
        except Exception as exc:
            counts["errors"] += 1
            resolver_disabled_result(
                item,
                status="resolver_error",
                reason=f"{exc.__class__.__name__}: {str(exc)[:240]}",
            )

    return counts


def write_manual_review_xlsx(path: Path, items: list[ReviewItem]) -> None:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "manual_review"
    headers = [
        "source",
        "page",
        "kind",
        "reason",
        "text",
        "confidence",
        "bbox",
        "crop_path",
        "resolver_status",
        "visible_text",
        "resolver_confidence",
        "resolver_reason",
        "safe_to_autofix",
    ]
    sheet.append(headers)
    for item in items:
        result = item.resolver_result or {}
        sheet.append(
            [
                item.relative_source,
                item.page,
                item.kind,
                item.reason,
                item.text,
                item.confidence,
                json.dumps(item.bbox, ensure_ascii=False) if item.bbox else "",
                item.crop_path,
                item.resolver_status,
                result.get("visible_text"),
                result.get("confidence"),
                result.get("reason"),
                result.get("safe_to_autofix"),
            ]
        )
    for column in sheet.columns:
        width = min(60, max(10, max(len(str(cell.value or "")) for cell in column) + 2))
        sheet.column_dimensions[column[0].column_letter].width = width
    workbook.save(path)


def write_coordinates_xlsx(path: Path, rows: list[dict[str, object]]) -> None:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "coordinates"
    sheet.append(["source", "page", "line", "numbers", "raw_text"])
    for row in rows:
        sheet.append(
            [
                row.get("source"),
                row.get("page"),
                row.get("line"),
                ", ".join(row.get("numbers", [])),
                row.get("raw_text"),
            ]
        )
    workbook.save(path)


def process_file(
    source: Path,
    *,
    mode: str,
    report_dir: Path,
    lang: str,
    psm: int,
    oem: int,
    dpi: int,
    low_confidence: float,
    tesseract_available: bool,
    tesseract_note: str,
    ai_provider: str,
    ai_mode: str,
    model: str,
    resolver_limit: int,
) -> tuple[list[ReviewItem], list[dict[str, object]], WorkbenchStats]:
    stats = WorkbenchStats(files=1, tesseract_available=tesseract_available, ai_provider=ai_provider, ai_mode=ai_mode)
    review_items: list[ReviewItem] = []
    coordinate_rows: list[dict[str, object]] = []
    rel_source = project_rel(source)
    report_base = report_base_for(report_dir, source)
    output_base = output_base_for(source)
    output_base.mkdir(parents=True, exist_ok=True)

    page_lines: list[tuple[int, str]] = []
    vector_pages = vector_pdf_text_pages(source)
    if vector_pages:
        stats.vector_text_pages += len(vector_pages)
        page_lines.extend(vector_pages)

    needs_raster_ocr = mode in {"auto", "review", "ai-review", "coordinates"} and (
        source.suffix.lower() != ".pdf" or not vector_pages
    )

    if needs_raster_ocr:
        page_images: list[tuple[int, Any]] = []
        if source.suffix.lower() == ".pdf":
            count = pdf_page_count(source)
            for page_index in range(count):
                page_images.append((page_index + 1, image_from_pdf_page(source, page_index, dpi)))
        else:
            for frame_index, image in iter_image_frames(source):
                page_images.append((frame_index + 1, image))

        for page_number, image in page_images:
            stats.pages += 1
            if not tesseract_available:
                crop_path = save_page_preview(
                    image,
                    report_base / "crops" / f"page_{page_number:04d}_no_ocr_engine.png",
                )
                review_items.append(
                    ReviewItem(
                        source=str(source),
                        relative_source=rel_source,
                        page=page_number,
                        kind="ocr_engine_missing",
                        reason=f"{LOCAL_OCR_LIMITED_REASON} Detail: {tesseract_note}",
                        crop_path=crop_path,
                    )
                )
                continue

            text, words = run_tesseract(image, lang=lang, psm=psm, oem=oem)
            stats.ocr_pages += 1
            if text:
                page_lines.append((page_number, text))
            for word_index, word in enumerate(words):
                confidence = float(word["confidence"])
                if confidence < 0 or confidence >= low_confidence:
                    continue
                bbox = list(word["bbox"])  # type: ignore[arg-type]
                crop_path = save_crop(
                    image,
                    bbox,
                    report_base / "crops" / f"page_{page_number:04d}_low_conf_{word_index:04d}.png",
                )
                review_items.append(
                    ReviewItem(
                        source=str(source),
                        relative_source=rel_source,
                        page=page_number,
                        kind="low_confidence",
                        reason=f"Tesseract confidence below {low_confidence:g}.",
                        text=str(word["text"]),
                        confidence=confidence,
                        bbox=bbox,
                        crop_path=crop_path,
                    )
                )

    if source.suffix.lower() == ".pdf" and not needs_raster_ocr:
        stats.pages += max(len(vector_pages), pdf_page_count(source))
    elif source.suffix.lower() != ".pdf" and not needs_raster_ocr:
        stats.pages += 1

    line_number = 0
    for page_number, text in page_lines:
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            line_number += 1
            if is_coordinate_like(line):
                coordinate_rows.append(
                    {
                        "source": rel_source,
                        "page": page_number,
                        "line": line_number,
                        "numbers": NUMBER_RE.findall(line),
                        "raw_text": line,
                    }
                )
            elif mode in {"review", "ai-review", "auto"} and is_table_like(line) and len(line) > 180:
                review_items.append(
                    ReviewItem(
                        source=str(source),
                        relative_source=rel_source,
                        page=page_number,
                        kind="wide_table_like_line",
                        reason="Long numeric/table-like line should be checked before XLSX export.",
                        text=line[:500],
                    )
                )

    resolver_counts = resolve_review_items(
        review_items,
        ai_provider=ai_provider,
        ai_mode=ai_mode,
        model=model,
        resolver_limit=resolver_limit,
    )

    stats.review_items = len(review_items)
    stats.coordinate_rows = len(coordinate_rows)
    stats.ai_resolved = resolver_counts["resolved"]
    stats.ai_errors = resolver_counts["errors"]
    stats.safe_autofix_candidates = resolver_counts["safe_autofix_candidates"]
    return review_items, coordinate_rows, stats


def run_workbench(args: argparse.Namespace) -> int:
    ensure_project_dirs()
    report_dir = Path(args.report_dir).resolve() if args.report_dir else (Path("report") / "workbench").resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    tesseract_available, tesseract_note = detect_tesseract()
    local_ocr_status = "available" if tesseract_available else "limited"
    if args.ocr_engine == "disabled":
        tesseract_available = False
        local_ocr_status = "disabled"
        tesseract_note = "Local OCR disabled by user."
    elif not tesseract_available:
        print(f"[LOCAL OCR LIMITED] {tesseract_note}")

    files = iter_project_files(SUPPORTED_INPUTS)
    stats_total = WorkbenchStats(tesseract_available=tesseract_available, ai_provider=args.ai_provider, ai_mode=args.ai_mode)
    all_review_items: list[ReviewItem] = []
    all_coordinate_rows: list[dict[str, object]] = []

    print("=== AUDION PYTHON OCR WORKBENCH ===")
    print(f"Mode: {args.mode}")
    print(f"Local OCR: {local_ocr_status} - {tesseract_note}")
    print(f"AI resolver: provider={args.ai_provider}, mode={args.ai_mode}")
    print(f"Input files: {len(files)}")

    for index, source in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] {project_rel(source)}")
        review_items, coordinate_rows, stats = process_file(
            source,
            mode=args.mode,
            report_dir=report_dir,
            lang=args.lang,
            psm=args.psm,
            oem=args.oem,
            dpi=args.dpi,
            low_confidence=args.low_confidence,
            tesseract_available=tesseract_available,
            tesseract_note=tesseract_note,
            ai_provider=args.ai_provider,
            ai_mode=args.ai_mode,
            model=args.model,
            resolver_limit=args.resolver_limit,
        )
        all_review_items.extend(review_items)
        all_coordinate_rows.extend(coordinate_rows)
        stats_total.files += stats.files
        stats_total.pages += stats.pages
        stats_total.vector_text_pages += stats.vector_text_pages
        stats_total.ocr_pages += stats.ocr_pages
        stats_total.review_items += stats.review_items
        stats_total.coordinate_rows += stats.coordinate_rows
        stats_total.ai_resolved += stats.ai_resolved
        stats_total.ai_errors += stats.ai_errors
        stats_total.safe_autofix_candidates += stats.safe_autofix_candidates

    if all_review_items:
        write_manual_review_xlsx(report_dir / "manual_review.xlsx", all_review_items)
    if all_coordinate_rows:
        write_coordinates_xlsx(OUTPUT_DIR / "workbench_coordinates.xlsx", all_coordinate_rows)
        write_coordinates_xlsx(report_dir / "coordinates.xlsx", all_coordinate_rows)

    safe_candidates = [
        asdict(item)
        for item in all_review_items
        if item.resolver_status == "safe_autofix_candidate"
    ]

    summary = {
        **asdict(stats_total),
        "mode": args.mode,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "local_ocr_status": local_ocr_status,
        "optional_tesseract_install": OPTIONAL_INSTALL_COMMAND,
        "tesseract_note": tesseract_note,
        "manual_review_xlsx": str(report_dir / "manual_review.xlsx") if all_review_items else "",
        "coordinates_xlsx": str(OUTPUT_DIR / "workbench_coordinates.xlsx") if all_coordinate_rows else "",
        "safe_autofix_candidates_json": str(report_dir / "safe_autofix_candidates.json") if safe_candidates else "",
    }
    (report_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / "review_items.json").write_text(
        json.dumps([asdict(item) for item in all_review_items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_dir / "resolver_candidates.json").write_text(
        json.dumps([asdict(item) for item in all_review_items if item.resolver_status != "disabled"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_dir / "safe_autofix_candidates.json").write_text(
        json.dumps(safe_candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] Report: {report_dir}")
    if all_review_items:
        print(f"[REVIEW] {len(all_review_items)} item(s): {report_dir / 'manual_review.xlsx'}")
    if safe_candidates:
        print(f"[SAFE AUTOFIX] {len(safe_candidates)} candidate(s): {report_dir / 'safe_autofix_candidates.json'}")
    if all_coordinate_rows:
        print(f"[COORDINATES] {len(all_coordinate_rows)} row(s): {OUTPUT_DIR / 'workbench_coordinates.xlsx'}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adjacent Python OCR workbench and AI-resolver queue.")
    parser.add_argument("--mode", choices=["auto", "review", "ai-review", "coordinates"], default="review")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--ocr-engine", choices=["auto", "tesseract", "disabled"], default="auto")
    parser.add_argument("--lang", default="rus+eng")
    parser.add_argument("--psm", type=int, default=6)
    parser.add_argument("--oem", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--low-confidence", type=float, default=70.0)
    parser.add_argument("--ai-provider", choices=["none", "openai", "gemini"], default="none")
    parser.add_argument("--ai-mode", choices=["off", "review-only", "auto-fix-safe"], default="off")
    parser.add_argument("--model", default="auto")
    parser.add_argument(
        "--resolver-limit",
        type=int,
        default=-1,
        help="Maximum suspicious crops to send to the selected AI resolver; default -1 sends all suspicious crops.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_workbench(parse_args()))
