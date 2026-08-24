from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_paths import BASE_DIR, INPUT_DIR


SKIP_DIRS = {
    ".git",
    "._runtime",
    "__pycache__",
    "input",
    "logs",
    "output",
    "release",
    "report",
    "runtime",
    "wheelhouse",
    "workspace",
}


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    vars: dict[str, str]


@dataclass(frozen=True)
class RenderLayout:
    margin_left_mm: float = 17.0
    margin_right_mm: float = 17.0
    margin_top_mm: float = 16.0
    margin_bottom_mm: float = 20.0
    page_margin_y_mm: float = 4.0
    line_height: float = 1.5


DEFAULT_LAYOUT = RenderLayout()


def validate_layout(layout: RenderLayout) -> RenderLayout:
    values = {
        "margin_left_mm": layout.margin_left_mm,
        "margin_right_mm": layout.margin_right_mm,
        "margin_top_mm": layout.margin_top_mm,
        "margin_bottom_mm": layout.margin_bottom_mm,
        "page_margin_y_mm": layout.page_margin_y_mm,
        "line_height": layout.line_height,
    }
    for name, value in values.items():
        if not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric.")
        if value < 0:
            raise ValueError(f"{name} must not be negative.")

    horizontal = layout.margin_left_mm + layout.margin_right_mm
    vertical = layout.margin_top_mm + layout.margin_bottom_mm + (layout.page_margin_y_mm * 2)
    if horizontal > 120:
        raise ValueError("Left and right margins are too large for A4.")
    if vertical > 120:
        raise ValueError("Top, bottom and page reserve are too large for A4.")
    if not 1 <= layout.line_height <= 2:
        raise ValueError("line_height must be between 1 and 2.")
    return layout


THEMES = {
    "dark": Theme(
        id="dark",
        label="Dark",
        vars={
            "page": "#0c1213",
            "panel": "#10191a",
            "panelSoft": "#142123",
            "text": "#dbe8e5",
            "muted": "#93aaa6",
            "heading": "#8fe4d6",
            "heading2": "#ffb35f",
            "heading3": "#90d86c",
            "line": "#2b4b4d",
            "lineStrong": "#45b8b1",
            "link": "#72d3ee",
            "accentOrange": "#ff9f43",
            "accentGreen": "#82cc59",
            "accentTeal": "#38c6bd",
            "inlineBg": "#1b2a2c",
            "inlineText": "#ffd2a1",
            "inlineBorder": "#38595b",
            "codeBg": "#0f1819",
            "codeText": "#e7f4f0",
            "codeBorder": "#315c5e",
            "quoteBg": "#152224",
            "tableStripe": "#142022",
            "shadow": "rgba(0, 0, 0, 0.28)",
            "footer": "#77827f",
        },
    ),
    "light-sand": Theme(
        id="light-sand",
        label="Light Sand",
        vars={
            "page": "#f5eddd",
            "panel": "#fff8ea",
            "panelSoft": "#f0e4cf",
            "text": "#22312f",
            "muted": "#66746f",
            "heading": "#075e63",
            "heading2": "#b65a18",
            "heading3": "#477d2c",
            "line": "#d8c9ad",
            "lineStrong": "#1f9b95",
            "link": "#007882",
            "accentOrange": "#e87922",
            "accentGreen": "#5f9f3f",
            "accentTeal": "#0e9a9a",
            "inlineBg": "#efe1c9",
            "inlineText": "#874412",
            "inlineBorder": "#d7bd92",
            "codeBg": "#f8eddc",
            "codeText": "#173331",
            "codeBorder": "#cdb386",
            "quoteBg": "#f1e5cf",
            "tableStripe": "#f3e7d1",
            "shadow": "rgba(96, 68, 30, 0.12)",
            "footer": "#6f746e",
        },
    ),
}


def project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def is_markdown(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".md", ".markdown"}


def iter_markdown(root: Path, recursive: bool) -> Iterable[Path]:
    if is_markdown(root):
        yield root
        return
    if not root.is_dir():
        return
    if not recursive:
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if is_markdown(child):
                yield child
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in SKIP_DIRS and not dirname.startswith(".")
        ]
        current = Path(dirpath)
        for filename in sorted(filenames, key=str.lower):
            path = current / filename
            if is_markdown(path):
                yield path


def default_sources() -> list[Path]:
    return [INPUT_DIR] if INPUT_DIR.exists() else []


def collect_sources(recursive: bool, roots: list[Path] | None = None) -> list[Path]:
    roots = roots if roots is not None else default_sources()
    docs: dict[str, Path] = {}
    for root in roots:
        for doc in iter_markdown(root, recursive=recursive):
            key = str(doc.resolve()).lower()
            docs[key] = doc.resolve()
    return sorted(docs.values(), key=lambda item: project_relative(item).lower())


def load_source_list(path: Path) -> list[Path]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Source list must be a JSON array: {path}")
    sources: list[Path] = []
    for item in data:
        source = Path(str(item)).expanduser()
        if not source.is_absolute():
            source = BASE_DIR / source
        if is_markdown(source):
            sources.append(source.resolve())
    return sources


def normalize_markdown_for_pdf(markdown: str) -> str:
    """Repair a small set of known OCR/generator glitches before rendering."""
    markdown = markdown.replace("- \x0degistry -", "- registry -")
    markdown = markdown.replace("- \x0ceature -", "- feature -")
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    markdown = markdown.replace("- \negistry -", "- registry -")
    markdown = markdown.replace("- \x0ceature -", "- feature -")

    lines = markdown.split("\n")
    repaired: list[str] = []
    in_repaired_fence = False
    for line in lines:
        if not in_repaired_fence and re.fullmatch(r"`[\t ]*ext", line):
            repaired.append("```text")
            in_repaired_fence = True
            continue
        if in_repaired_fence and line.strip() == "`":
            repaired.append("```")
            in_repaired_fence = False
            continue
        repaired.append(line)

    return "\n".join(repaired)


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return normalize_markdown_for_pdf(handle.read())


def markdown_to_html(markdown: str) -> str:
    try:
        from markdown_it import MarkdownIt
    except Exception as exc:
        raise RuntimeError(
            "markdown-it-py is not installed. Rebuild the portable runtime first."
        ) from exc

    md = MarkdownIt("commonmark", {"html": True})
    for rule in ("table", "strikethrough"):
        try:
            md.enable(rule)
        except Exception:
            pass
    return md.render(markdown)


def title_from_markdown(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip(" #`*_~") or fallback
    return fallback


def detect_lang(path: Path) -> str:
    name = path.name.upper()
    if "_RU" in name or name.endswith("_RU.MD"):
        return "RU"
    if "_EN" in name or name.endswith("_EN.MD"):
        return "EN"
    return "EN"


def mm(value: float) -> str:
    return f"{float(value):g}mm"


def theme_css(theme: Theme, layout: RenderLayout) -> str:
    vars_css = "\n".join(f"--{key}: {value};" for key, value in theme.vars.items())
    color_scheme = "dark" if theme.id == "dark" else "light"
    page_top_padding = layout.margin_top_mm + layout.page_margin_y_mm
    page_bottom_padding = layout.margin_bottom_mm + layout.page_margin_y_mm
    return f"""
    :root {{
      {vars_css}
      color-scheme: {color_scheme};
    }}
    * {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    html,
    body {{
      margin: 0;
      min-height: 100%;
      background: var(--page);
      color: var(--text);
    }}
    body {{
      font-family: "Segoe UI", "Inter", "Arial", sans-serif;
      font-size: 11pt;
      line-height: {layout.line_height:g};
    }}
    .page {{
      max-width: 920px;
      margin: 0 auto;
      padding: 42px 52px 58px;
      background:
        linear-gradient(90deg, var(--accentOrange), var(--accentGreen), var(--accentTeal)) top left / 100% 7px no-repeat,
        var(--panel);
      box-shadow: 0 18px 48px var(--shadow);
      min-height: 100vh;
    }}
    .doc-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding-bottom: 16px;
      margin-bottom: 26px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 8.7pt;
    }}
    .doc-meta strong {{
      color: var(--heading);
      font-size: 9.2pt;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 9px;
      background: var(--panelSoft);
      color: var(--muted);
    }}
    .source {{
      flex-basis: 100%;
      overflow-wrap: anywhere;
    }}
    h1,
    h2,
    h3,
    h4 {{
      line-height: 1.18;
      break-after: avoid;
      letter-spacing: 0;
    }}
    h1 {{
      margin: 0 0 22px;
      padding-bottom: 13px;
      border-bottom: 3px solid var(--accentOrange);
      color: var(--heading);
      font-size: 28pt;
      font-weight: 760;
    }}
    h2 {{
      margin: 30px 0 12px;
      padding-bottom: 7px;
      border-bottom: 1px solid var(--line);
      color: var(--heading2);
      font-size: 18pt;
    }}
    h3 {{
      margin: 24px 0 10px;
      color: var(--heading3);
      font-size: 14.5pt;
    }}
    h4 {{
      margin: 20px 0 8px;
      color: var(--heading);
      font-size: 12pt;
    }}
    p,
    ul,
    ol,
    blockquote,
    pre,
    table {{
      margin-top: 0;
      margin-bottom: 13px;
    }}
    ul,
    ol {{
      padding-left: 24px;
    }}
    li + li {{
      margin-top: 4px;
    }}
    p + ul,
    p + ol {{
      break-before: avoid;
    }}
    a {{
      color: var(--link);
      text-decoration: none;
      border-bottom: 1px solid var(--lineStrong);
    }}
    strong {{
      color: var(--heading);
    }}
    hr {{
      border: 0;
      height: 1px;
      margin: 24px 0;
      background: linear-gradient(90deg, var(--accentOrange), var(--accentGreen), var(--accentTeal));
    }}
    blockquote {{
      margin-left: 0;
      padding: 12px 16px;
      border-left: 4px solid var(--accentOrange);
      background: var(--quoteBg);
      break-inside: avoid;
    }}
    code,
    pre {{
      font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
    }}
    :not(pre) > code {{
      padding: 0.13em 0.36em;
      border: 1px solid var(--inlineBorder);
      border-radius: 5px;
      background: var(--inlineBg);
      color: var(--inlineText);
      font-size: 0.92em;
      white-space: break-spaces;
    }}
    pre {{
      padding: 14px 16px;
      border: 1px solid var(--codeBorder);
      border-left: 4px solid var(--accentTeal);
      border-radius: 8px;
      background: var(--codeBg);
      color: var(--codeText);
      font-size: 9.4pt;
      line-height: {layout.line_height:g};
      overflow-wrap: anywhere;
      white-space: pre-wrap;
      break-inside: avoid;
    }}
    pre code {{
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
      font-size: inherit;
      white-space: inherit;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 9.7pt;
      break-inside: auto;
    }}
    thead {{
      display: table-header-group;
    }}
    tfoot {{
      display: table-footer-group;
    }}
    tr {{
      break-inside: avoid;
      break-after: auto;
    }}
    th,
    td {{
      padding: 8px 9px;
      border: 1px solid var(--line);
      vertical-align: top;
      break-inside: avoid;
    }}
    th {{
      background: var(--panelSoft);
      color: var(--heading);
      text-align: left;
    }}
    tr:nth-child(even) td {{
      background: var(--tableStripe);
    }}
    img {{
      display: block;
      max-width: 100%;
      height: auto;
      margin: 14px auto;
      border-radius: 8px;
      border: 1px solid var(--line);
    }}
    input[type="checkbox"] {{
      transform: translateY(1px);
      accent-color: var(--accentTeal);
    }}
    @page {{
      size: A4;
      margin: 0;
    }}
    @media print {{
      body {{
        background: var(--panel);
      }}
      .page {{
        max-width: none;
        min-height: 100vh;
        box-shadow: none;
        -webkit-box-decoration-break: clone;
        box-decoration-break: clone;
        padding: {mm(page_top_padding)} {mm(layout.margin_right_mm)} {mm(page_bottom_padding)} {mm(layout.margin_left_mm)};
      }}
    }}
    """


def html_document(markdown: str, source: Path, theme: Theme, layout: RenderLayout) -> str:
    rendered = markdown_to_html(markdown)
    title = title_from_markdown(markdown, source.stem)
    lang = detect_lang(source)
    base_href = source.parent.resolve().as_uri() + "/"
    source_rel = project_relative(source)
    return f"""<!doctype html>
<html lang="{html.escape('ru' if lang == 'RU' else 'en')}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <base href="{html.escape(base_href)}">
  <title>{html.escape(title)} - {html.escape(theme.label)}</title>
  <style>{theme_css(theme, layout)}</style>
</head>
<body>
  <main class="page">
    <div class="doc-meta">
      <strong>AUDION</strong>
      <span class="pill">{html.escape(lang)}</span>
      <span class="pill">{html.escape(theme.label)}</span>
      <span class="source">{html.escape(source_rel)}</span>
    </div>
    <article>
      {rendered}
    </article>
  </main>
</body>
</html>"""


def output_relative_path(source: Path, base_root: Path | None = None) -> Path:
    resolved = source.resolve()
    roots = [base_root.resolve()] if base_root else []
    roots.extend([INPUT_DIR.resolve(), BASE_DIR.resolve()])
    for root in roots:
        try:
            return resolved.relative_to(root)
        except ValueError:
            continue
    return Path(source.name)


def containing_docs_dir(source: Path, base_root: Path | None = None) -> Path | None:
    base_resolved = base_root.resolve() if base_root else None
    for parent in [source.parent, *source.parents]:
        if parent.name.lower() == "docs":
            return parent
        if base_resolved and parent.resolve() == base_resolved:
            break
    return None


def output_path_for(source: Path, theme: Theme, mode: str, out_dir: Path, base_root: Path | None = None) -> Path:
    if mode == "beside":
        return source.with_name(f"{source.stem}.{theme.id}.pdf")
    if mode == "md-folder-pdf":
        return source.parent / "PDF" / f"{source.stem}.{theme.id}.pdf"
    if mode == "docs-pdf":
        docs_dir = containing_docs_dir(source, base_root)
        if docs_dir is None:
            docs_dir = source.parent
        try:
            rel = source.resolve().relative_to(docs_dir.resolve())
        except ValueError:
            rel = Path(source.name)
        return docs_dir / "PDF" / rel.parent / f"{source.stem}.{theme.id}.pdf"
    else:
        rel = output_relative_path(source, base_root)
    return out_dir / rel.parent / f"{source.stem}.{theme.id}.pdf"


def import_playwright():
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Python Playwright is not installed. Run builder_main.cmd and choose "
            "INSTALL PLAYWRIGHT CHROMIUM, or rebuild the portable runtime."
        ) from exc
    return sync_playwright, PlaywrightError


def render_pdfs(
    docs: list[Path],
    themes: list[Theme],
    output_mode: str,
    out_dir: Path,
    layout: RenderLayout,
    dry_run: bool,
    browser_exe: Path | None,
    base_root: Path | None = None,
) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    layout = validate_layout(layout)
    for source in docs:
        for theme in themes:
            output = output_path_for(source, theme, output_mode, out_dir, base_root)
            manifest.append(
                {
                    "source": project_relative(source),
                    "output": project_relative(output),
                    "theme": theme.id,
                }
            )

    if dry_run:
        for item in manifest:
            print(f"[PLAN] {item['theme']:<10} {item['source']} -> {item['output']}")
        return manifest

    sync_playwright, PlaywrightError = import_playwright()
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BASE_DIR / "runtime" / ".playwright"))

    launch_options: dict[str, object] = {"headless": True}
    if browser_exe:
        launch_options["executable_path"] = str(browser_exe.resolve())

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": 1280, "height": 1600})
            try:
                for source in docs:
                    markdown = read_text(source)
                    for theme in themes:
                        output = output_path_for(source, theme, output_mode, out_dir, base_root)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        page.set_content(html_document(markdown, source, theme, layout), wait_until="load")
                        page.pdf(
                            path=str(output),
                            format="A4",
                            print_background=True,
                            prefer_css_page_size=True,
                            display_header_footer=True,
                            header_template="<span></span>",
                            footer_template=(
                                "<div style=\"width:100%;font-family:Segoe UI,Arial,sans-serif;"
                                f"font-size:7pt;color:{theme.vars['footer']};"
                                f"padding:0 {mm(layout.margin_right_mm)} 4mm {mm(layout.margin_left_mm)};text-align:right;\">"
                                "<span class=\"pageNumber\"></span>/<span class=\"totalPages\"></span>"
                                "</div>"
                            ),
                            margin={
                                "top": "0",
                                "right": "0",
                                "bottom": "0",
                                "left": "0",
                            },
                        )
                        print(f"[PDF] {theme.id:<10} {project_relative(output)}")
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RuntimeError(
            "Chromium is not available for Playwright. Run builder_main.cmd and choose "
            "INSTALL PLAYWRIGHT CHROMIUM. Details: " + str(exc)
        ) from exc

    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render Markdown files from input/ to dark/light PDF through Chromium.",
    )
    parser.add_argument(
        "--theme",
        choices=["both", "dark", "light-sand"],
        default="both",
        help="Theme to render. Default: both.",
    )
    parser.add_argument(
        "--output-mode",
        choices=["beside", "md-folder-pdf", "docs-pdf", "mirror-output"],
        default="docs-pdf",
        help="Write PDFs beside Markdown, into a sibling PDF folder, under docs/PDF, or mirrored. Default: docs/PDF.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(BASE_DIR / "output" / "dev_pdf"),
        help="Output folder for docs-pdf/mirror-output modes.",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Markdown file or folder to render. Can be repeated. Default: input/.",
    )
    parser.add_argument(
        "--source-list",
        default="",
        help="UTF-8 JSON array of Markdown file paths to render.",
    )
    parser.add_argument(
        "--base-root",
        default="",
        help="Base root for mirror-output relative paths.",
    )
    parser.add_argument(
        "--margin-left-mm",
        type=float,
        default=DEFAULT_LAYOUT.margin_left_mm,
        help=f"PDF content left margin in millimeters. Default: {DEFAULT_LAYOUT.margin_left_mm:g}.",
    )
    parser.add_argument(
        "--margin-right-mm",
        type=float,
        default=DEFAULT_LAYOUT.margin_right_mm,
        help=f"PDF content right margin in millimeters. Default: {DEFAULT_LAYOUT.margin_right_mm:g}.",
    )
    parser.add_argument(
        "--margin-top-mm",
        type=float,
        default=DEFAULT_LAYOUT.margin_top_mm,
        help=f"PDF content top margin in millimeters. Default: {DEFAULT_LAYOUT.margin_top_mm:g}.",
    )
    parser.add_argument(
        "--margin-bottom-mm",
        type=float,
        default=DEFAULT_LAYOUT.margin_bottom_mm,
        help=f"PDF content bottom margin in millimeters. Default: {DEFAULT_LAYOUT.margin_bottom_mm:g}.",
    )
    parser.add_argument(
        "--page-margin-y-mm",
        type=float,
        default=DEFAULT_LAYOUT.page_margin_y_mm,
        help=(
            "Extra page breathing room added above and below content in millimeters. "
            f"Default: {DEFAULT_LAYOUT.page_margin_y_mm:g}."
        ),
    )
    parser.add_argument(
        "--line-height",
        type=float,
        default=DEFAULT_LAYOUT.line_height,
        help=f"CSS line-height for body and code blocks. Default: {DEFAULT_LAYOUT.line_height:g}.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not scan folders recursively.",
    )
    parser.add_argument(
        "--browser-exe",
        default="",
        help="Optional explicit Chromium/Chrome/Edge executable for smoke tests.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned conversions without rendering.",
    )
    return parser.parse_args(argv)


def selected_themes(theme_arg: str) -> list[Theme]:
    if theme_arg == "both":
        return [THEMES["dark"], THEMES["light-sand"]]
    return [THEMES[theme_arg]]


def write_manifest(manifest: list[dict[str, str]]) -> Path:
    report_dir = BASE_DIR / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = report_dir / "dev_markdown_pdf_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        source_roots = [
            (Path(source).expanduser() if Path(source).expanduser().is_absolute() else BASE_DIR / source).resolve()
            for source in args.source
        ]
        docs = load_source_list(Path(args.source_list)) if args.source_list else collect_sources(
            recursive=not args.no_recursive,
            roots=source_roots or None,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Failed to resolve Markdown sources: {exc}")
        return 2
    if not docs:
        print("[INFO] No Markdown files found.")
        return 0

    browser_exe = Path(args.browser_exe) if args.browser_exe else None
    if browser_exe and not browser_exe.exists():
        print(f"[ERROR] Browser executable not found: {browser_exe}")
        return 2

    print("======================================================================")
    print("AUDION DEV MARKDOWN PDF ENGINE")
    print("======================================================================")
    print(f"Root       : {BASE_DIR}")
    print(f"Documents  : {len(docs)}")
    print(f"Themes     : {args.theme}")
    print(f"Output mode: {args.output_mode}")
    print(
        "Layout     : "
        f"L/R/T/B={args.margin_left_mm:g}/{args.margin_right_mm:g}/"
        f"{args.margin_top_mm:g}/{args.margin_bottom_mm:g} mm, "
        f"page Y={args.page_margin_y_mm:g} mm, "
        f"line-height={args.line_height:g}"
    )
    print()

    try:
        layout = RenderLayout(
            margin_left_mm=args.margin_left_mm,
            margin_right_mm=args.margin_right_mm,
            margin_top_mm=args.margin_top_mm,
            margin_bottom_mm=args.margin_bottom_mm,
            page_margin_y_mm=args.page_margin_y_mm,
            line_height=args.line_height,
        )
        manifest = render_pdfs(
            docs=docs,
            themes=selected_themes(args.theme),
            output_mode=args.output_mode,
            out_dir=Path(args.out_dir),
            layout=layout,
            dry_run=args.dry_run,
            browser_exe=browser_exe,
            base_root=Path(args.base_root) if args.base_root else None,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return 1

    manifest_path = write_manifest(manifest)
    print()
    print(f"[OK] Planned/generated PDFs: {len(manifest)}")
    print(f"[OK] Manifest: {project_relative(manifest_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
