import json
from types import SimpleNamespace

from system_core.ocr_brick.engines.mistral import MistralOCRAdapter, _page_markdown, _parse_html_table
from system_core.ocr_brick.engines.regions import LayoutResult, layout_from_dict
from system_core.ocr_brick.pipeline_controller import _normalize_mistral_cached_result, build_ocr_verification
from system_core.services.office_service import _write_ocr_brick_outputs


class _Response:
    status_code = 200
    headers = {}
    text = ""

    def __init__(self, payload):
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")


def test_mistral_ocr_parses_cyrillic_response(monkeypatch, tmp_path):
    key = tmp_path / "api_key_mistral.txt"
    key.write_text("secret", encoding="utf-8")
    image = tmp_path / "page.png"
    image.write_bytes(b"png")
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response(
            {
                "model": "mistral-ocr-4-0",
                "usage_info": {"pages_processed": 1},
                "pages": [
                    {
                        "index": 0,
                        "markdown": "Омская область\n\n| X | Y |\n|---|---|\n| 1 | 2 |",
                        "dimensions": {"width": 1000, "height": 1400},
                        "blocks": [],
                        "tables": [],
                    }
                ],
            }
        )

    monkeypatch.setattr("system_core.ocr_brick.engines.mistral.requests.post", post)
    result = MistralOCRAdapter(key).recognize(str(image), {})

    assert captured["url"] == "https://api.mistral.ai/v1/ocr"
    assert captured["json"]["model"] == "mistral-ocr-4-0"
    assert captured["json"]["include_blocks"] is True
    assert captured["json"]["confidence_scores_granularity"] == "word"
    assert "Омская область" in result.text
    assert result.may_rewrite is False


def test_mistral_html_table_preserves_spans():
    table = _parse_html_table(
        "<table><tr><th rowspan='2'>Точка</th><th colspan='2'>Координаты</th></tr>"
        "<tr><th>X</th><th>Y</th></tr><tr><td>1</td><td>123.4</td><td>567.8</td></tr></table>",
        (10, 20, 300, 100),
    )

    assert table is not None
    assert table.rows == 3
    assert table.cols == 3
    assert table.cells[0].rowspan == 2
    assert table.cells[1].colspan == 2
    assert table.cells[-1].text == "567.8"


def test_layout_metadata_roundtrip():
    source = LayoutResult(
        page=1,
        width=1200,
        height=620,
        engine="mistral",
        metadata={"usage_info": {"pages_processed": 1}, "confidence_scores": {"page": 0.99}},
    )

    restored = layout_from_dict(source.to_dict())

    assert restored.metadata == source.metadata


def test_page_markdown_expands_table_and_repairs_mojibake():
    clean_text = "СП Структурное подразделение"
    mojibake = clean_text.encode("utf-8").decode("cp1251")
    page = {
        "markdown": f"[tbl-0.html](tbl-0.html)\n\n{mojibake}",
        "tables": [{"id": "tbl-0.html", "content": "<table><tr><td>123</td></tr></table>"}],
    }

    text = _page_markdown(page)

    assert clean_text in text
    assert "<td>123</td>" in text
    assert "[tbl-0.html]" not in text


def test_cached_result_is_upgraded_without_api_call():
    cached = {
        "text": "[tbl-0.html](tbl-0.html)",
        "mistral_page": {
            "markdown": "[tbl-0.html](tbl-0.html)",
            "tables": [{"id": "tbl-0.html", "content": "<table><tr><td>456</td></tr></table>"}],
        },
    }

    upgraded = _normalize_mistral_cached_result(cached)

    assert "<td>456</td>" in upgraded["text"]


def test_verification_normalizes_grouping_and_decimal_separator():
    report = build_ocr_verification(
        "Сумма 28 500,000; год 2022; мощность 500",
        "Сумма 28 500.000 год 2022 мощность 500",
        primary_engine="mistral",
        threshold=1.0,
    )

    assert report["status"] == "pass"
    assert report["numeric_agreement"] == 1.0


def test_verification_requires_review_on_numeric_mismatch():
    report = build_ocr_verification(
        "Население 7903; площадь 500; год 2022",
        "Население 7965; площадь 300; год 2021",
        primary_engine="mistral",
        threshold=0.9,
    )

    assert report["status"] == "review"
    assert report["verified"] is False
    assert {item["token"] for item in report["missing_in_tesseract"]} == {"7903", "500", "2022"}


def test_selected_output_formats_write_verification_files(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    context = SimpleNamespace(
        paths=SimpleNamespace(root=tmp_path, output=output),
        log=lambda _message: None,
    )
    results = [{
        "page": 0,
        "text": "Текст",
        "verification": build_ocr_verification(
            "Сумма 500", "Сумма 500", primary_engine="mistral", threshold=1.0
        ),
    }]

    _write_ocr_brick_outputs(context, tmp_path / "scan.pdf", results, {"json", "verification"})

    assert (output / "scan.ocr_brick.json").is_file()
    assert not (output / "scan.ocr_brick.md").exists()
    assert (output / "scan.verification.json").is_file()
    assert (output / "scan.verification.md").is_file()
