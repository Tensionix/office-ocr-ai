# benchmark_quality.py
# One-page OCR quality/cost harness for damaged vs tolerable scan comparison.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import cleanconfig, preprocess
from .cache import Cache
from .engines import registry
from .sr_client import SRClient


CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")
SUSPICIOUS_RE = re.compile(r"[�□■●◆◇◊¤¬�]")
REPEATED_PUNCT_RE = re.compile(r"([.,;:!?\-_=*])\1{2,}")


@dataclass
class TextMetrics:
    chars: int
    words: int
    lines: int
    cyrillic_ratio: float
    latin_ratio: float
    suspicious_ratio: float
    repeated_punct: int
    markdown_emphasis: int
    markdown_fences: int


@dataclass
class WordMetrics:
    words_with_boxes: int
    avg_confidence: float | None
    low_confidence_ratio: float | None


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


def _prompt_file(root: Path, args: argparse.Namespace) -> Path:
    return _arg_path(root, getattr(args, "prompt_file", ""), root / "config" / "ocr_prompt_vision_ocr.md")


def _tesseract_exe(root: Path) -> str:
    portable = root / "runtime" / "tesseract" / "tesseract.exe"
    return str(portable if portable.exists() else "tesseract")


def _realesrgan_exe(root: Path) -> Path | None:
    candidates = [
        root / "tools" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
        root / "runtime" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
        root / "runtime" / "realesrgan-ncnn-vulkan.exe",
        root / "system_core" / "ocr_brick" / "bin" / "realesrgan-ncnn-vulkan.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _optional_ocr_python(root: Path, engine: str, args: argparse.Namespace | None = None) -> Path:
    names = (engine,)
    candidates = [root / "tools" / "optional-ocr-engines" / name / "runtime" / "python.exe" for name in names]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _ensure_optional_runtime(root: Path, engine: str, modules: tuple[str, ...], args: argparse.Namespace) -> None:
    python = _optional_ocr_python(root, engine, args)
    if not python.exists():
        raise RuntimeError(f"{engine} optional portable runtime is not installed: {python}")
    code = (
        "import importlib.util, sys; "
        f"mods={list(modules)!r}; "
        "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
        "print(','.join(missing)); "
        "sys.exit(1 if missing else 0)"
    )
    proc = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        missing = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        raise RuntimeError(f"{engine} optional runtime is missing packages: {missing}")


def _safe_excerpt(text: str, limit: int = 1600) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def _metrics(text: str) -> TextMetrics:
    chars = len(text)
    words = len(re.findall(r"\S+", text))
    lines = len([line for line in text.splitlines() if line.strip()])
    denom = max(1, chars)
    return TextMetrics(
        chars=chars,
        words=words,
        lines=lines,
        cyrillic_ratio=len(CYRILLIC_RE.findall(text)) / denom,
        latin_ratio=len(LATIN_RE.findall(text)) / denom,
        suspicious_ratio=len(SUSPICIOUS_RE.findall(text)) / denom,
        repeated_punct=len(REPEATED_PUNCT_RE.findall(text)),
        markdown_emphasis=text.count("**") + text.count("__"),
        markdown_fences=text.count("```"),
    )


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any, digits: int = 4) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    if digits <= 0:
        return f"{number:.0f}"
    if number == 0:
        return "0"
    if abs(number) >= 100:
        return f"{number:.0f}"
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _fmt_delta(raw: Any, clean: Any, digits: int = 4) -> str:
    raw_num = _num(raw)
    clean_num = _num(clean)
    if raw_num is None or clean_num is None:
        return "n/a"
    delta = clean_num - raw_num
    sign = "+" if delta > 0 else ""
    return f"{_fmt(raw_num, digits)} -> {_fmt(clean_num, digits)} ({sign}{_fmt(delta, digits)})"


def _comparison_verdict(raw: dict[str, Any], clean: dict[str, Any]) -> str:
    raw_metrics = raw.get("metrics", {})
    clean_metrics = clean.get("metrics", {})
    raw_words = raw.get("word_metrics", {})
    clean_words = clean.get("word_metrics", {})

    wins = 0
    losses = 0

    def prefer_higher(key: str, threshold: float = 0.0) -> None:
        nonlocal wins, losses
        raw_value = _num(raw_metrics.get(key))
        clean_value = _num(clean_metrics.get(key))
        if raw_value is None or clean_value is None:
            return
        delta = clean_value - raw_value
        if delta > threshold:
            wins += 1
        elif delta < -threshold:
            losses += 1

    def prefer_lower(key: str, threshold: float = 0.0) -> None:
        nonlocal wins, losses
        raw_value = _num(raw_metrics.get(key))
        clean_value = _num(clean_metrics.get(key))
        if raw_value is None or clean_value is None:
            return
        delta = clean_value - raw_value
        if delta < -threshold:
            wins += 1
        elif delta > threshold:
            losses += 1

    prefer_higher("cyrillic_ratio", 0.005)
    prefer_lower("suspicious_ratio", 0.0005)
    prefer_lower("repeated_punct", 0.0)
    prefer_lower("markdown_fences", 0.0)

    raw_conf = _num(raw_words.get("avg_confidence"))
    clean_conf = _num(clean_words.get("avg_confidence"))
    if raw_conf is not None and clean_conf is not None:
        delta = clean_conf - raw_conf
        if delta > 0.005:
            wins += 1
        elif delta < -0.005:
            losses += 1

    raw_low = _num(raw_words.get("low_confidence_ratio"))
    clean_low = _num(clean_words.get("low_confidence_ratio"))
    if raw_low is not None and clean_low is not None:
        delta = clean_low - raw_low
        if delta < -0.005:
            wins += 1
        elif delta > 0.005:
            losses += 1

    if wins > losses:
        return "clean better"
    if losses > wins:
        return "raw better"
    return "mixed"


def _comparison_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for item in results:
        engine = str(item.get("engine") or "")
        variant = str(item.get("variant") or "")
        if engine and variant:
            grouped.setdefault(engine, {})[variant] = item

    rows: list[dict[str, Any]] = []
    for engine, variants in grouped.items():
        raw = variants.get("raw")
        clean = variants.get("clean")
        if not raw or not clean:
            continue
        rows.append(
            {
                "engine": engine,
                "chars": _fmt_delta(raw.get("metrics", {}).get("chars"), clean.get("metrics", {}).get("chars"), 0),
                "words": _fmt_delta(raw.get("metrics", {}).get("words"), clean.get("metrics", {}).get("words"), 0),
                "cyrillic": _fmt_delta(raw.get("metrics", {}).get("cyrillic_ratio"), clean.get("metrics", {}).get("cyrillic_ratio")),
                "suspicious": _fmt_delta(raw.get("metrics", {}).get("suspicious_ratio"), clean.get("metrics", {}).get("suspicious_ratio")),
                "markdown_marks": _fmt_delta(raw.get("metrics", {}).get("markdown_emphasis"), clean.get("metrics", {}).get("markdown_emphasis"), 0),
                "markdown_fences": _fmt_delta(raw.get("metrics", {}).get("markdown_fences"), clean.get("metrics", {}).get("markdown_fences"), 0),
                "avg_conf": _fmt_delta(raw.get("word_metrics", {}).get("avg_confidence"), clean.get("word_metrics", {}).get("avg_confidence")),
                "low_conf": _fmt_delta(raw.get("word_metrics", {}).get("low_confidence_ratio"), clean.get("word_metrics", {}).get("low_confidence_ratio")),
                "verdict": _comparison_verdict(raw, clean),
            }
        )
    return rows


def _usage_cost_usd_estimate(usage: dict[str, Any]) -> float | None:
    raw_ticks = usage.get("cost_in_usd_ticks") if isinstance(usage, dict) else None
    try:
        ticks = float(raw_ticks)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return ticks / 10_000_000_000


def _word_metrics(words: list[Any]) -> WordMetrics:
    confidences = [float(getattr(word, "confidence", 0.0)) for word in words if getattr(word, "text", "")]
    if not confidences:
        return WordMetrics(words_with_boxes=0, avg_confidence=None, low_confidence_ratio=None)
    low = [value for value in confidences if value < 0.70]
    return WordMetrics(
        words_with_boxes=len(confidences),
        avg_confidence=round(sum(confidences) / len(confidences), 4),
        low_confidence_ratio=round(len(low) / len(confidences), 4),
    )


def _adapter_params(root: Path, engine: str, args: argparse.Namespace) -> dict[str, Any]:
    if engine == "tesseract":
        return {"lang": args.tesseract_lang, "psm": args.tesseract_psm}
    if engine == "surya":
        return {"surya_backend": getattr(args, "surya_backend", "llamacpp")}
    if engine == "yandex":
        langs = [item.strip() for item in args.yandex_languages.split(",") if item.strip()]
        return {"mode": "sync", "model": args.yandex_model, "languageCodes": langs or ["ru", "en"]}
    if engine == "xai":
        return {
            "model": args.xai_model,
            "api_key_file": str(_arg_path(root, getattr(args, "xai_api_key_file", ""), root / "config" / "api_key_xai.txt")),
            "prompt": _read_text(_prompt_file(root, args)),
        }
    if engine == "mistral":
        return {
            "adapter_version": 1,
            "model": args.mistral_model,
            "api_key_file": str(_arg_path(root, getattr(args, "mistral_api_key_file", ""), root / "config" / "api_key_mistral.txt")),
            "include_blocks": True,
            "table_format": "html",
            "confidence_granularity": "word",
        }
    if engine == "gemini":
        return {
            "model": args.gemini_model,
            "api_key_file": str(_arg_path(root, getattr(args, "gemini_api_key_file", ""), root / "config" / "api_key_gemini.txt")),
            "prompt": _read_text(_prompt_file(root, args)),
            "use_stream": bool(getattr(args, "gemini_use_stream", True)),
            "service_tier": str(getattr(args, "gemini_service_tier", "standard") or "standard"),
            "timeout_sec": 600 if str(getattr(args, "gemini_service_tier", "standard") or "standard").lower() == "flex" else 180,
        }
    if engine == "chatgpt":
        return {
            "model": args.openai_model,
            "api_key_file": str(_arg_path(root, getattr(args, "openai_api_key_file", ""), root / "config" / "api_key_openai.txt")),
            "prompt": _read_text(_prompt_file(root, args)),
        }
    return {}


def _yandex_key_file(root: Path, args: argparse.Namespace) -> Path:
    return _arg_path(root, getattr(args, "yandex_api_key_file", ""), root / "config" / "api_key_yandex_studio.txt")


def _yandex_folder_file(root: Path, args: argparse.Namespace) -> Path:
    return _arg_path(root, getattr(args, "yandex_folder_file", ""), root / "config" / "yandex_folder.txt")


def _ensure_nonempty_file(path: Path, label: str) -> None:
    if not _read_text(path):
        raise RuntimeError(f"{label} is empty or missing: {path}")


def _ensure_engine_available(root: Path, engine: str, args: argparse.Namespace) -> None:
    if engine == "yandex":
        _ensure_nonempty_file(_yandex_key_file(root, args), "Yandex key")
        _ensure_nonempty_file(_yandex_folder_file(root, args), "Yandex folder id")
    if engine == "xai":
        _ensure_nonempty_file(_arg_path(root, getattr(args, "xai_api_key_file", ""), root / "config" / "api_key_xai.txt"), "xAI key")
    if engine == "mistral":
        _ensure_nonempty_file(_arg_path(root, getattr(args, "mistral_api_key_file", ""), root / "config" / "api_key_mistral.txt"), "Mistral key")
    if engine == "gemini":
        _ensure_nonempty_file(_arg_path(root, getattr(args, "gemini_api_key_file", ""), root / "config" / "api_key_gemini.txt"), "Gemini key")
    if engine == "chatgpt":
        _ensure_nonempty_file(_arg_path(root, getattr(args, "openai_api_key_file", ""), root / "config" / "api_key_openai.txt"), "OpenAI key")
    optional = {
        "surya": ("surya", "torch"),
    }.get(engine, ())
    if optional:
        _ensure_optional_runtime(root, engine, optional, args)


def _build_adapter(root: Path, engine: str, manifest: dict[str, Any], args: argparse.Namespace):
    if engine == "yandex":
        from .engines.yandex import YandexAdapter
        from .engines.yandex_creds import YandexCreds

        creds = YandexCreds(
            auth_type="api_key",
            secret=_read_text(_yandex_key_file(root, args)),
            folder_id=_read_text(_yandex_folder_file(root, args)),
        )
        return YandexAdapter(creds)
    return registry.build_adapter(engine, manifest, root, _tesseract_exe(root))


def _clean_variant(
    root: Path,
    source: Path,
    page_png: bytes,
    engine: str,
    variant: str,
    args: argparse.Namespace,
) -> bytes:
    profiles = cleanconfig.load_profiles(root / "system_core" / "ocr_brick" / "preprocess.profiles.json")
    manifest = registry.load_engines(root / "system_core" / "ocr_brick" / "ocr.engines.json")
    profile = registry.engine_profile(engine, manifest)
    overrides: dict[str, Any]
    if variant == "raw":
        overrides = {"enabled": False, "sr_scale": 0}
    else:
        overrides = {
            "enabled": True,
            "sr_scale": args.sr_scale,
            "sr_model": args.sr_model,
            "denoise": args.denoise,
            "contrast": args.contrast,
            "unsharp": args.unsharp,
            "binarize": args.binarize,
            "deskew": args.deskew,
            "strip_vlines": args.strip_vlines,
            "intent": "text",
            "source_format": "auto",
        }
    cfg = cleanconfig.resolve(profiles, target_engine=profile, gui_overrides=overrides, original_name=str(source))
    cache = Cache(root / "cache" / "benchmark_quality", max_bytes=5 * 1024**3)
    sr = None
    if cfg.sr_scale and cfg.sr_scale > 0:
        sr_exe = _realesrgan_exe(root)
        if sr_exe is None:
            raise RuntimeError("SR requested but Real-ESRGAN ncnn-vulkan executable was not found.")
        sr = SRClient(sr_exe, gpu=args.sr_gpu)
    return preprocess.clean_page(page_png, cfg, cache=cache, sr=sr)


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    source = Path(args.source).resolve()
    out_dir = Path(args.out).resolve() if args.out else root / "workspace" / "ocr_quality_benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = preprocess.rasterize(source, dpi=args.dpi)
    page_index = max(0, min(args.page - 1, len(pages) - 1))
    page_png = pages[page_index]

    manifest = registry.load_engines(root / "system_core" / "ocr_brick" / "ocr.engines.json")
    engines = [item.strip() for item in args.engines.split(",") if item.strip()]
    variants = [item.strip() for item in args.variants.split(",") if item.strip()]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for engine in engines:
        try:
            _ensure_engine_available(root, engine, args)
        except Exception as exc:
            if bool(getattr(args, "skip_unavailable", False)):
                errors.append({"engine": engine, "variant": "", "error": str(exc)})
                continue
            raise
        for variant in variants:
            try:
                clean_png = _clean_variant(root, source, page_png, engine, variant, args)
                clean_path = out_dir / f"{source.stem}_page{page_index + 1}_{engine}_{variant}.png"
                clean_path.write_bytes(clean_png)
                adapter = _build_adapter(root, engine, manifest, args)
                params = _adapter_params(root, engine, args)
                start = time.perf_counter()
                result = adapter.recognize(str(clean_path), params)
                elapsed = time.perf_counter() - start
                usage = getattr(adapter, "last_usage", {}) or {}
                item = {
                    "source": str(source),
                    "page": page_index + 1,
                    "variant": variant,
                    "engine": engine,
                    "elapsed_sec": round(elapsed, 3),
                    "usage": usage,
                    "cost_usd_estimate": _usage_cost_usd_estimate(usage),
                    "metrics": asdict(_metrics(result.text)),
                    "word_metrics": asdict(_word_metrics(result.words)),
                    "text": result.text,
                    "image": str(clean_path),
                }
                results.append(item)
            except Exception as exc:
                if bool(getattr(args, "skip_unavailable", False)):
                    errors.append({"engine": engine, "variant": variant, "error": str(exc)})
                    continue
                raise

    report = {
        "source": str(source),
        "page": page_index + 1,
        "engines": engines,
        "variants": variants,
        "results": results,
        "errors": errors,
    }
    json_path = out_dir / f"{source.stem}_page{page_index + 1}_benchmark.json"
    md_path = out_dir / f"{source.stem}_page{page_index + 1}_benchmark.md"
    comparison_rows = _comparison_rows(results)
    report["comparisons"] = comparison_rows
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    chunks = [f"# OCR Quality Benchmark: {source.name} page {page_index + 1}", ""]
    if errors:
        chunks.extend(["## Skipped / errors", ""])
        for item in errors:
            chunks.append(f"- {item.get('engine')} {item.get('variant')}: {item.get('error')}")
        chunks.append("")
    if comparison_rows:
        chunks.extend(
            [
                "## Raw vs clean summary",
                "",
                "| Engine | Chars | Words | Cyrillic | Suspicious | MD fences | MD marks | Avg conf | Low conf | Verdict |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in comparison_rows:
            chunks.append(
                "| {engine} | {chars} | {words} | {cyrillic} | {suspicious} | "
                "{markdown_fences} | {markdown_marks} | {avg_conf} | {low_conf} | {verdict} |".format(**row)
            )
        chunks.append("")
    for item in results:
        chunks.extend(
            [
                f"## {item['variant']} / {item['engine']}",
                "",
                f"- elapsed_sec: {item['elapsed_sec']}",
                f"- usage: `{json.dumps(item['usage'], ensure_ascii=False)}`",
                f"- metrics: `{json.dumps(item['metrics'], ensure_ascii=False)}`",
                f"- word_metrics: `{json.dumps(item['word_metrics'], ensure_ascii=False)}`",
                "",
                "```text",
                _safe_excerpt(str(item["text"])),
                "```",
                "",
            ]
        )
    md_path.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")
    report["json"] = str(json_path)
    report["markdown"] = str(md_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--root", default=str(_project_root()))
    parser.add_argument("--out", default="")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--engines", default="tesseract,yandex,mistral,xai")
    parser.add_argument("--variants", default="raw,clean")
    parser.add_argument("--sr-scale", type=int, default=0)
    parser.add_argument("--sr-model", default="auto")
    parser.add_argument("--sr-gpu", default="auto")
    parser.add_argument("--denoise", default="weak")
    parser.add_argument("--contrast", default="auto")
    parser.add_argument("--unsharp", default="auto")
    parser.add_argument("--binarize", default="auto")
    parser.add_argument("--deskew", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--strip-vlines", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--tesseract-lang", default="rus+eng")
    parser.add_argument("--tesseract-psm", type=int, default=6)
    parser.add_argument("--surya-backend", default="llamacpp")
    parser.add_argument("--yandex-model", default="page")
    parser.add_argument("--yandex-languages", default="ru,en")
    parser.add_argument("--xai-model", default="grok-4.20-non-reasoning-latest")
    parser.add_argument("--mistral-model", default="mistral-ocr-4-0")
    parser.add_argument("--gemini-model", default="gemini-3.5-flash")
    parser.add_argument("--gemini-use-stream", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--gemini-service-tier", default="standard", choices=["standard", "flex"])
    parser.add_argument("--openai-model", default="gpt-4.1")
    parser.add_argument("--xai-api-key-file", default="")
    parser.add_argument("--mistral-api-key-file", default="")
    parser.add_argument("--gemini-api-key-file", default="")
    parser.add_argument("--openai-api-key-file", default="")
    parser.add_argument("--yandex-api-key-file", default="")
    parser.add_argument("--yandex-folder-file", default="")
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--skip-unavailable", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()
    report = run_benchmark(args)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
