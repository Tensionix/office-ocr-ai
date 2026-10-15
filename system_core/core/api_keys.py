"""The key files of the providers: add one, set one aside.

Carried over from the window on NiceGUI (app.py `show_add_api_key_dialog`, `show_delete_api_key_dialog`):
a key is a plain .txt file in config\\, the name gets the provider in it, a key taken away is moved
to config\\deleted_keys\\<provider>\\ and never erased. That window had no buttons for Mistral; here every
provider of the OCR has them. The value of a key is never printed - the console command reads it
from the standard input.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

PROVIDERS = ("openai", "gemini", "yandex", "xai", "mistral")
UNSAFE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]+")


def default_filename(provider: str) -> str:
    return "api_key_yandex_studio.txt" if provider == "yandex" else f"api_key_{provider}.txt"


def sanitized_filename(provider: str, raw_name: str) -> str:
    raw = str(raw_name or "").strip().strip("\"'")
    if not raw:
        return default_filename(provider)
    name = UNSAFE.sub("_", Path(raw).name.strip()).strip(" .")
    if not name:
        return default_filename(provider)
    path = Path(name)
    stem = path.stem.strip(" ._") or provider
    if provider not in stem.lower():
        stem = f"api_key_{provider}_{stem}"
    return f"{stem}.txt"


def unique_path(config: Path, provider: str, raw_name: str) -> Path:
    target = (config / sanitized_filename(provider, raw_name)).resolve()
    try:
        target.relative_to(config.resolve())
    except ValueError:
        target = (config / default_filename(provider)).resolve()
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix or '.txt'}")
        if not candidate.exists():
            return candidate
    return target.with_name(f"{target.stem}_{datetime.now():%Y%m%d_%H%M%S}{target.suffix or '.txt'}")


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def add(root: Path, provider: str, raw_name: str, secret: str) -> str:
    """Write a new key file; its path, as the field of the key keeps it (config/…)."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    secret = secret.strip()
    if not secret:
        raise ValueError("the key is empty; no file was created")
    target = unique_path(root / "config", provider, raw_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(secret + "\n", encoding="utf-8", newline="\n")
    return relative(root, target)


def archive_path(config: Path, provider: str, source: Path) -> Path:
    folder = config / "deleted_keys" / provider
    folder.mkdir(parents=True, exist_ok=True)
    safe = UNSAFE.sub("_", source.name).strip(" .") or default_filename(provider)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = folder / f"{stamp}_{safe}.deleted"
    index = 2
    while candidate.exists():
        candidate = folder / f"{stamp}_{index}_{safe}.deleted"
        index += 1
    return candidate


def remove(root: Path, provider: str, selector: str) -> str:
    """Move the key file the field names to config\\deleted_keys\\; where it went."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    from system_core.services import office_service

    key_path = Path(office_service._resolve_key_file(root, provider, selector))  # noqa: SLF001 - the one rule the runs use
    if not key_path.is_file():
        raise ValueError(f"the key file was not found: {key_path}")
    try:
        key_path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"the key lies outside the program and is not moved: {key_path}") from error
    target = archive_path(root / "config", provider, key_path)
    key_path.replace(target)
    return relative(root, target)
