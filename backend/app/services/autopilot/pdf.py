"""Render an agent-written digital product (guide, planner, checklist) to PDF.

Files are written under backend/data/products/ on this machine (git-ignored)
for the owner to download and attach in Shopify.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF
from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "products"


class Section(BaseModel):
    heading: str = Field(min_length=1, max_length=120)
    paragraphs: list[str] = Field(default_factory=list, max_length=12)
    bullets: list[str] = Field(default_factory=list, max_length=30)
    checklist: bool = False  # render bullets as tick boxes (planners/checklists)


class ProductContent(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    subtitle: str | None = Field(None, max_length=200)
    sections: list[Section] = Field(min_length=2, max_length=14)


def _latin(text: str) -> str:
    """Core PDF fonts are Latin-1; map common typography and drop the rest."""
    table = {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "…": "...",
        "•": "-",
        " ": " ",
        "✓": "v",
        "→": "->",
    }
    for k, v in table.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "ignore").decode("latin-1")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "product"


def render(content: ProductContent, directory: Path | None = None) -> Path:
    directory = directory or DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.multi_cell(0, 11, _latin(content.title), new_x="LMARGIN", new_y="NEXT")
    if content.subtitle:
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 13)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(0, 7, _latin(content.subtitle), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    pdf.ln(6)
    for sec in content.sections:
        pdf.set_font("Helvetica", "B", 15)
        pdf.multi_cell(0, 8, _latin(sec.heading), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 11)
        for para in sec.paragraphs:
            pdf.multi_cell(0, 6, _latin(para), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        for b in sec.bullets:
            mark = "[  ]  " if sec.checklist else "-  "
            pdf.multi_cell(0, 6, _latin(mark + b), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
    path = directory / f"{slug(content.title)}-{datetime.now(UTC):%Y%m%d%H%M%S}.pdf"
    pdf.output(str(path))
    return path
