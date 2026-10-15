"""What this machine has for OCR: its video card and processor, Tesseract, the layout service of Surya.

The window on NiceGUI asked PowerShell for the video card in its own thread whenever Local OCR or
Project tools was drawn (app.py `hardware_badge_data`) and recommended the installs by it. Here the
same answer is given once, by the console command (`ocr_cli.cmd hardware`), for the badges of the
header and the plates of the installs; the words are given in both languages.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LAYOUT_SERVICE_PORT = 8771
NO_WINDOW = 0x08000000


def powershell_exe() -> str:
    """The PowerShell of the program first (App\\AudionPs.exe), then the one Windows has."""
    own = ROOT / "App" / "AudionPs.exe"
    if own.is_file():
        return str(own)
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(system) if system.is_file() else ""


def powershell_json(script: str, timeout: float = 8.0) -> Any:
    exe = powershell_exe()
    if not exe:
        return None
    wrapped = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
               "$OutputEncoding = [Console]::OutputEncoding; " + script)
    try:
        done = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, check=False, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (done.stdout or "").strip()
    if done.returncode != 0 or not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def video_controllers() -> list[dict[str, Any]]:
    data = powershell_json("Get-CimInstance Win32_VideoController | Select-Object Name,AdapterCompatibility,DriverVersion | ConvertTo-Json -Compress -Depth 3")
    if isinstance(data, dict):
        return [data]
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def cpu_name() -> str:
    data = powershell_json("Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name | ConvertTo-Json -Compress")
    return str(data or "").strip()


def best_gpu(controllers: list[dict[str, Any]]) -> dict[str, Any]:
    named = [item for item in controllers if str(item.get("Name") or "").strip()]
    if not named:
        return {}
    for item in named:
        if any(marker in str(item["Name"]).lower() for marker in ("nvidia", "rtx", "gtx", "radeon", "arc")):
            return item
    return named[0]


def gpu_generation(name: str) -> str:
    low = name.lower()
    if "nvidia" in low or "geforce" in low or "rtx" in low or "gtx" in low:
        match = re.search(r"\b(?:rtx|gtx)?\s*([2453][0-9]{3})\b", low, re.IGNORECASE)
        if match:
            series = int(match.group(1)) // 1000
            return "nvidia50" if series >= 5 else "nvidia40" if series >= 4 else "nvidia"
        return "nvidia"
    if "amd" in low or "radeon" in low or "intel" in low or "iris" in low or "arc" in low:
        return "vulkan"
    return "unknown"


def recommended_installs(generation: str) -> tuple[list[str], list[str]]:
    base = ["install_tesseract", "install_realesrgan", "surya_acceleration", "install_surya_cpu"]
    if generation == "nvidia50":
        return [*base, "install_llamacpp_cuda133"], ["install_surya_pytorch_cuda50"]
    if generation == "nvidia40":
        return [*base, "install_llamacpp_cuda124"], ["install_surya_pytorch_cuda40"]
    if generation == "nvidia":
        return [*base, "install_llamacpp_cuda124"], []
    if generation == "vulkan":
        return [*base, "install_llamacpp_vulkan"], []
    return ["install_tesseract"], ["install_realesrgan", "surya_acceleration", "install_surya_cpu", "install_llamacpp_vulkan"]


WORDS = {
    "nvidia50": ("nvidia", "NVIDIA RTX 50xx detected", "NVIDIA RTX 50xx обнаружена",
                 "Recommended: llama.cpp CUDA 13.3", "Рекомендовано: llama.cpp CUDA 13.3",
                 "Surya backend is automatic: llama.cpp. PyTorch CUDA 50xx/cu128 stays a heavy optional benchmark.",
                 "Surya backend выбирается автоматически: llama.cpp. PyTorch CUDA 50xx/cu128 остаётся тяжёлым optional benchmark."),
    "nvidia": ("nvidia", "NVIDIA GPU detected", "NVIDIA GPU обнаружена",
               "Recommended: llama.cpp CUDA 12.4", "Рекомендовано: llama.cpp CUDA 12.4",
               "Surya backend is automatic: llama.cpp. Install PyTorch CUDA/cu128 only for multiple-speed benchmarks.",
               "Surya backend выбирается автоматически: llama.cpp. PyTorch CUDA/cu128 ставим только если нужен benchmark кратного ускорения."),
    "vulkan": ("vulkan", "Vulkan GPU detected", "Vulkan GPU обнаружена",
               "Recommended: llama.cpp Vulkan", "Рекомендовано: llama.cpp Vulkan",
               "Surya backend is automatic: llama.cpp. Users tune cleanup, not backend plumbing.",
               "Surya backend выбирается автоматически: llama.cpp. Пользователь настраивает очистку, а не backend."),
    "unknown": ("cpu", "GPU not identified", "GPU не распознана",
                "Recommended: Vulkan, then CPU/API", "Рекомендовано: Vulkan, затем CPU/API",
                "Surya backend is automatic: llama.cpp. If Vulkan is not visible, use CPU or API OCR.",
                "Surya backend выбирается автоматически: llama.cpp. Если Vulkan не заработает, остаётся CPU или API OCR."),
}


def layout_service_up(timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", LAYOUT_SERVICE_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def tesseract_state() -> dict[str, Any]:
    try:
        from .tesseract_runtime import resolve_tesseract_runtime, tesseract_languages, tesseract_version

        runtime = resolve_tesseract_runtime()
        exe = getattr(runtime, "exe", None) or getattr(runtime, "path", None)
        found = bool(exe) and Path(str(exe)).is_file()
        return {"found": found, "version": tesseract_version(runtime) if found else "",
                "languages": tesseract_languages(runtime) if found else [], "where": str(exe or "")}
    except Exception as error:  # noqa: BLE001 - a badge must never stop the window
        return {"found": False, "version": "", "languages": [], "where": "", "error": f"{error.__class__.__name__}: {error}"}


def describe() -> dict[str, Any]:
    gpu = best_gpu(video_controllers())
    name = str(gpu.get("Name") or "").strip()
    generation = gpu_generation(name)
    tone, headline, headline_ru, short, short_ru, details, details_ru = WORDS["nvidia" if generation == "nvidia40" else generation]
    recommended, optional = recommended_installs(generation)
    return {
        "gpu": name, "gpu_driver": str(gpu.get("DriverVersion") or ""), "cpu": cpu_name(),
        "generation": generation, "tone": tone,
        "headline": headline, "headline_ru": headline_ru, "short": short, "short_ru": short_ru,
        "details": details, "details_ru": details_ru,
        "recommended_install_ids": recommended, "optional_install_ids": optional,
        "tesseract": tesseract_state(),
        "layout_service": {"port": LAYOUT_SERVICE_PORT, "up": layout_service_up()},
    }
