import json

from system_core.ocr_brick.engines.xai import XAIAdapter
from system_core.ocr_brick.engines.base import OcrResult
from system_core.ocr_brick.pipeline_controller import PipelineController, _russian_quality_flags


class _Response:
    status_code = 200
    headers = {}
    text = ""

    def __init__(self, payload):
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")


def test_xai_ocr_retries_transient_transport_error(monkeypatch, tmp_path):
    key = tmp_path / "api_key_xai.txt"
    key.write_text("secret", encoding="utf-8")
    image = tmp_path / "page.png"
    image.write_bytes(b"png")
    calls = {"count": 0}

    def post(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            import requests
            raise requests.ConnectionError("mobile network dropped")
        return _Response({"choices": [{"message": {"content": "Привет, мир"}}]})

    monkeypatch.setattr("system_core.ocr_brick.engines.xai.requests.post", post)
    monkeypatch.setattr("system_core.ocr_brick.engines.xai.time.sleep", lambda _delay: None)
    result = XAIAdapter(key, max_attempts=2).recognize(str(image), {})

    assert calls["count"] == 2
    assert result.text == "Привет, мир"


def test_russian_quality_flags_are_conservative():
    assert _russian_quality_flags("Иванов Иван Иванович, Омская область") == []
    assert "mixed_latin_cyrillic" in _russian_quality_flags("Иваноv Иван")
    assert "replacement_character" in _russian_quality_flags("Иванов \ufffd Иван")


def test_russian_review_requires_checkbox_and_suspicious_text(tmp_path):
    controller = PipelineController(tmp_path)

    class Adapter:
        calls = 0

        def recognize(self, _path, _params):
            self.calls += 1
            return OcrResult(kind="vision", text="Иванов Иван", words=[], engine="xai")

    adapter = Adapter()
    clean = {"text": "Иванов Иван Иванович, Омская область"}
    disabled = controller._russian_review(adapter, "page.png", {}, dict(clean))
    enabled_clean = controller._russian_review(
        adapter, "page.png", {"russian_review_enabled": True}, dict(clean)
    )
    suspicious = controller._russian_review(
        adapter,
        "page.png",
        {"russian_review_enabled": True},
        {"text": "Иваноv Иван"},
    )

    assert adapter.calls == 1
    assert disabled["russian_review"]["applied"] is False
    assert enabled_clean["russian_review"]["applied"] is False
    assert suspicious["russian_review"]["applied"] is True
