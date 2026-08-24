from __future__ import annotations

from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from typing import Any

from docx.enum.section import WD_ORIENT
from docx.shared import Mm


@dataclass(frozen=True)
class DocxLayoutOptions:
    orientation: str = "portrait"
    margin_top_mm: float = 20.0
    margin_right_mm: float = 10.0
    margin_bottom_mm: float = 20.0
    margin_left_mm: float = 20.0
    font_name: str = "Arial"
    font_size_pt: float = 10.5


def normalize_orientation(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"landscape", "album", "album_oriented", "альбомная"}:
        return "landscape"
    return "portrait"


def clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(str(value).strip().replace(",", "."))
    except Exception:
        result = default
    return max(minimum, min(maximum, result))


def clean_font_name(value: Any, default: str = "Arial") -> str:
    text = str(value or "").strip().replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    return text or default


def build_docx_layout_options(
    *,
    orientation: Any = "portrait",
    margin_top_mm: Any = 20.0,
    margin_right_mm: Any = 10.0,
    margin_bottom_mm: Any = 20.0,
    margin_left_mm: Any = 20.0,
    font_name: Any = "Arial",
    font_size_pt: Any = 10.5,
) -> DocxLayoutOptions:
    return DocxLayoutOptions(
        orientation=normalize_orientation(orientation),
        margin_top_mm=clamp_float(margin_top_mm, 20.0, 0.0, 100.0),
        margin_right_mm=clamp_float(margin_right_mm, 10.0, 0.0, 100.0),
        margin_bottom_mm=clamp_float(margin_bottom_mm, 20.0, 0.0, 100.0),
        margin_left_mm=clamp_float(margin_left_mm, 20.0, 0.0, 100.0),
        font_name=clean_font_name(font_name),
        font_size_pt=clamp_float(font_size_pt, 10.5, 6.0, 72.0),
    )


def add_docx_layout_arguments(
    parser: ArgumentParser,
    *,
    default_font_name: str = "Arial",
    default_font_size_pt: float = 10.5,
    default_right_margin_mm: float = 10.0,
) -> None:
    parser.add_argument("--orientation", choices=["portrait", "landscape"], default="portrait")
    parser.add_argument("--margin-top-mm", default="20")
    parser.add_argument("--margin-right-mm", default=str(default_right_margin_mm))
    parser.add_argument("--margin-bottom-mm", default="20")
    parser.add_argument("--margin-left-mm", default="20")
    parser.add_argument("--font-name", default=default_font_name)
    parser.add_argument("--font-size-pt", default=str(default_font_size_pt))


def options_from_args(args: Namespace, *, default_font_size_pt: float = 10.5) -> DocxLayoutOptions:
    return build_docx_layout_options(
        orientation=getattr(args, "orientation", "portrait"),
        margin_top_mm=getattr(args, "margin_top_mm", 20),
        margin_right_mm=getattr(args, "margin_right_mm", 10),
        margin_bottom_mm=getattr(args, "margin_bottom_mm", 20),
        margin_left_mm=getattr(args, "margin_left_mm", 20),
        font_name=getattr(args, "font_name", "Arial"),
        font_size_pt=getattr(args, "font_size_pt", default_font_size_pt),
    )


def apply_section_layout(section, options: DocxLayoutOptions) -> None:
    if options.orientation == "landscape":
        section.orientation = WD_ORIENT.LANDSCAPE
        if section.page_width < section.page_height:
            section.page_width, section.page_height = section.page_height, section.page_width
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        if section.page_width > section.page_height:
            section.page_width, section.page_height = section.page_height, section.page_width

    section.top_margin = Mm(options.margin_top_mm)
    section.right_margin = Mm(options.margin_right_mm)
    section.bottom_margin = Mm(options.margin_bottom_mm)
    section.left_margin = Mm(options.margin_left_mm)


def describe_options(options: DocxLayoutOptions) -> str:
    return (
        f"orientation={options.orientation}, "
        f"margins_mm={options.margin_top_mm:g}/{options.margin_right_mm:g}/"
        f"{options.margin_bottom_mm:g}/{options.margin_left_mm:g}, "
        f"font={options.font_name}, size_pt={options.font_size_pt:g}"
    )
