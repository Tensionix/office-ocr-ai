"""Lossless, provider-neutral document package for OCR and office exports.

The JSON manifest is deliberately not a presentation format. It references exact
source/page assets stored beside it and keeps every provider result, verification
record and future manual correction so exports can be rebuilt without paid OCR.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


MODEL_VERSION = "1.1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class SourceAsset:
    name: str
    path: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass
class PageModel:
    index: int
    width: int
    height: int
    dpi: int
    source_page_image: str
    ocr_page_image: str
    source_page_sha256: str
    ocr_page_sha256: str
    primary_engine: str
    primary_text: str
    primary_words: list[dict[str, Any]] = field(default_factory=list)
    regions: list[dict[str, Any]] = field(default_factory=list)
    reading_order: list[int] = field(default_factory=list)
    ocr_candidates: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    manual_corrections: list[dict[str, Any]] = field(default_factory=list)
    raw_result: dict[str, Any] = field(default_factory=dict)
    fused_text: str = ""
    fused_regions: list[dict[str, Any]] = field(default_factory=list)
    fusion: dict[str, Any] = field(default_factory=dict)
    provider_verifications: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class DocumentModel:
    version: str
    document_id: str
    created_at: str
    source: SourceAsset
    pages: list[PageModel]
    metadata: dict[str, Any] = field(default_factory=dict)
    manual_corrections: list[dict[str, Any]] = field(default_factory=list)
    export_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DocumentModel":
        return cls(
            version=str(value.get("version") or MODEL_VERSION),
            document_id=str(value.get("document_id") or ""),
            created_at=str(value.get("created_at") or ""),
            source=SourceAsset(**dict(value.get("source") or {})),
            pages=[PageModel(**dict(page)) for page in value.get("pages") or []],
            metadata=dict(value.get("metadata") or {}),
            manual_corrections=list(value.get("manual_corrections") or []),
            export_history=list(value.get("export_history") or []),
        )


def _image_size(package_dir: Path, relative_path: str) -> tuple[int, int]:
    path = package_dir / relative_path
    if not path.is_file():
        return 0, 0
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _regions_from_result(result: dict[str, Any], page_index: int) -> tuple[list[dict[str, Any]], int, int]:
    if isinstance(result.get("regions"), list):
        return list(result.get("regions") or []), int(result.get("width") or 0), int(result.get("height") or 0)
    raw_page = result.get("mistral_page")
    if isinstance(raw_page, dict):
        from system_core.ocr_brick.engines.mistral import layout_from_mistral_page

        layout = layout_from_mistral_page(
            raw_page,
            page=page_index,
            usage_info=dict(result.get("usage_info") or {}),
        )
        payload = layout.to_dict()
        return list(payload.get("regions") or []), int(payload.get("width") or 0), int(payload.get("height") or 0)
    return [], 0, 0


def create_document_model(
    source_path: str | Path,
    results: list[dict[str, Any]],
    package_dir: str | Path,
    *,
    engine: str,
    preprocess: dict[str, Any] | None = None,
    engine_params: dict[str, Any] | None = None,
) -> DocumentModel:
    source = Path(source_path)
    package = Path(package_dir)
    (package / "source").mkdir(parents=True, exist_ok=True)
    (package / "pages").mkdir(parents=True, exist_ok=True)
    (package / "providers").mkdir(parents=True, exist_ok=True)
    source_copy = package / "source" / source.name
    if source.resolve() != source_copy.resolve():
        shutil.copy2(source, source_copy)
    source_hash = _sha256(source_copy)
    source_asset = SourceAsset(
        name=source.name,
        path=f"source/{source.name}",
        media_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
        size_bytes=source_copy.stat().st_size,
        sha256=source_hash,
    )

    pages: list[PageModel] = []
    for index, result in enumerate(results):
        assets = dict(result.get("assets") or {})
        source_image = str(assets.get("source_page_image") or "")
        ocr_image = str(assets.get("ocr_page_image") or source_image)
        width, height = _image_size(package, ocr_image)
        regions, layout_width, layout_height = _regions_from_result(result, index)
        width = width or layout_width
        height = height or layout_height
        primary_text = str(result.get("text") or "")
        primary_words = list(result.get("words") or [])
        candidates: list[dict[str, Any]] = [{
            "engine": engine,
            "text": primary_text,
            "words": primary_words,
            "may_rewrite": bool(result.get("may_rewrite", False)),
        }]
        second_pass = result.get("tesseract_2pass")
        if isinstance(second_pass, dict) and second_pass.get("ok"):
            candidates.append({
                "engine": "tesseract",
                "text": str(second_pass.get("text") or ""),
                "words": list(second_pass.get("words") or []),
                "lang": second_pass.get("lang"),
                "psm": second_pass.get("psm"),
            })
        yandex_pass = result.get("yandex_2pass")
        if isinstance(yandex_pass, dict) and yandex_pass.get("ok") and not yandex_pass.get("skipped"):
            candidates.append({
                "engine": "yandex",
                "text": str(yandex_pass.get("text") or ""),
                "words": list(yandex_pass.get("words") or []),
                "model": yandex_pass.get("model"),
                "scope": yandex_pass.get("scope"),
            })
        fusion = dict(result.get("fusion") or {})
        provider_dir = package / "providers" / engine
        provider_dir.mkdir(parents=True, exist_ok=True)
        provider_result = provider_dir / f"page-{index + 1:04d}.json"
        provider_result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for provider_name, provider_payload in (
            ("tesseract", second_pass),
            ("yandex", yandex_pass),
        ):
            if not isinstance(provider_payload, dict) or not provider_payload.get("ok") or provider_payload.get("skipped"):
                continue
            secondary_dir = package / "providers" / provider_name
            secondary_dir.mkdir(parents=True, exist_ok=True)
            (secondary_dir / f"page-{index + 1:04d}.json").write_text(
                json.dumps(provider_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        pages.append(PageModel(
            index=index,
            width=width,
            height=height,
            dpi=int(assets.get("raster_dpi") or 300),
            source_page_image=source_image,
            ocr_page_image=ocr_image,
            source_page_sha256=str(assets.get("source_page_sha256") or ""),
            ocr_page_sha256=str(assets.get("ocr_page_sha256") or ""),
            primary_engine=engine,
            primary_text=primary_text,
            primary_words=primary_words,
            regions=regions,
            reading_order=list(range(len(regions))),
            ocr_candidates=candidates,
            verification=dict(result.get("verification") or {}),
            raw_result=dict(result),
            fused_text=str(fusion.get("text") or ""),
            fused_regions=list(fusion.get("regions") or []),
            fusion=fusion,
            provider_verifications={
                key: value
                for key, value in {
                    "tesseract": result.get("verification"),
                    "yandex": result.get("yandex_verification"),
                }.items()
                if isinstance(value, dict)
            },
        ))

    model = DocumentModel(
        version=MODEL_VERSION,
        document_id=source_hash[:24],
        created_at=datetime.now(timezone.utc).isoformat(),
        source=source_asset,
        pages=pages,
        metadata={
            "engine": engine,
            "preprocess": dict(preprocess or {}),
            "engine_params": _redact_params(dict(engine_params or {})),
            "lossless_package": True,
        },
    )
    write_document_model(model, package / "document.json")
    return model


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in params.items():
        lowered = key.lower()
        out[key] = "[redacted]" if any(token in lowered for token in ("key", "token", "secret", "password")) else value
    return out


def write_document_model(model: DocumentModel, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_document_model(path: str | Path) -> DocumentModel:
    return DocumentModel.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
