from __future__ import annotations

import sys
import os
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_paths import (
    API_KEY_GEMINI_FILE,
    CONFIG_API_KEY_GEMINI_FILE,
    LEGACY_CONFIG_API_KEY_GEMINI_FILE,
    MODELS_CACHE_FILE,
    ensure_project_dirs,
)


def get_api_key(path: Path = CONFIG_API_KEY_GEMINI_FILE) -> str | None:
    env_key = os.getenv("AUDION_GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    env_key_file = os.getenv("AUDION_GEMINI_API_KEY_FILE", "").strip()
    if env_key_file:
        path = Path(env_key_file)
    if path.exists():
        key = path.read_text(encoding="utf-8", errors="ignore").strip()
        if key:
            return key
    for fallback_path in (LEGACY_CONFIG_API_KEY_GEMINI_FILE, API_KEY_GEMINI_FILE):
        if fallback_path == path or not fallback_path.exists():
            continue
        key = fallback_path.read_text(encoding="utf-8", errors="ignore").strip()
        if key:
            return key
    return None


def main() -> int:
    ensure_project_dirs()
    api_key = get_api_key()
    if not api_key:
        print(f"[ERROR] File '{CONFIG_API_KEY_GEMINI_FILE}' was not found or is empty.")
        return 1

    try:
        from google import genai
    except Exception as exc:
        print(f"[ERROR] google-genai import failed: {exc}")
        return 1

    print("[INFO] Requesting model list from Gemini API...")
    client = genai.Client(api_key=api_key)

    try:
        models = []
        for model in client.models.list():
            actions = getattr(model, "supported_actions", None)
            if actions and "generateContent" in actions:
                models.append(model.name.replace("models/", ""))

        if not models:
            print("[WARN] No content-generation models were returned for this key.")
            return 1

        models = sorted(dict.fromkeys(models))
        MODELS_CACHE_FILE.write_text(
            "# Gemini models available for current key\n\n"
            f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + "\n".join(models)
            + "\n",
            encoding="utf-8",
        )
        print("\n".join(models))
        print(f"\n[OK] Saved to: {MODELS_CACHE_FILE}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Gemini API request failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
