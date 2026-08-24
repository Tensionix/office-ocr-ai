# engines/yandex_creds.py
# Credential loading for the Yandex adapter. The secret lives in a PLAIN TEXT file
# in the project's config folder (one value per file, no YAML). folder-id is read
# the same way. Nothing is hardcoded: every path is passed in.
# Supports both auth styles -> the right Authorization header is built per type.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _read_secret(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Yandex secret file not found: {p}")
    # tolerate trailing newline / surrounding whitespace from editors
    return p.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class YandexCreds:
    auth_type: str          # "api_key" | "iam"
    secret: str             # the API key OR the IAM token
    folder_id: str          # x-folder-id value

    def auth_header(self) -> str:
        # API key  -> "Api-Key <key>"
        # IAM token-> "Bearer <token>"
        if self.auth_type == "api_key":
            return f"Api-Key {self.secret}"
        if self.auth_type == "iam":
            return f"Bearer {self.secret}"
        raise ValueError(f"unknown auth_type '{self.auth_type}'")

    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": self.auth_header(),
            "x-folder-id": self.folder_id,
        }


def load_creds(spec: dict, project_root: str | Path) -> YandexCreds:
    """Build creds from the engine manifest 'creds' block.

    Expected manifest shape (paths relative to project_root):
      "creds": {
        "auth_type":      "api_key" | "iam",
        "secret_file":    "config/yandex_key.txt",
        "folder_id_file": "config/yandex_folder.txt"
      }
    TODO(codex): align these filenames with the project's actual config/*.txt.
    """
    root = Path(project_root)
    auth_type = spec.get("auth_type", "api_key")
    secret = _read_secret(root / spec["secret_file"])
    folder_id = _read_secret(root / spec["folder_id_file"])
    return YandexCreds(auth_type=auth_type, secret=secret, folder_id=folder_id)
