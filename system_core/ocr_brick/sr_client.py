# sr_client.py
# Thin wrapper around the Real-ESRGAN ncnn-Vulkan binary (no CUDA, no PyTorch).
# Invoked list-based (never a shell string). Paths are passed in, not assumed.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

# Map our abstract knobs -> concrete ncnn model names.
# [VERIFY] against the INSTALLED binary: model names and whether a denoise
# strength flag (e.g. -dn) exists. Names below are the common upstream set.
_MODEL = {
    "sharp": "realesrgan-x4plus",          # crisp, amplifies artifacts -> clean PNG only
    "general": "realesrgan-x4plus",        # portable upstream zip ships this ncnn model
    "general_wdn": "realesrgan-x4plus",    # TODO(codex): add extra ncnn denoise model asset
}


class SRClient:
    """Holds the binary path + GPU selection; one warm instance per service."""

    def __init__(self, ncnn_exe: str | Path, gpu: str = "auto") -> None:
        self.exe = Path(ncnn_exe)
        if not self.exe.is_file():
            raise FileNotFoundError(f"ncnn-vulkan binary not found: {self.exe}")
        self.models_dir = self.exe.parent / "models"
        self.gpu = gpu  # "auto" | "cpu" | "0" | "1" ...
        self.last_device = gpu
        self.last_error = ""

    def _gpu_arg(self) -> list[str]:
        if self.gpu == "cpu":
            return ["-g", "-1"]
        if self.gpu == "auto":
            return []  # let the binary pick; falls back to CPU if no device
        return ["-g", str(self.gpu)]

    def _model_name(self, sr_model: str, denoise: str) -> str:
        if sr_model == "general" and denoise == "strong":
            return _MODEL["general_wdn"]
        return _MODEL.get(sr_model, _MODEL["general"])

    def enhance_bytes(self, png_bytes: bytes, sr_model: str, denoise: str, scale: int) -> bytes:
        """Upscale PNG bytes -> PNG bytes. Uses temp files because the CLI is file-based."""
        if self.gpu == "cpu":
            self.last_device = "cpu-pil"
            return self._pil_upscale(png_bytes, scale)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.png"
            dst = Path(td) / "out.png"
            src.write_bytes(png_bytes)
            cmd_base = [
                str(self.exe),
                "-i", str(src),
                "-o", str(dst),
                "-n", self._model_name(sr_model, denoise),
                "-m", str(self.models_dir),
                "-s", str(scale),
                "-f", "png",
            ]
            try:
                subprocess.run([*cmd_base, *self._gpu_arg()], check=True, capture_output=True)
                self.last_device = self.gpu
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
                stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
                self.last_error = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
                self.last_device = "cpu-pil"
                return self._pil_upscale(png_bytes, scale)
            return dst.read_bytes()

    def probe_devices(self) -> dict:
        """Best-effort device info for /health. TODO(codex): parse real output if
        the installed binary exposes a list flag; otherwise report configured gpu."""
        return {"configured_gpu": self.gpu, "last_device": self.last_device, "last_error": self.last_error}

    @staticmethod
    def _pil_upscale(png_bytes: bytes, scale: int) -> bytes:
        with Image.open(BytesIO(png_bytes)) as img:
            factor = max(1, int(scale or 1))
            out = img.convert("RGB").resize(
                (img.width * factor, img.height * factor),
                Image.Resampling.LANCZOS,
            )
            buf = BytesIO()
            out.save(buf, format="PNG")
            return buf.getvalue()
