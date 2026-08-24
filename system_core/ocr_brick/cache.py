# cache.py
# Two-layer, content-addressed cache for the preprocess brick.
# L1 = cleaned image (keyed by raw page + CleanConfig).
# L2 = OCR result (keyed by cleaned image + engine + engine params).
# Eviction: explicit size-based LRU using a sidecar index (filesystem atime is
# unreliable on many volumes, so we do not depend on it).
# No globals, no magic paths: the cache root is passed to the constructor.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Iterable


def _key(*parts: bytes | str) -> str:
    h = hashlib.blake2b(digest_size=16)  # fast; same family as the project's BLAKE3 usage
    for p in parts:
        h.update(p if isinstance(p, (bytes, bytearray)) else str(p).encode("utf-8"))
    return h.hexdigest()


class Cache:
    """Content-addressed store safe to reuse across OCR jobs."""

    def __init__(self, root: str | Path, max_bytes: int = 20 * 1024 ** 3) -> None:
        self.root = Path(root)
        self.max_bytes = int(max_bytes)
        self._index = self.root / "index.json"
        (self.root / "prep").mkdir(parents=True, exist_ok=True)
        (self.root / "ocr").mkdir(parents=True, exist_ok=True)

    # --- key -> path (sharded by first byte to avoid huge directories) ---

    def _l1(self, k: str) -> Path:
        return self.root / "prep" / k[:2] / f"{k}.png"

    def _l2(self, k: str) -> Path:
        return self.root / "ocr" / k[:2] / f"{k}.json"

    # --- L1: cleaned image ---

    def l1_get(self, page_bytes: bytes, cfg_canonical: str) -> bytes | None:
        p = self._l1(_key(page_bytes, cfg_canonical))
        if p.is_file():
            self._touch(p)
            return p.read_bytes()
        return None

    def l1_put(self, page_bytes: bytes, cfg_canonical: str, clean_png: bytes) -> Path:
        p = self._l1(_key(page_bytes, cfg_canonical))
        p.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write_bytes(p, clean_png)
        self._touch(p)
        self._enforce_cap()
        return p

    # --- L2: OCR result ---

    def l2_get(self, clean_png: bytes, engine: str, eparams_canonical: str) -> dict | None:
        p = self._l2(_key(clean_png, engine, eparams_canonical))
        if p.is_file():
            self._touch(p)
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def l2_put(self, clean_png: bytes, engine: str, eparams_canonical: str, result: dict) -> Path:
        p = self._l2(_key(clean_png, engine, eparams_canonical))
        p.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write_text(p, json.dumps(result, ensure_ascii=False))
        self._touch(p)
        self._enforce_cap()
        return p

    # --- maintenance ---

    def clear(self) -> None:
        for child in (self.root / "prep", self.root / "ocr"):
            for f in child.rglob("*"):
                if f.is_file():
                    f.unlink()
        if self._index.is_file():
            self._index.unlink()

    def stats(self) -> dict:
        files = list(self._iter_files())
        total = sum(f.stat().st_size for f in files)
        return {"files": len(files), "bytes": total, "max_bytes": self.max_bytes}

    # --- internal: explicit access-time index + LRU eviction ---

    def _iter_files(self) -> Iterable[Path]:
        for child in (self.root / "prep", self.root / "ocr"):
            yield from (f for f in child.rglob("*") if f.is_file())

    def _load_index(self) -> dict[str, float]:
        if self._index.is_file():
            try:
                return json.loads(self._index.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_index(self, idx: dict[str, float]) -> None:
        self._atomic_write_text(self._index, json.dumps(idx))

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_bytes(data)
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    @classmethod
    def _atomic_write_text(cls, path: Path, text: str) -> None:
        cls._atomic_write_bytes(path, text.encode("utf-8"))

    def _touch(self, p: Path) -> None:
        idx = self._load_index()
        idx[str(p.relative_to(self.root))] = time.time()
        self._save_index(idx)

    def _enforce_cap(self) -> None:
        files = list(self._iter_files())
        total = sum(f.stat().st_size for f in files)
        if total <= self.max_bytes:
            return
        idx = self._load_index()
        # oldest access first; unknown entries treated as oldest (atime 0)
        files.sort(key=lambda f: idx.get(str(f.relative_to(self.root)), 0.0))
        for f in files:
            if total <= self.max_bytes:
                break
            sz = f.stat().st_size
            f.unlink()
            idx.pop(str(f.relative_to(self.root)), None)
            total -= sz
        self._save_index(idx)
