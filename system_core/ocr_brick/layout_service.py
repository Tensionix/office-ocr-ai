# layout_service.py
# Warm host for heavy engines (Surya): the model loads ONCE here, and
# clients call /ocr and /layout over 127.0.0.1. Mirrors preprocess_service.
# Adapters are cached per engine name. No module-level config: state built in
# build_app from explicit paths. EN comments only. UTF-8 without BOM.
# Requires: fastapi, uvicorn, requests. Heavy engines need their own frameworks.

from __future__ import annotations

import argparse
import base64
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .engines import registry


def build_app(project_root: Path) -> FastAPI:
    app = FastAPI(title="Audion Layout Service")
    manifest = registry.load_engines(project_root / "ocr.engines.json")
    warm: dict[str, object] = {}     # engine name -> adapter (model loaded once)

    def get_adapter(name: str):
        if name not in warm:
            adapter = registry.build_adapter(name, manifest, project_root)
            if not hasattr(adapter, "analyze_layout"):
                raise HTTPException(status_code=400,
                                    detail=f"engine '{name}' has no layout capability")
            warm[name] = adapter
        return warm[name]

    def _to_tmp(image_b64: str) -> str:
        data = base64.b64decode(image_b64)
        fp = Path(tempfile.mkstemp(suffix=".png")[1])
        fp.write_bytes(data)
        return str(fp)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "warm_engines": sorted(warm.keys())}

    @app.post("/ocr")
    def ocr(req: dict) -> dict:
        try:
            adapter = get_adapter(req["engine"])
            path = _to_tmp(req["image_b64"])
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        try:
            return adapter.recognize(path, req.get("params", {})).to_dict()
        finally:
            Path(path).unlink(missing_ok=True)

    @app.post("/layout")
    def layout(req: dict) -> dict:
        try:
            adapter = get_adapter(req["engine"])
            path = _to_tmp(req["image_b64"])
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        try:
            return adapter.analyze_layout(path, int(req.get("page", 0))).to_dict()
        finally:
            Path(path).unlink(missing_ok=True)

    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--port", type=int, default=8771)
    args = ap.parse_args()
    import uvicorn
    uvicorn.run(build_app(Path(args.root).resolve()), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
