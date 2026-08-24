# preprocess_service.py
# Warm local service: loads the SR client once, serves cleaning over 127.0.0.1.
# Run via the PowerShell brick (Preprocess.Service.ps1). Bind localhost only.
# No globals leaking config: state is built in main() from CLI args + manifest.
# EN comments only. UTF-8 without BOM.
#
# Requires: fastapi, uvicorn, opencv-python, numpy. SR via ncnn-vulkan binary.

from __future__ import annotations

import argparse
import base64
import json
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException

from . import cleanconfig, preprocess
from .sr_client import SRClient


def resolve_ncnn_exe(profiles_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    brick_root = profiles_path.parent
    project_root = brick_root.parents[1]
    candidates = [
        brick_root / raw_path,
        project_root / raw_path,
        project_root / "tools" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
        project_root / "runtime" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
        project_root / "runtime" / "realesrgan-ncnn-vulkan.exe",
    ]
    for item in candidates:
        if item.is_file():
            return item
    found = shutil.which("realesrgan-ncnn-vulkan") or shutil.which("realesrgan-ncnn-vulkan.exe")
    return Path(found) if found else candidates[0]


def build_app(profiles_path: Path, port: int) -> FastAPI:
    app = FastAPI(title="Audion Preprocess Service")

    profiles = cleanconfig.load_profiles(profiles_path)
    eng = profiles.get("engine", {})
    exe = resolve_ncnn_exe(profiles_path, eng.get("ncnn_exe", "bin/realesrgan-ncnn-vulkan.exe"))

    state: dict = {"sr": None, "sr_error": None}
    try:
        state["sr"] = SRClient(exe, gpu=eng.get("gpu", "auto"))
    except Exception as e:  # graceful: service still answers, SR disabled
        state["sr_error"] = str(e)

    @app.get("/health")
    def health() -> dict:
        ok = state["sr"] is not None
        info = state["sr"].probe_devices() if ok else {}
        return {"ok": ok, "sr_error": state["sr_error"], "device": info, "port": port}

    @app.post("/prep")
    def prep(req: dict) -> dict:
        """Body: { page_b64, target_engine, gui_overrides?, original_name? }.
        Returns: { clean_b64 }."""
        try:
            page = base64.b64decode(req["page_b64"])
            cfg = cleanconfig.resolve(
                profiles,
                target_engine=req["target_engine"],
                gui_overrides=req.get("gui_overrides"),
                original_name=req.get("original_name", ""),
            )
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

        if cfg.sr_scale and cfg.sr_scale > 0 and state["sr"] is None:
            raise HTTPException(status_code=503, detail=f"SR unavailable: {state['sr_error']}")

        # NOTE: cache is wired by the caller/GUI, not the service (job-scoped root).
        out = preprocess.clean_page(page, cfg, cache=None, sr=state["sr"])
        return {"clean_b64": base64.b64encode(out).decode("ascii"),
                "config": json.loads(cfg.canonical())}

    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    # Default profiles path is relative to THIS file, never the CWD.
    ap.add_argument("--profiles", default=str(Path(__file__).with_name("preprocess.profiles.json")))
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args()

    import uvicorn
    app = build_app(Path(args.profiles).resolve(), args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
