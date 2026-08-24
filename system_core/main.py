from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_paths import (
    BASE_DIR,
    CONFIG_API_KEY_GEMINI_FILE,
    CONFIG_API_KEY_OPENAI_FILE,
    LLM_SETTINGS_FILE,
    OUTPUT_DIR,
    ensure_project_dirs,
)


def detect_python_mode(root: Path) -> str:
    if (root / "runtime" / "python.exe").exists():
        return "portable-runtime"
    if (root / "runtime" / "python" / "python.exe").exists():
        return "portable-runtime"
    return "system-python"


def main() -> int:
    ensure_project_dirs()

    payload = {
        "project": "Audion Office OCR AI",
        "project_root": str(BASE_DIR),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "python_mode": detect_python_mode(BASE_DIR),
        "folders": {
            "input": str(BASE_DIR / "input"),
            "output": str(OUTPUT_DIR),
        },
        "api_keys": {
            "gemini": str(CONFIG_API_KEY_GEMINI_FILE),
            "openai": str(CONFIG_API_KEY_OPENAI_FILE),
        },
        "llm_settings": str(LLM_SETTINGS_FILE),
        "message": "Portable workspace is ready for extraction and document compilation.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
