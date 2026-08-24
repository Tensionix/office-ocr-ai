from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parents[1]

INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
RUNTIME_DIR = BASE_DIR / "runtime"
TESSERACT_DIR = RUNTIME_DIR / "tesseract"
TESSERACT_EXE = TESSERACT_DIR / "tesseract.exe"
TESSDATA_DIR = TESSERACT_DIR / "tessdata"
WHEELHOUSE_DIR = BASE_DIR / "wheelhouse"
RELEASE_DIR = BASE_DIR / "release"
INTERNAL_RUNTIME_DIR = BASE_DIR / "._runtime"
TEMP_DIR = Path(tempfile.gettempdir()) / "audion_office_ocr_ai"

# Legacy optional folders. Files can still be dropped directly into `input/`.
INPUT_DOCS_DIR = INPUT_DIR / "docs"
INPUT_MD_DIR = INPUT_DIR / "md"

OUTPUT_MD_DIR = OUTPUT_DIR
OUTPUT_IMAGES_DIR = OUTPUT_DIR
OUTPUT_DOCX_DIR = OUTPUT_DIR
OUTPUT_PDF_DIR = OUTPUT_DIR
OUTPUT_PPTX_DIR = OUTPUT_DIR
OUTPUT_XLSX_DIR = OUTPUT_DIR

API_KEY_GEMINI_FILE = BASE_DIR / "api_key.txt"
API_KEY_OPENAI_FILE = BASE_DIR / "api_key_openai.txt"
CONFIG_API_KEY_GEMINI_FILE = CONFIG_DIR / "api_key_gemini.txt"
CONFIG_API_KEY_OPENAI_FILE = CONFIG_DIR / "api_key_openai.txt"
LEGACY_CONFIG_API_KEY_GEMINI_FILE = CONFIG_DIR / "api_gemini.txt"
LEGACY_CONFIG_API_KEY_OPENAI_FILE = CONFIG_DIR / "api_openai.txt"
LLM_SETTINGS_FILE = CONFIG_DIR / "llm_settings.yaml"
MODELS_CACHE_FILE = DATA_DIR / "available_models_gemini.md"
MODELS_CACHE_GEMINI_FILE = MODELS_CACHE_FILE
MODELS_CACHE_OPENAI_FILE = DATA_DIR / "available_models_openai.md"

EXCLUDED_TOP_LEVEL_DIRS = {
    "output",
    "runtime",
    "wheelhouse",
    "release",
    "logs",
    "config",
    "data",
    "system_core",
    "install",
    "licenses",
    "._runtime",
    "__pycache__",
}


def ensure_project_dirs() -> None:
    for folder in (
        INPUT_DIR,
        OUTPUT_DIR,
        LOGS_DIR,
        CONFIG_DIR,
        DATA_DIR,
        RUNTIME_DIR,
        TESSERACT_DIR,
        TESSDATA_DIR,
        WHEELHOUSE_DIR,
        RELEASE_DIR,
        INTERNAL_RUNTIME_DIR,
        TEMP_DIR,
        OUTPUT_MD_DIR,
        OUTPUT_IMAGES_DIR,
        OUTPUT_DOCX_DIR,
        OUTPUT_PDF_DIR,
        OUTPUT_PPTX_DIR,
        OUTPUT_XLSX_DIR,
    ):
        folder.mkdir(parents=True, exist_ok=True)


def is_project_source_file(path: Path) -> bool:
    try:
        rel = path.relative_to(BASE_DIR)
    except ValueError:
        return False
    if not rel.parts:
        return False
    top_level = rel.parts[0].lower()
    if top_level in EXCLUDED_TOP_LEVEL_DIRS:
        return False
    if top_level.startswith("audion_ocr_"):
        return False
    return True


def iter_project_files(extensions: Iterable[str]) -> list[Path]:
    allowed = {ext.lower() for ext in extensions}
    results: list[Path] = []
    if not INPUT_DIR.exists():
        return results

    for dirpath, dirnames, filenames in os.walk(INPUT_DIR, followlinks=False):
        current_dir = Path(dirpath)
        filtered_dirnames: list[str] = []
        for dirname in dirnames:
            candidate = current_dir / dirname
            if candidate.is_symlink():
                continue
            if hasattr(candidate, "is_junction") and candidate.is_junction():
                continue
            filtered_dirnames.append(dirname)
        dirnames[:] = filtered_dirnames

        for filename in filenames:
            path = current_dir / filename
            if path.suffix.lower() not in allowed:
                continue
            if path.is_symlink():
                continue
            if not is_project_source_file(path):
                continue
            results.append(path)
    return sorted(results, key=lambda item: str(item.relative_to(BASE_DIR)).lower())


def project_relative_path(path: Path) -> Path:
    return path.relative_to(BASE_DIR)


def normalized_source_relative_path(path: Path) -> Path:
    try:
        rel = path.relative_to(INPUT_DIR)
    except ValueError:
        rel = project_relative_path(path)
    parts = list(rel.parts)
    if parts and parts[0].lower() in {"docs", "md"}:
        parts = parts[1:]
    if not parts:
        return Path(path.name)
    return Path(*parts)


def output_path_for(source_path: Path, suffix: str) -> Path:
    rel_path = normalized_source_relative_path(source_path)
    return OUTPUT_DIR / rel_path.with_suffix(suffix)
