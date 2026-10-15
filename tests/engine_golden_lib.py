"""Reference runs of the OCR engine: fixtures, a stand, network stubs, digests of results.

The engine (system_core) stays when the window moves to Avalonia, but the Python environment
around it is trimmed and the console command is rebuilt. These runs pin what the engine makes
today, so that both changes can be checked against it: tests\\engine_golden.json is written by
tests\\record_engine_golden.py and compared by tests\\test_engine_golden.py.

The stand. A run needs a project: scripts are started from `system_core`, with the project as the
working folder and `runtime\\python.exe` as Python. The stand is a copy of `system_core` and of the
non-secret part of `config`, with `runtime` linked (a junction, no copy) and fake key files - the
real keys never come near a reference run.

The network. Paid providers are never called. In the process, `requests` and `httpx` answer from
canned replies and record what would have been sent; a socket guard refuses anything else that is
not loopback. Scripts started as child processes get a dead proxy, so a request that slips through
fails instead of leaving the machine - and it would carry only the fake key.

The digest. Outputs are compared by content, not bytes: text of Markdown and HTML, paragraphs and
tables of DOCX, cells of XLSX, text of every PDF page, pixels of images, JSON without timestamps.
Paths of the stand are replaced by <STAND>.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECORD_PARAMS = PROJECT_ROOT / "tests" / "former_window_parameters.json"
FONT = Path(r"C:\Windows\Fonts\arial.ttf")
FAKE_KEY = "TEST-KEY-NOT-REAL"
DEAD_PROXY = "http://127.0.0.1:9"
VOLATILE_KEYS = re.compile(r"(^|_)(created|updated|started|finished|generated|checked|modified)(_at)?$|elapsed|duration|timestamp|_seconds$|_sec$|^time$|^date$", re.I)
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}[:\-]\d{2}[:\-]\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?")
BIG_TEXT = 3000
# Measured times in reports: "elapsed_sec: 0.331", "took 1.2 s".
MEASURED = re.compile(r"((?:elapsed|duration|took|seconds|time)[\w ]{0,12}[:=]?\s*)\d+(?:[.,]\d+)?", re.I)
# A line of a Python traceback names the line of the source: any change above it moves the number,
# and a case that fails on purpose would differ while it fails the same way.
TRACEBACK_LINE = re.compile(r'(File "[^"]+", line )\d+')
FIXED_TIME = __import__("datetime").datetime(2026, 1, 1, 0, 0, 0)


# ---------------------------------------------------------------- the stand


def build_stand(stand: Path) -> Path:
    """A project the engine can run in: code and settings copied, runtime linked, fake keys."""
    if stand.exists():
        _unlink_runtime(stand)
        shutil.rmtree(stand)
    stand.mkdir(parents=True)
    shutil.copytree(
        PROJECT_ROOT / "system_core",
        stand / "system_core",
        ignore=shutil.ignore_patterns("powershell", "__pycache__", "cache", "fzf.exe", "license"),
    )
    (stand / "config").mkdir()
    for item in (PROJECT_ROOT / "config").iterdir():
        if item.is_file() and not _is_secret(item.name):
            shutil.copy2(item, stand / "config" / item.name)
    for name in ("api_key_openai.txt", "api_key_gemini.txt", "api_key_mistral.txt", "api_key_xai.txt", "api_key_yandex_studio.txt"):
        (stand / "config" / name).write_text(FAKE_KEY, encoding="utf-8")
    (stand / "config" / "yandex_folder.txt").write_text("b1gtestfolder", encoding="utf-8")
    (stand / "config" / "path_history.json").write_text("{}", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(stand / "runtime"), str(PROJECT_ROOT / "runtime")], check=True, capture_output=True)
    for folder in ("input", "output", "logs", "report", "workspace", "release", "data"):
        (stand / folder).mkdir(exist_ok=True)
    return stand


def remove_stand(stand: Path) -> None:
    if stand.exists():
        _unlink_runtime(stand)
        shutil.rmtree(stand, ignore_errors=True)


def _unlink_runtime(stand: Path) -> None:
    link = stand / "runtime"
    if link.exists() or link.is_symlink():
        # A junction is removed with rmdir, which never touches what it points to.
        subprocess.run(["cmd", "/c", "rmdir", str(link)], check=False, capture_output=True)


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("api_key_") or lowered in {"yandex_folder.txt", "yandex_key_id.txt", "yandex_key.txt", "path_history.json"}


def reset_work_folders(stand: Path) -> None:
    for folder in ("input", "output", "logs", "report", "workspace"):
        target = stand / folder
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()


# ---------------------------------------------------------------- fixtures


def make_fixtures(base: Path) -> dict[str, Path]:
    """Deterministic source files. Returns named sources (files or folders)."""
    base.mkdir(parents=True, exist_ok=True)
    office = base / "office"
    office.mkdir(exist_ok=True)
    _make_docx(office / "report.docx")
    _make_xlsx(office / "budget.xlsx")
    _make_pptx(office / "slides.pptx")
    _make_text_pdf(office / "letter.pdf")
    (office / "notes.txt").write_text("Заметки к проекту\nОмская область, 2026 год.\nTotal: 1 234 567,89\n", encoding="utf-8")
    (office / "data.csv").write_text("Код;Наименование;Сумма\n1;Омск;1200,50\n2;Тара;340\n", encoding="utf-8")
    (office / "page.html").write_text(
        "<html><head><meta charset='utf-8'><title>Проба</title></head><body><h1>Заголовок</h1>"
        "<p>Абзац с <b>жирным</b> словом.</p><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></body></html>",
        encoding="utf-8",
    )

    scans = base / "scans"
    scans.mkdir(exist_ok=True)
    _make_scan(scans / "page.png")

    markdown = base / "markdown"
    markdown.mkdir(exist_ok=True)
    (markdown / "note.md").write_text(
        "# Пояснительная записка\n\nВводный абзац о проекте планировки.\n\n## Таблица показателей\n\n"
        "| № | Показатель | Значение |\n|---|---|---|\n| 1 | Площадь, га | 12,5 |\n| 2 | Население, чел. | 3 400 |\n\n"
        "- первый пункт\n- второй пункт\n",
        encoding="utf-8",
    )

    coords = base / "coords"
    coords.mkdir(exist_ok=True)
    _make_coordinates_pdf(coords / "coords.pdf")
    return {"office": office, "scan": scans / "page.png", "scans": scans, "markdown": markdown, "coords": coords / "coords.pdf"}


def _make_docx(path: Path) -> None:
    from docx import Document

    document = Document()
    document.core_properties.created = FIXED_TIME
    document.core_properties.modified = FIXED_TIME
    document.add_heading("Отчёт о проверке", level=1)
    document.add_paragraph("Первый абзац отчёта: Омская область, договор № 2026-117 от 15.10.2026.")
    table = document.add_table(rows=2, cols=3)
    for row, values in enumerate((("Код", "Объект", "Сумма"), ("1", "Школа", "1 200,50"))):
        for column, value in enumerate(values):
            table.cell(row, column).text = value
    document.add_paragraph("Итог: 1 200,50 руб.")
    document.save(path)
    _freeze_zip_times(path)


def _make_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Бюджет"
    for row in (("Статья", "Сумма"), ("Связь", 1200.5), ("Аренда", 340), ("Итого", 1540.5)):
        sheet.append(row)
    second = workbook.create_sheet("Notes")
    second.append(["Comment", "Value"])
    second.append(["Checked", True])
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    workbook.save(path)
    _freeze_zip_times(path)


def _make_pptx(path: Path) -> None:
    from pptx import Presentation

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Проект планировки"
    slide.placeholders[1].text = "Первый пункт\nВторой пункт"
    second = presentation.slides.add_slide(presentation.slide_layouts[5])
    second.shapes.title.text = "Итоги 2026"
    presentation.save(path)
    _freeze_zip_times(path)


def _make_text_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    for number, lines in enumerate((("Письмо № 15", "Омская область, 2026 год."), ("Страница вторая", "Итог: 1 234 567,89 руб.")), start=1):
        page = document.new_page(width=595, height=842)
        y = 80
        for line in lines:
            page.insert_text((72, y), line, fontsize=14, fontfile=str(FONT), fontname="arial")
            y += 28
    document.set_metadata({})
    document.save(path, no_new_id=True)


def _make_scan(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 40)
    lines = (
        "АКТ ПРОВЕРКИ № 2026-117",
        "Омская область, город Тара",
        "Contract No 2026-117 dated 15.10.2026",
        "Итого: 1 234 567,89 руб.",
    )
    for index, line in enumerate(lines):
        draw.text((80, 80 + index * 90), line, fill="black", font=font)
    for index, (code, x, y) in enumerate((("1", "452 123,45", "2 312 456,78"), ("2", "452 130,10", "2 312 470,05"))):
        draw.text((80, 520 + index * 70), f"{code}    {x}    {y}", fill="black", font=font)
    image.save(path, optimize=False)


def _make_coordinates_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page(width=595, height=842)
    rows = (("№", "X", "Y"), ("1", "452123.45", "2312456.78"), ("2", "452130.10", "2312470.05"), ("3", "452141.92", "2312481.33"))
    for index, row in enumerate(rows):
        for column, value in enumerate(row):
            page.insert_text((72 + column * 140, 100 + index * 24), value, fontsize=12, fontfile=str(FONT), fontname="arial")
    document.set_metadata({})
    document.save(path, no_new_id=True)


def _freeze_zip_times(path: Path) -> None:
    """Office files are ZIPs with the time of saving in every entry; fix it so fixtures are byte-stable."""
    source = path.read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as old, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as new:
        for info in old.infolist():
            data = old.read(info.filename)
            fixed = zipfile.ZipInfo(info.filename, date_time=(2026, 1, 1, 0, 0, 0))
            fixed.compress_type = zipfile.ZIP_DEFLATED
            fixed.external_attr = info.external_attr
            if info.filename == "docProps/core.xml":
                data = re.sub(rb"<dcterms:(created|modified)[^>]*>[^<]*</dcterms:\1>", b"", data)
            new.writestr(fixed, data)
    path.write_bytes(output.getvalue())


# ---------------------------------------------------------------- network stubs


class FakeResponse:
    def __init__(self, url: str, payload: Any, status: int = 200) -> None:
        self.url = url
        self.status_code = status
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.text = self.content.decode("utf-8")
        self.encoding = "utf-8"
        self.ok = status < 400

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def canned_reply(url: str, body: Any) -> Any:
    """A reply in the shape each provider returns. The text says which provider answered."""
    if "ocr.api.cloud.yandex.net" in url:
        lines = ["АКТ ПРОВЕРКИ № 2026-117", "Омская область, город Тара", "Итого: 1 234 567,89 руб."]
        return {
            "result": {
                "textAnnotation": {
                    "width": "1600",
                    "height": "900",
                    "blocks": [
                        {
                            "lines": [
                                {
                                    "text": line,
                                    "words": [
                                        {
                                            "text": word,
                                            "boundingBox": {"vertices": [{"x": 80 + i * 160, "y": 80 + n * 90}, {"x": 220 + i * 160, "y": 80 + n * 90}, {"x": 220 + i * 160, "y": 120 + n * 90}, {"x": 80 + i * 160, "y": 120 + n * 90}]},
                                            "confidence": 0.98,
                                        }
                                        for i, word in enumerate(line.split())
                                    ],
                                }
                                for n, line in enumerate(lines)
                            ]
                        }
                    ],
                    "fullText": "\n".join(lines),
                }
            }
        }
    if "api.mistral.ai" in url:
        return {
            "model": (body or {}).get("model", "mistral-ocr-4-0"),
            "usage_info": {"pages_processed": 1},
            "pages": [
                {
                    "index": 0,
                    "markdown": "АКТ ПРОВЕРКИ № 2026-117\n\nОмская область, город Тара\n\n| № | X | Y |\n|---|---|---|\n| 1 | 452 123,45 | 2 312 456,78 |",
                    "dimensions": {"width": 1600, "height": 900, "dpi": 200},
                    "blocks": [],
                    "tables": [],
                }
            ],
        }
    if "api.x.ai" in url:
        return {
            "id": "stub",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "АКТ ПРОВЕРКИ № 2026-117 (xAI)\nОмская область, город Тара\nИтого: 1 234 567,89 руб."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
    if "api.openai.com" in url:
        return {
            "id": "resp_stub",
            "object": "response",
            "created_at": 1760000000,
            "status": "completed",
            "model": (body or {}).get("model", "gpt-4.1"),
            "output": [
                {
                    "type": "message",
                    "id": "msg_stub",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "АКТ ПРОВЕРКИ № 2026-117 (ChatGPT)\nОмская область, город Тара", "annotations": []}],
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    if "generativelanguage.googleapis.com" in url:
        return {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "АКТ ПРОВЕРКИ № 2026-117 (Gemini)\nОмская область, город Тара"}]},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "totalTokenCount": 120},
            "modelVersion": "stub",
        }
    raise ConnectionRefusedError(f"reference run: no canned reply for {url}")


def openai_events(response: dict[str, Any]) -> bytes:
    """The Responses API as a stream: created, the text in one delta, completed."""
    item = response["output"][0]
    part = item["content"][0]
    text = part["text"]
    started = {**response, "status": "in_progress", "output": []}
    empty_item = {**item, "status": "in_progress", "content": []}
    empty_part = {**part, "text": ""}
    where = {"item_id": item["id"], "output_index": 0, "content_index": 0}
    events = [
        ("response.created", {"type": "response.created", "response": started}),
        ("response.in_progress", {"type": "response.in_progress", "response": started}),
        ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": empty_item}),
        ("response.content_part.added", {"type": "response.content_part.added", **where, "part": empty_part}),
        ("response.output_text.delta", {"type": "response.output_text.delta", **where, "delta": text, "logprobs": []}),
        ("response.output_text.done", {"type": "response.output_text.done", **where, "text": text, "logprobs": []}),
        ("response.content_part.done", {"type": "response.content_part.done", **where, "part": part}),
        ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
        ("response.completed", {"type": "response.completed", "response": response}),
    ]
    for number, (_name, data) in enumerate(events):
        data["sequence_number"] = number
    chunks = [f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events]
    return "".join(chunks).encode("utf-8")


def summarize_body(value: Any) -> Any:
    """What was sent, without images and keys: long strings become their length and hash."""
    if isinstance(value, dict):
        return {key: summarize_body(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [summarize_body(item) for item in value]
    if isinstance(value, bytes):
        return f"<bytes {len(value)}>"
    if isinstance(value, str):
        if FAKE_KEY in value:
            return value.replace(FAKE_KEY, "<KEY>")
        if len(value) > 400:
            return f"<text {len(value)} sha {hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}>"
        return value
    return value


@contextmanager
def network_stubs() -> Iterator[list[dict[str, Any]]]:
    """Canned providers for this process, a dead proxy for its children, nothing else reaches out."""
    import requests
    import httpx

    try:  # the OpenAI SDK talks through its own fork, httpx2
        import httpx2
    except ImportError:
        httpx2 = None

    sent: list[dict[str, Any]] = []
    saved_env = {key: os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")}
    os.environ.update({"HTTP_PROXY": DEAD_PROXY, "HTTPS_PROXY": DEAD_PROXY, "ALL_PROXY": DEAD_PROXY, "NO_PROXY": ""})

    original_request = requests.sessions.Session.request
    original_send = httpx.Client.send
    original_send2 = httpx2.Client.send if httpx2 is not None else None
    original_connect = socket.socket.connect

    def fake_request(self, method, url, **kwargs):  # noqa: ANN001
        body = kwargs.get("json")
        if body is None and kwargs.get("data"):
            body = kwargs.get("data")
        sent.append({"via": "requests", "method": method.upper(), "url": str(url), "body": summarize_body(body)})
        return FakeResponse(str(url), canned_reply(str(url), body if isinstance(body, dict) else None))

    def fake_send(self, request, **kwargs):  # noqa: ANN001
        url = str(request.url)
        try:
            body = json.loads(request.content.decode("utf-8")) if request.content else None
        except Exception:
            body = f"<bytes {len(request.content or b'')}>"
        sent.append({"via": "httpx", "method": request.method, "url": url.split("?")[0], "body": summarize_body(body)})
        payload = canned_reply(url, body if isinstance(body, dict) else None)
        response_class = httpx2.Response if httpx2 is not None and isinstance(request, httpx2.Request) else httpx.Response
        if isinstance(body, dict) and body.get("stream") and "api.openai.com" in url:
            return response_class(200, headers={"content-type": "text/event-stream"}, content=openai_events(payload), request=request)
        return response_class(200, json=payload, request=request)

    def guarded_connect(self, address):  # noqa: ANN001
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ConnectionRefusedError(f"reference run: outside connection refused ({host})")
        return original_connect(self, address)

    requests.sessions.Session.request = fake_request
    httpx.Client.send = fake_send
    if httpx2 is not None:
        httpx2.Client.send = fake_send
    socket.socket.connect = guarded_connect
    try:
        yield sent
    finally:
        requests.sessions.Session.request = original_request
        httpx.Client.send = original_send
        if httpx2 is not None:
            httpx2.Client.send = original_send2
        socket.socket.connect = original_connect
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------- digests


def normalize_text(text: str, stand: Path) -> str:
    text = text.replace("\r\n", "\n")
    # The stand lies in <BASE>\stand and the fixtures in <BASE>\fixtures.
    for folder, mark in ((stand, "<STAND>"), (stand.parent, "<BASE>")):
        for form in (str(folder).replace("\\", "\\\\"), str(folder), str(folder).replace("\\", "/")):
            text = text.replace(form, mark)
    text = ISO_TIME.sub("<TIME>", text)
    text = MEASURED.sub(lambda match: match.group(1) + "<N>", text)
    text = TRACEBACK_LINE.sub(lambda match: match.group(1) + "<N>", text)
    return _quiet_timed_columns(text)


TIMED_HEADER = re.compile(r"^(seconds|sec|elapsed|duration|time|время|секунд)", re.I)


def _quiet_timed_columns(text: str) -> str:
    """In Markdown tables, the cells under a header like "Seconds" are measured, not made: <N>."""
    out: list[str] = []
    timed: set[int] = set()
    for line in text.split("\n"):
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            timed = set()
            out.append(line)
            continue
        cells = stripped[1:-1].split("|")
        if not timed and not set(stripped) <= set("|-: "):
            found = {index for index, cell in enumerate(cells) if TIMED_HEADER.match(cell.strip())}
            if found:
                timed = found
                out.append(line)
                continue
        if timed and not set(stripped) <= set("|-: "):
            cells = [" <N> " if index in timed and cell.strip() else cell for index, cell in enumerate(cells)]
            line = "|" + "|".join(cells) + "|"
        out.append(line)
    return "\n".join(out)


def _cell(value: Any, stand: Path) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str):
        return normalize_text(value, stand)
    if hasattr(value, "isoformat"):
        return "<TIME>"
    return value


def _short(text: str) -> Any:
    if len(text) <= BIG_TEXT:
        return text
    return {"chars": len(text), "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "head": text[:300]}


def normalize_json(value: Any, stand: Path) -> Any:
    if isinstance(value, dict):
        return {key: ("<VOLATILE>" if VOLATILE_KEYS.search(str(key)) else normalize_json(item, stand)) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [normalize_json(item, stand) for item in value]
    if isinstance(value, str):
        return normalize_text(value, stand)
    if isinstance(value, float):
        return round(value, 4)
    return value


def digest_file(path: Path, stand: Path) -> Any:
    suffix = path.suffix.lower()
    name = path.name.lower()
    try:
        if suffix in {".md", ".txt", ".csv", ".tsv"}:
            return {"text": _short(normalize_text(path.read_text(encoding="utf-8", errors="replace"), stand))}
        if suffix == ".html":
            raw = normalize_text(path.read_text(encoding="utf-8", errors="replace"), stand)
            body = re.sub(r"<style.*?</style>", "", raw, flags=re.S)
            visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
            return {"visible_text": _short(visible), "markup": _short(raw)}
        if suffix == ".json":
            return {"json": _json_digest(normalize_json(json.loads(path.read_text(encoding="utf-8")), stand))}
        if suffix == ".docx":
            return _docx_digest(path, stand)
        if suffix == ".xlsx":
            return _xlsx_digest(path, stand)
        if suffix == ".pptx":
            return _pptx_digest(path, stand)
        if suffix == ".pdf":
            return _pdf_digest(path, stand)
        if suffix == ".odt":
            with zipfile.ZipFile(path) as archive:
                content = archive.read("content.xml").decode("utf-8")
            return {"odt_text": _short(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)).strip())}
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
            from PIL import Image

            with Image.open(path) as image:
                pixels = hashlib.sha256(image.tobytes()).hexdigest()[:16]
                return {"image": [image.width, image.height, image.mode], "pixels": pixels}
    except Exception as exc:  # a digest must never hide a file
        return {"unreadable": normalize_text(f"{exc.__class__.__name__}: {exc}", stand), "size": path.stat().st_size}
    return {"size": path.stat().st_size, "sha": hashlib.sha256(path.read_bytes()).hexdigest()[:16]}


def _json_digest(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= BIG_TEXT * 2:
        return value
    return {"chars": len(text), "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "keys": sorted(value) if isinstance(value, dict) else f"list[{len(value)}]"}


def _docx_digest(path: Path, stand: Path) -> Any:
    from docx import Document

    document = Document(str(path))
    paragraphs = [normalize_text(f"{p.style.name}|{p.text}", stand) for p in document.paragraphs if p.text.strip()]
    tables = [[[normalize_text(cell.text, stand) for cell in row.cells] for row in table.rows] for table in document.tables]
    section = document.sections[0]
    return {
        "paragraphs": _short("\n".join(paragraphs)),
        "tables": _json_digest(tables),
        "page": [round(section.page_width.mm, 1) if section.page_width else None, round(section.page_height.mm, 1) if section.page_height else None, str(section.orientation)],
        "images": sum(1 for rel in document.part.rels.values() if "image" in rel.reltype),
    }


def _xlsx_digest(path: Path, stand: Path) -> Any:
    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=False)
    sheets = {}
    for sheet in workbook.worksheets:
        rows = [[cell for cell in row] for row in sheet.iter_rows(values_only=True)]
        sheets[sheet.title] = _json_digest([[_cell(c, stand) for c in row] for row in rows])
    return {"sheets": sheets}


def _pptx_digest(path: Path, stand: Path) -> Any:
    from pptx import Presentation

    presentation = Presentation(str(path))
    slides = []
    for slide in presentation.slides:
        texts = [normalize_text(shape.text_frame.text, stand) for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()]
        slides.append(texts)
    return {"slides": _json_digest(slides)}


def _pdf_digest(path: Path, stand: Path) -> Any:
    import fitz

    with fitz.open(path) as document:
        pages = []
        for page in document:
            pages.append({"text": _short(normalize_text(page.get_text().strip(), stand)), "images": len(page.get_images()), "size": [round(page.rect.width), round(page.rect.height)]})
    return {"pages": pages}


def digest_tree(folder: Path, stand: Path) -> dict[str, Any]:
    if not folder.exists():
        return {}
    found: dict[str, Any] = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            found[normalize_text(path.relative_to(folder).as_posix(), stand)] = digest_file(path, stand)
    return found


# ---------------------------------------------------------------- parameters from the record


def window_defaults(path: str) -> dict[str, Any]:
    """The parameters the former window sent for this node with nothing touched."""
    record = json.loads(RECORD_PARAMS.read_text(encoding="utf-8"))
    for item in record["operations"]:
        if item["path"] == path:
            return dict(item["defaults"]["parameters"])
    raise KeyError(path)
