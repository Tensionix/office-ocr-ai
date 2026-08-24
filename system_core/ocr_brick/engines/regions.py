# engines/regions.py
# Structured layout model. A layout provider (Surya / PP-Structure) turns a page
# into ordered, typed regions. This is what makes reliable DOCX/XLSX tables
# possible — far better than clustering a flat word list.
# No globals; plain dataclasses. EN comments only. UTF-8 without BOM.

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

Box = tuple[int, int, int, int]  # x, y, w, h in pixels of the recognized image


@dataclass
class Cell:
    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    box: Box | None = None


@dataclass
class TableRegion:
    rows: int
    cols: int
    cells: list[Cell] = field(default_factory=list)
    box: Box | None = None
    kind: str = "table"


@dataclass
class TextRegion:
    text: str
    box: Box | None = None
    kind: str = "paragraph"   # "paragraph" | "heading" | "caption"


@dataclass
class FigureRegion:
    box: Box | None = None
    kind: str = "figure"      # rendered as image / skipped in text outputs


@dataclass
class LayoutResult:
    page: int
    regions: list[object] = field(default_factory=list)  # ordered top-to-bottom
    width: int = 0
    height: int = 0
    engine: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {"page": self.page, "width": self.width, "height": self.height,
               "engine": self.engine, "metadata": self.metadata, "regions": []}
        for r in self.regions:
            d = asdict(r)
            d["region_type"] = getattr(r, "kind", type(r).__name__)
            out["regions"].append(d)
        return out


def tables(layout: LayoutResult) -> list[TableRegion]:
    return [r for r in layout.regions if isinstance(r, TableRegion)]


def text_blocks(layout: LayoutResult) -> list[TextRegion]:
    return [r for r in layout.regions if isinstance(r, TextRegion)]


def _box(v) -> Box | None:
    return tuple(int(x) for x in v) if v else None  # list (from JSON) -> tuple


def region_from_dict(d: dict) -> object:
    """Rebuild a region object from its to_dict() form (carries region_type)."""
    t = d.get("region_type") or d.get("kind")
    if t == "table":
        cells = [Cell(text=c.get("text", ""), row=int(c["row"]), col=int(c["col"]),
                      rowspan=int(c.get("rowspan", 1)), colspan=int(c.get("colspan", 1)),
                      box=_box(c.get("box"))) for c in d.get("cells", [])]
        return TableRegion(rows=int(d.get("rows", 0)), cols=int(d.get("cols", 0)),
                           cells=cells, box=_box(d.get("box")))
    if t == "figure":
        return FigureRegion(box=_box(d.get("box")))
    return TextRegion(text=d.get("text", ""), box=_box(d.get("box")),
                      kind=t or "paragraph")


def layout_from_dict(d: dict) -> LayoutResult:
    lr = LayoutResult(page=int(d.get("page", 0)), engine=d.get("engine", ""),
                      width=int(d.get("width", 0)), height=int(d.get("height", 0)),
                      metadata=dict(d.get("metadata") or {}))
    lr.regions = [region_from_dict(r) for r in d.get("regions", [])]
    return lr
