# numeric_check.py
# Post-OCR verifier for legal/financial identifiers. It crops numeric-heavy
# lines and asks a small vision model to read only visible identifiers exactly.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from . import cleanconfig, preprocess
from .cache import Cache
from .engines.surya import SuryaAdapter
from .engines.tesseract import TesseractAdapter
from .engines.xai import XAIAdapter


KEYWORD_RE = re.compile(
    r"(контракт|договор|закупк|идентификационн|икз|инн|кпп|бик|"
    r"счет|сч[её]т|р/с|л/с|к/с|казначейск|протокол|акт|"
    r"сумм|цена|ндс|руб|коп|номер|№)",
    re.IGNORECASE,
)
DIGIT_RE = re.compile(r"\d")
JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

NUMERIC_PROMPT = """
You are verifying a cropped line from a legal or financial document.

Read only what is visible in the crop. Preserve every digit, zero, slash,
dash, dot, quote, and "№" exactly as printed. Do not infer missing digits.
If a digit is unclear, put "?" at that exact position.

Return JSON only, no Markdown:
{
  "items": [
    {"label": "short visible label or identifier type", "value": "exact visible number or identifier"}
  ],
  "raw": "exact visible text from the crop"
}
""".strip()


@dataclass
class Candidate:
    id: int
    kind: str
    text: str
    crop: str
    box: tuple[int, int, int, int]
    digits: int


@dataclass
class Verification:
    candidate_id: int
    provider: str
    model: str
    text: str
    parsed: dict[str, Any]
    status: str
    locator_digit_sequences: list[str]
    verified_digit_sequences: list[str]
    usage: dict[str, Any]
    cost_usd_estimate: float | None
    elapsed_sec: float


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def _arg_path(root: Path, raw: object, default: Path) -> Path:
    text = str(raw or "").strip().strip('"')
    if not text:
        return default
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _usage_cost_usd_estimate(usage: dict[str, Any]) -> float | None:
    raw_ticks = usage.get("cost_in_usd_ticks") if isinstance(usage, dict) else None
    try:
        ticks = float(raw_ticks)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return ticks / 10_000_000_000


def _make_numeric_image(path: Path) -> Path:
    image = Image.open(path).convert("L")
    image = ImageOps.autocontrast(image, cutoff=0.25)
    image = ImageEnhance.Contrast(image).enhance(1.55)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=230, threshold=2))
    image = image.convert("RGB")
    out = path.with_name(path.stem + "_numeric.png")
    image.save(out)
    return out


def _digit_count(text: str) -> int:
    return len(DIGIT_RE.findall(text or ""))


def _line_kind(text: str) -> str:
    lowered = text.lower()
    if "идентификацион" in lowered or "икз" in lowered:
        return "purchase_id"
    if "контракт" in lowered or "договор" in lowered:
        return "contract_number"
    if "инн" in lowered or "кпп" in lowered:
        return "tax_id"
    if "бик" in lowered or "счет" in lowered or "счёт" in lowered or "р/с" in lowered or "л/с" in lowered or "к/с" in lowered:
        return "bank_details"
    if "протокол" in lowered or "акт" in lowered:
        return "document_number"
    if "цена" in lowered or "сумм" in lowered or "руб" in lowered or "коп" in lowered:
        return "money"
    return "long_number"


def _group_words_into_lines(words: list[Any]) -> list[list[Any]]:
    items = [word for word in words if getattr(word, "text", "").strip() and getattr(word, "box", None)]
    items.sort(key=lambda word: (word.box[1] + word.box[3] / 2.0, word.box[0]))
    lines: list[list[Any]] = []
    centers: list[float] = []
    for word in items:
        x, y, _w, h = word.box
        center = y + h / 2.0
        best_index = -1
        best_delta = 10**9
        for index, line_center in enumerate(centers):
            delta = abs(center - line_center)
            if delta < best_delta:
                best_index = index
                best_delta = delta
        threshold = max(8.0, h * 0.72)
        if best_index >= 0 and best_delta <= threshold:
            lines[best_index].append(word)
            centers[best_index] = sum(item.box[1] + item.box[3] / 2.0 for item in lines[best_index]) / len(lines[best_index])
        else:
            lines.append([word])
            centers.append(center)
    for line in lines:
        line.sort(key=lambda word: word.box[0])
    lines.sort(key=lambda line: min(word.box[1] for word in line))
    return lines


def _candidate_lines(words: list[Any], min_digits: int, max_candidates: int) -> list[tuple[str, str, tuple[int, int, int, int], int]]:
    candidates: list[tuple[str, str, tuple[int, int, int, int], int]] = []
    for line in _group_words_into_lines(words):
        text = " ".join(str(getattr(word, "text", "")).strip() for word in line if str(getattr(word, "text", "")).strip())
        digits = _digit_count(text)
        if digits < min_digits and not (digits >= 4 and KEYWORD_RE.search(text)):
            continue
        if digits < 4:
            continue
        xs = [word.box[0] for word in line]
        ys = [word.box[1] for word in line]
        rights = [word.box[0] + word.box[2] for word in line]
        bottoms = [word.box[1] + word.box[3] for word in line]
        box = (min(xs), min(ys), max(rights) - min(xs), max(bottoms) - min(ys))
        candidates.append((_line_kind(text), text, box, digits))

    def rank(item: tuple[str, str, tuple[int, int, int, int], int]) -> tuple[int, int]:
        kind, text, _box, digits = item
        keyword_bonus = 100 if KEYWORD_RE.search(text) else 0
        kind_bonus = 50 if kind != "long_number" else 0
        return (keyword_bonus + kind_bonus + digits, digits)

    candidates.sort(key=rank, reverse=True)
    deduped: list[tuple[str, str, tuple[int, int, int, int], int]] = []
    seen_y: list[int] = []
    for item in candidates:
        y = item[2][1]
        if any(abs(y - prev) < 8 for prev in seen_y):
            continue
        deduped.append(item)
        seen_y.append(y)
        if len(deduped) >= max_candidates:
            break
    return deduped


def _crop_candidate(image_path: Path, box: tuple[int, int, int, int], out_path: Path, padding: int = 22) -> tuple[int, int, int, int]:
    image = Image.open(image_path).convert("RGB")
    x, y, w, h = box
    pad_y = max(padding, int(h * 1.4))
    pad_x = max(padding, int(h * 2.2))
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(image.width, x + w + pad_x)
    bottom = min(image.height, y + h + pad_y)
    crop = image.crop((left, top, right, bottom))
    if crop.width < 1200:
        scale = min(4.0, 1200 / max(1, crop.width))
        crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.Resampling.LANCZOS)
        crop = crop.filter(ImageFilter.UnsharpMask(radius=1.0, percent=170, threshold=2))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out_path)
    return (left, top, right - left, bottom - top)


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"raw": raw, "items": []}
    except json.JSONDecodeError:
        match = JSON_OBJECT_RE.search(raw)
        if match:
            try:
                payload = json.loads(match.group(0))
                return payload if isinstance(payload, dict) else {"raw": raw, "items": []}
            except json.JSONDecodeError:
                pass
    return {"raw": raw, "items": []}


def _digit_sequences(text: str) -> list[str]:
    return re.findall(r"\d[\d .\-/]{2,}\d|\d{4,}", text or "")


def _normalize_digits(value: str) -> str:
    return "".join(DIGIT_RE.findall(value or ""))


def _parsed_value_text(parsed: dict[str, Any], raw_text: str) -> str:
    pieces: list[str] = []
    items = parsed.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                pieces.append(str(item.get("value") or ""))
                pieces.append(str(item.get("raw") or ""))
    pieces.append(str(parsed.get("raw") or ""))
    pieces.append(raw_text)
    return "\n".join(piece for piece in pieces if piece)


def _comparison_status(locator_text: str, parsed: dict[str, Any], raw_text: str) -> tuple[str, list[str], list[str]]:
    locator_sequences = [_normalize_digits(value) for value in _digit_sequences(locator_text)]
    verified_sequences = [_normalize_digits(value) for value in _digit_sequences(_parsed_value_text(parsed, raw_text))]
    locator_sequences = [value for value in locator_sequences if len(value) >= 4]
    verified_sequences = [value for value in verified_sequences if len(value) >= 4]
    locator_sequences = list(dict.fromkeys(locator_sequences))
    verified_sequences = list(dict.fromkeys(verified_sequences))
    critical_locator = [value for value in locator_sequences if len(value) >= 12]
    critical_verified = [value for value in verified_sequences if len(value) >= 12]

    if "?" in raw_text:
        return "uncertain", locator_sequences, verified_sequences
    if not locator_sequences and not verified_sequences:
        return "no_digits", locator_sequences, verified_sequences
    if critical_locator:
        if any(value in critical_verified for value in critical_locator):
            return "match", locator_sequences, verified_sequences
        if critical_verified:
            return "mismatch", locator_sequences, verified_sequences
        return "locator_only", locator_sequences, verified_sequences
    if critical_verified and not critical_locator:
        return "verifier_only", locator_sequences, verified_sequences
    if locator_sequences and any(value in verified_sequences for value in locator_sequences):
        return "match", locator_sequences, verified_sequences
    if locator_sequences and verified_sequences:
        return "mismatch", locator_sequences, verified_sequences
    if locator_sequences:
        return "locator_only", locator_sequences, verified_sequences
    return "verifier_only", locator_sequences, verified_sequences


def _prompt_for_candidate(base_prompt: str, candidate: Candidate, *, locator_hint: bool) -> str:
    if candidate.kind == "vision_page":
        return (
            f"{base_prompt}\n\n"
            "This image may be a full page fallback because no local OCR line locator was available. "
            "Extract only visible legal/financial numeric identifiers from the page: contract numbers, "
            "purchase IDs, INN/KPP, account numbers, dates, sums, act/protocol numbers. Do not summarize."
        )
    if not locator_hint:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        "Rough local OCR hypothesis for this crop follows. Treat it as a hypothesis, "
        "not as truth. If the image agrees, preserve the exact digits from this "
        "hypothesis; if the image disagrees, correct it from the image only.\n"
        f"LOCAL_OCR_HYPOTHESIS: {candidate.text}"
    )


def _verify_xai(crop_path: Path, model: str, key_file: Path, prompt: str) -> tuple[str, dict[str, Any], float | None]:
    adapter = XAIAdapter(key_file, timeout=120.0)
    result = adapter.recognize(
        str(crop_path),
        {
            "model": model,
            "api_key_file": str(key_file),
            "prompt": prompt,
        },
    )
    usage = adapter.last_usage if isinstance(adapter.last_usage, dict) else {}
    return result.text, usage, _usage_cost_usd_estimate(usage)


def _full_page_candidate(numeric_page: Path, source: Path, page_number: int, crops_dir: Path) -> Candidate:
    image = Image.open(numeric_page).convert("RGB")
    crop_path = crops_dir / f"{source.stem}_page{page_number}_candidate_01_vision_page.png"
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(crop_path)
    return Candidate(1, "vision_page", "", str(crop_path), (0, 0, image.width, image.height), 0)


def _surya_python(root: Path) -> Path:
    return root / "tools" / "optional-ocr-engines" / "surya" / "runtime" / "python.exe"


def run_numeric_check(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    source = Path(args.source).resolve()
    out_dir = Path(args.out).resolve() if args.out else root / "workspace" / "numeric_check"
    out_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = out_dir / "crops"

    pages = preprocess.rasterize(source, dpi=int(args.dpi))
    page_index = max(0, min(int(args.page) - 1, len(pages) - 1))
    page_png = pages[page_index]

    profiles = cleanconfig.load_profiles(root / "system_core" / "ocr_brick" / "preprocess.profiles.json")
    cfg = cleanconfig.resolve(
        profiles,
        target_engine="vision",
        gui_overrides={
            "enabled": True,
            "sr_scale": 0,
            "denoise": str(args.denoise),
            "contrast": str(args.contrast),
            "unsharp": str(args.unsharp),
            "binarize": str(args.binarize),
            "deskew": bool(args.deskew),
            "intent": "text",
            "source_format": "auto",
        },
        original_name=str(source),
    )
    cache = Cache(root / "cache" / "numeric_check", max_bytes=2 * 1024**3)
    numeric_png = preprocess.clean_page(page_png, cfg, cache=cache, sr=None)

    locator_mode = str(getattr(args, "locator", "auto") or "auto").strip().lower().replace("_", "-")
    if locator_mode not in {"auto", "tesseract", "surya", "vision-page"}:
        locator_mode = "auto"
    locator_used = "vision-page"
    locator_notes: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        temp_page = Path(td) / "page.png"
        temp_page.write_bytes(numeric_png)
        numeric_page = _make_numeric_image(temp_page)

        page_image_out = out_dir / f"{source.stem}_page{page_index + 1}_numeric_source.png"
        page_image_out.write_bytes(numeric_page.read_bytes())

        candidates: list[Candidate] = []
        line_items: list[tuple[str, str, tuple[int, int, int, int], int]] = []
        if locator_mode in {"auto", "tesseract"}:
            tesseract_path = _arg_path(root, getattr(args, "tesseract_exe", ""), root / "runtime" / "tesseract" / "tesseract.exe")
            if tesseract_path.exists():
                try:
                    tesseract = TesseractAdapter(str(tesseract_path))
                    locator = tesseract.recognize(str(numeric_page), {"lang": args.tesseract_lang, "psm": int(args.tesseract_psm)})
                    line_items = _candidate_lines(locator.words, int(args.min_digits), int(args.max_candidates))
                    locator_used = "tesseract"
                except Exception as exc:
                    locator_notes.append(f"Tesseract locator failed: {exc}")
                    if locator_mode == "tesseract":
                        raise
            else:
                locator_notes.append(f"Tesseract not found: {tesseract_path}")
                if locator_mode == "tesseract":
                    raise RuntimeError(locator_notes[-1])

        if not line_items and locator_mode in {"auto", "surya"}:
            surya_python = _surya_python(root)
            if surya_python.exists():
                try:
                    surya = SuryaAdapter(project_root=root)
                    surya_result = surya.recognize(
                        str(numeric_page),
                        {
                            "surya_backend": str(getattr(args, "surya_backend", "llamacpp") or "llamacpp"),
                            "timeout_sec": int(getattr(args, "surya_timeout_sec", 900) or 900),
                            "keep_server": True,
                        },
                    )
                    line_items = _candidate_lines(surya_result.words, int(args.min_digits), int(args.max_candidates))
                    locator_used = "surya"
                    if not line_items:
                        locator_notes.append("Surya locator returned no numeric candidates.")
                except Exception as exc:
                    locator_notes.append(f"Surya locator failed: {exc}")
                    if locator_mode == "surya":
                        raise
            else:
                locator_notes.append(f"Surya not found: {surya_python}")
                if locator_mode == "surya":
                    raise RuntimeError(locator_notes[-1])

        if line_items:
            for index, (kind, text, box, digits) in enumerate(line_items, start=1):
                crop_path = crops_dir / f"{source.stem}_page{page_index + 1}_candidate_{index:02d}_{kind}.png"
                crop_box = _crop_candidate(numeric_page, box, crop_path)
                candidates.append(Candidate(index, kind, text, str(crop_path), crop_box, digits))
        else:
            if not locator_notes and locator_mode == "auto":
                locator_notes.append("Local locators returned no numeric candidates; used full-page vision fallback.")
            locator_used = "vision-page"
            candidates.append(_full_page_candidate(numeric_page, source, page_index + 1, crops_dir))

    provider = str(args.provider or "xai").strip().lower()
    if provider != "xai":
        raise RuntimeError("numeric_check prototype currently supports provider=xai.")
    key_file = _arg_path(root, getattr(args, "xai_api_key_file", ""), root / "config" / "api_key_xai.txt")
    if not _read_text(key_file):
        raise RuntimeError(f"xAI key is empty or missing: {key_file}")

    prompt = str(args.prompt or NUMERIC_PROMPT)
    checks: list[Verification] = []
    for candidate in candidates:
        start = time.perf_counter()
        candidate_prompt = _prompt_for_candidate(prompt, candidate, locator_hint=bool(args.locator_hint))
        text, usage, cost = _verify_xai(Path(candidate.crop), str(args.model), key_file, candidate_prompt)
        parsed = _parse_json_object(text)
        status, locator_digits, verified_digits = _comparison_status(candidate.text, parsed, text)
        checks.append(
            Verification(
                candidate_id=candidate.id,
                provider=provider,
                model=str(args.model),
                text=text,
                parsed=parsed,
                status=status,
                locator_digit_sequences=locator_digits,
                verified_digit_sequences=verified_digits,
                usage=usage,
                cost_usd_estimate=cost,
                elapsed_sec=round(time.perf_counter() - start, 3),
            )
        )

    report = {
        "source": str(source),
        "page": page_index + 1,
        "provider": provider,
        "model": str(args.model),
        "locator": locator_used,
        "locator_error": " | ".join(locator_notes),
        "numeric_source_image": str(out_dir / f"{source.stem}_page{page_index + 1}_numeric_source.png"),
        "candidates": [asdict(candidate) for candidate in candidates],
        "checks": [asdict(check) for check in checks],
        "total_cost_usd_estimate": round(sum(float(check.cost_usd_estimate or 0.0) for check in checks), 8),
    }

    json_path = out_dir / f"{source.stem}_page{page_index + 1}_numeric_check.json"
    md_path = out_dir / f"{source.stem}_page{page_index + 1}_numeric_check.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, report)
    report["json"] = str(json_path)
    report["markdown"] = str(md_path)
    return report


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    chunks = [
        f"# Numeric Check: {Path(str(report.get('source', ''))).name} page {report.get('page')}",
        "",
        f"- provider: `{report.get('provider')}`",
        f"- model: `{report.get('model')}`",
        f"- locator: `{report.get('locator')}`",
        f"- total_cost_usd_estimate: `{report.get('total_cost_usd_estimate')}`",
        "",
        "| ID | Status | Kind | Locator text | Locator digits | Verified values | Verified digits | Seconds | Cost | Crop |",
        "| ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    if report.get("locator_error"):
        chunks.insert(5, f"- locator_note: `{report.get('locator_error')}`")
    candidates = {item["id"]: item for item in report.get("candidates", []) if isinstance(item, dict)}
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        candidate = candidates.get(check.get("candidate_id"), {})
        parsed = check.get("parsed") if isinstance(check.get("parsed"), dict) else {}
        values: list[str] = []
        for item in parsed.get("items", []) if isinstance(parsed.get("items"), list) else []:
            if isinstance(item, dict):
                label = str(item.get("label") or "").strip()
                value = str(item.get("value") or "").strip()
                values.append(f"{label}: `{value}`" if label else f"`{value}`")
        if not values:
            values = [str(parsed.get("raw") or check.get("text") or "").replace("\n", " ")[:180]]
        cost = check.get("cost_usd_estimate")
        cost_text = "" if cost is None else f"${float(cost):.6f}"
        crop = str(candidate.get("crop") or "")
        locator_digits = "<br>".join(f"`{value}`" for value in check.get("locator_digit_sequences", []) if value)
        verified_digits = "<br>".join(f"`{value}`" for value in check.get("verified_digit_sequences", []) if value)
        chunks.append(
            "| {id} | {status} | {kind} | {locator} | {locator_digits} | {values} | {verified_digits} | {seconds} | {cost} | {crop} |".format(
                id=check.get("candidate_id"),
                status=check.get("status", ""),
                kind=candidate.get("kind", ""),
                locator=str(candidate.get("text", "")).replace("|", "/")[:180],
                locator_digits=locator_digits,
                values="<br>".join(value.replace("|", "/") for value in values),
                verified_digits=verified_digits,
                seconds=check.get("elapsed_sec"),
                cost=cost_text,
                crop=Path(crop).name if crop else "",
            )
        )
    chunks.append("")
    path.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--root", default=str(_project_root()))
    parser.add_argument("--out", default="")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--provider", default="xai")
    parser.add_argument("--model", default="grok-4.20-non-reasoning-latest")
    parser.add_argument("--locator", choices=("auto", "tesseract", "surya", "vision-page"), default="auto")
    parser.add_argument("--xai-api-key-file", default="")
    parser.add_argument("--tesseract-exe", default="")
    parser.add_argument("--tesseract-lang", default="rus+eng")
    parser.add_argument("--tesseract-psm", type=int, default=6)
    parser.add_argument("--surya-backend", default="llamacpp")
    parser.add_argument("--surya-timeout-sec", type=int, default=900)
    parser.add_argument("--min-digits", type=int, default=8)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--denoise", default="weak")
    parser.add_argument("--contrast", default="high")
    parser.add_argument("--unsharp", default="strong")
    parser.add_argument("--binarize", default="off")
    parser.add_argument("--deskew", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--locator-hint", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prompt", default=NUMERIC_PROMPT)
    report = run_numeric_check(parser.parse_args())
    print(json.dumps({key: report[key] for key in ("json", "markdown", "total_cost_usd_estimate")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
