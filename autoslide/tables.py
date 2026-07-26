"""Markdown table parsing. Rendering lives in ``templates/blocks/table.tex.j2``."""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .theme import Theme, default_theme

_SEPARATOR_ROW = re.compile(r"^\s*\|?[\s\-\|:]+\|?\s*$")


@dataclass
class TableRow:
    cells: List[str]
    shaded: bool = False


@dataclass
class TableModel:
    header: List[str] = field(default_factory=list)
    rows: List[TableRow] = field(default_factory=list)
    columns: int = 0


def parse_table(content: str, theme: Optional[Theme] = None) -> Optional[TableModel]:
    """Parse a markdown table. Returns None when the content isn't a table.

    Row shading follows a fixed cycle (by default: two plain rows, two shaded)
    which is decided here so the template only has to apply a colour.
    """
    theme = theme or default_theme()
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    if len(lines) < 2:
        return None

    parsed_rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in lines
        if "|" in line and not _SEPARATOR_ROW.match(line)
    ]
    if not parsed_rows:
        return None

    columns = max(len(row) for row in parsed_rows)

    def pad(row: List[str]) -> List[str]:
        return row + [""] * (columns - len(row))

    header, *data = parsed_rows
    cycle = theme.layout.table_shade_cycle
    rows = [
        TableRow(cells=pad(row), shaded=(index % cycle) >= theme.layout.table_shade_from)
        for index, row in enumerate(data)
    ]
    return TableModel(header=pad(header), rows=rows, columns=columns)
