# engines/surya.py
# Surya adapter via the optional portable Surya runtime.
# The main project runtime must not import surya/torch: Surya's dependency
# pins conflict with the GUI/API/PDF stack. Calls cross a process boundary into
# tools/optional-ocr-engines/surya/runtime/python.exe and read Surya JSON output.

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import OcrResult, Word
from .regions import LayoutResult, TextRegion


TAG_BREAK_RE = re.compile(r"</(?:p|div|h[1-6]|li|tr|table)>", re.IGNORECASE)
TAG_CELL_RE = re.compile(r"</t[dh]>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


class SuryaAdapter:
    kind = "ocr"
    provides_layout = True

    def __init__(
        self,
        device: str = "auto",
        langs: list[str] | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.device = device
        self.langs = langs or ["ru", "en"]
        self.root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[3]

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        page = self._run_ocr(clean_png_path, params)
        blocks = sorted(page.get("blocks", []) or [], key=lambda item: int(item.get("reading_order", 0)))
        texts: list[str] = []
        words: list[Word] = []
        for block in blocks:
            if block.get("skipped") or block.get("error"):
                continue
            text = _html_to_text(str(block.get("html") or "")).strip()
            if not text:
                continue
            texts.append(text)
            box = _polygon_box(block.get("polygon"))
            if box:
                words.append(
                    Word(
                        text=text,
                        box=box,
                        confidence=float(block.get("confidence", 1.0) or 1.0),
                    )
                )
        return OcrResult(kind="ocr", text="\n\n".join(texts), words=words, engine="surya")

    def analyze_layout(self, clean_png_path: str, page: int = 0) -> LayoutResult:
        raw = self._run_ocr(clean_png_path, {"keep_server": True})
        image_bbox = raw.get("image_bbox") or [0, 0, 0, 0]
        out = LayoutResult(
            page=page,
            engine="surya",
            width=int(float(image_bbox[2] if len(image_bbox) > 2 else 0)),
            height=int(float(image_bbox[3] if len(image_bbox) > 3 else 0)),
        )
        blocks = sorted(raw.get("blocks", []) or [], key=lambda item: int(item.get("reading_order", 0)))
        for block in blocks:
            if block.get("skipped") or block.get("error"):
                continue
            text = _html_to_text(str(block.get("html") or "")).strip()
            if not text:
                continue
            label = str(block.get("label") or "").lower()
            kind = "heading" if label in {"title", "section-header", "header"} else "paragraph"
            out.regions.append(TextRegion(text=text, box=_polygon_box(block.get("polygon")), kind=kind))
        return out

    def _optional_python(self) -> Path:
        return self.root / "tools" / "optional-ocr-engines" / "surya" / "runtime" / "python.exe"

    def _run_ocr(self, clean_png_path: str, params: dict | None = None) -> dict[str, Any]:
        params = params or {}
        python = self._optional_python()
        if not python.exists():
            raise RuntimeError(
                f"Surya optional portable runtime is not installed: {python}. "
                "Run Project tools -> Install optional OCR engines."
            )

        source = Path(clean_png_path).resolve()
        if not source.exists():
            raise FileNotFoundError(str(source))

        with tempfile.TemporaryDirectory(prefix="audion_surya_ocr_") as td:
            out_dir = Path(td)
            code = "from surya.scripts.ocr_text import ocr_text_cli; ocr_text_cli()"
            cmd = [
                str(python),
                "-c",
                code,
                str(source),
                "--output_dir",
                str(out_dir),
            ]
            if bool(params.get("keep_server", True)):
                cmd.append("--keep_server")

            env = os.environ.copy()
            env["PYTHONNOUSERSITE"] = "1"
            cache_root = self.root / "tools" / "optional-ocr-engines" / "surya" / "cache"
            cache_root.mkdir(parents=True, exist_ok=True)
            env.setdefault("HF_HOME", str(cache_root / "huggingface"))
            env.setdefault("HF_HUB_CACHE", str(cache_root / "huggingface" / "hub"))
            env.setdefault("XDG_CACHE_HOME", str(cache_root))
            env.setdefault("SURYA_INFERENCE_PARALLEL", str(params.get("parallel", 1)))
            env.setdefault("SURYA_INFERENCE_CTX_SIZE", str(params.get("ctx_size", 24576)))
            backend = str(params.get("surya_backend") or params.get("backend") or "").strip()
            if backend:
                env["SURYA_INFERENCE_BACKEND"] = backend
            elif self.device == "cuda":
                env["SURYA_INFERENCE_BACKEND"] = "vllm"
            elif self.device == "cpu":
                env["SURYA_INFERENCE_BACKEND"] = "llamacpp"
            else:
                env["SURYA_INFERENCE_BACKEND"] = "llamacpp"
            llama_binary = _default_llama_binary(self.root)
            if llama_binary and "LLAMA_CPP_BINARY" not in env:
                env["LLAMA_CPP_BINARY"] = str(llama_binary)

            timeout = float(params.get("timeout_sec", 900))
            proc = subprocess.run(
                cmd,
                cwd=str(self.root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if proc.returncode != 0:
                tail = "\n".join((proc.stderr or proc.stdout or "").splitlines()[-30:])
                raise RuntimeError(f"Surya OCR failed with exit code {proc.returncode}:\n{tail}")

            result_path = out_dir / source.stem / "results.json"
            if not result_path.exists():
                matches = list(out_dir.rglob("results.json"))
                if not matches:
                    raise RuntimeError(f"Surya did not write results.json under {out_dir}")
                result_path = matches[0]
            data = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not data:
                raise RuntimeError("Surya results.json is empty or not an object")
            pages = next(iter(data.values()))
            if not pages:
                return {"blocks": [], "image_bbox": [0, 0, 0, 0]}
            return dict(pages[0])


def _default_llama_binary(root: Path) -> Path | None:
    candidates = [
        root / "tools" / "llama.cpp" / "llama-server.exe",
        root / "tools" / "llama-cpp" / "llama-server.exe",
        root / "tools" / "llama-server" / "llama-server.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _polygon_box(raw: object) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, list) or not raw:
        return None
    try:
        xs = [float(point[0]) for point in raw if isinstance(point, list) and len(point) >= 2]
        ys = [float(point[1]) for point in raw if isinstance(point, list) and len(point) >= 2]
    except (TypeError, ValueError):
        return None
    if not xs or not ys:
        return None
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return (int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))


def _html_to_text(value: str) -> str:
    if not value:
        return ""
    text = TAG_CELL_RE.sub("\t", value)
    text = TAG_BREAK_RE.sub("\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
