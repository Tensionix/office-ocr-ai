from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_paths import (
    API_KEY_OPENAI_FILE,
    CONFIG_API_KEY_OPENAI_FILE,
    LEGACY_CONFIG_API_KEY_OPENAI_FILE,
    MODELS_CACHE_OPENAI_FILE,
    ensure_project_dirs,
)


def get_api_key(path: Path = CONFIG_API_KEY_OPENAI_FILE) -> str | None:
    env_key = os.getenv("AUDION_OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    env_key_file = os.getenv("AUDION_OPENAI_API_KEY_FILE", "").strip()
    if env_key_file:
        path = Path(env_key_file)
    if path.exists():
        key = path.read_text(encoding="utf-8", errors="ignore").strip()
        if key:
            return key
    for fallback_path in (LEGACY_CONFIG_API_KEY_OPENAI_FILE, API_KEY_OPENAI_FILE):
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
        print(f"[ERROR] File '{CONFIG_API_KEY_OPENAI_FILE}' was not found or is empty.")
        return 1

    try:
        from openai import OpenAI
    except Exception as exc:
        print(f"[ERROR] openai import failed: {exc}")
        return 1

    print("[INFO] Requesting model list from OpenAI API...")
    client = OpenAI(api_key=api_key)

    try:
        models = sorted(
            dict.fromkeys(
                str(item.id).strip()
                for item in client.models.list().data
                if str(getattr(item, "id", "")).strip()
            )
        )

        if not models:
            print("[WARN] No models were returned for this key.")
            return 1

        MODELS_CACHE_OPENAI_FILE.write_text(
            "# OpenAI models available for current key\n\n"
            f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + "\n".join(models)
            + "\n",
            encoding="utf-8",
        )
        print("\n".join(models))
        print(f"\n[OK] Saved to: {MODELS_CACHE_OPENAI_FILE}")
        return 0
    except Exception as exc:
        print(f"[ERROR] OpenAI API request failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
