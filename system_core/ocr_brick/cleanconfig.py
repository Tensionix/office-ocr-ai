# cleanconfig.py
# Resolved cleaning configuration for the Audion preprocess brick.
# No module-level state, no hardcoded paths. Everything is passed in.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CleanConfig:
    """Fully resolved config. The pipeline is a pure function of this + page bytes."""
    enabled: bool            # MASTER: False = raw passthrough, whole pipeline skipped
    target_engine: str       # tesseract|surya|yandex|vision
    sr_scale: int            # 0(off)|2|4
    sr_model: str            # auto|sharp|general
    denoise: str             # none|weak|strong
    contrast: str            # auto|normal|high
    unsharp: str             # auto|off|weak|strong
    source_format: str       # auto|jpeg|png   (resolved away from "auto" before use)
    strip_vlines: bool
    deskew: bool
    binarize: str            # auto|on|off
    intent: str              # text|image
    gpu: str                 # auto|cpu|"0"|"1"...

    def canonical(self) -> str:
        """Stable key material for the cache. Sorted, no whitespace."""
        payload = asdict(self)
        payload["_pipeline_version"] = 2
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    # --- resolved helpers (call these in the pipeline, never read raw "auto") ---

    def binarize_on(self) -> bool:
        if self.binarize == "on":
            return True
        if self.binarize == "off":
            return False
        # "auto": on only for Tesseract, and never in image-preserving intent
        return self.target_engine == "tesseract" and self.intent != "image"

    def sr_model_resolved(self) -> str:
        if self.sr_model != "auto":
            return self.sr_model
        # "auto": denoise-capable general for JPEG, sharp for clean PNG
        return "sharp" if self.source_format == "png" else "general"


def load_profiles(profiles_path: str | Path) -> dict[str, Any]:
    """Load preprocess.profiles.json. Path is given, not assumed."""
    p = Path(profiles_path)
    if not p.is_file():
        raise FileNotFoundError(f"profiles manifest not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def detect_source_format(original_name: str) -> str:
    """Cheap sniff from extension. TODO(codec): add magic-byte fallback if needed."""
    ext = Path(original_name).suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        return "jpeg"
    if ext == "png":
        return "png"
    return "jpeg"  # conservative default: assume compression artifacts present


def resolve(
    profiles: dict[str, Any],
    target_engine: str,
    gui_overrides: dict[str, Any] | None = None,
    original_name: str = "",
) -> CleanConfig:
    """profile_defaults(engine) (+) gui_overrides -> CleanConfig.

    `gui_overrides` is whatever the GUI changed; everything else falls back to the
    engine profile. `original_name` is used only to resolve source_format=="auto".
    """
    gui_overrides = dict(gui_overrides or {})
    prof = profiles.get("profiles", {}).get(target_engine)
    if prof is None:
        raise KeyError(f"no profile for engine '{target_engine}' in manifest")

    base = {
        "enabled": True,
        "target_engine": target_engine,
        "sr_scale": prof.get("sr_scale", 2),
        "sr_model": prof.get("sr_model", "auto"),
        "denoise": prof.get("denoise", "weak"),
        "contrast": prof.get("contrast", "auto"),
        "unsharp": prof.get("unsharp", "auto"),
        "source_format": prof.get("source_format", "auto"),
        "strip_vlines": prof.get("strip_vlines", False),
        "deskew": prof.get("deskew", True),
        "binarize": prof.get("binarize", "auto"),
        "intent": prof.get("intent", "text"),
        "gpu": profiles.get("engine", {}).get("gpu", "auto"),
    }
    base.update({k: v for k, v in gui_overrides.items() if k in base})

    cfg = CleanConfig(**base)

    # resolve source_format=="auto" now so the cache key is concrete
    if cfg.source_format == "auto":
        fmt = detect_source_format(original_name) if original_name else "jpeg"
        cfg = replace(cfg, source_format=fmt)
        # PNG sources have no JPEG ringing -> default denoise off unless GUI set it
        if fmt == "png" and "denoise" not in gui_overrides:
            cfg = replace(cfg, denoise="none")
    return cfg
