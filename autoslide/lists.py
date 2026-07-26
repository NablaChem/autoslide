"""Markdown list parsing. Rendering lives in ``templates/blocks/list.tex.j2``."""

from dataclasses import dataclass, field
from typing import List

_SUB_ITEM_PREFIXES = ("  -", "\t-", "    -")


@dataclass
class ListItem:
    text: str
    children: List[str] = field(default_factory=list)


@dataclass
class ListModel:
    #: Bold coloured lead-in line (a first line without a dash), if any.
    heading: str = ""
    items: List[ListItem] = field(default_factory=list)

    @property
    def compact(self) -> bool:
        """A lone item without children renders as plain lines, not an itemize.

        This keeps consecutive one-liner lists in a single LaTeX paragraph so
        ``\\parskip`` doesn't open a gap between them.
        """
        return len(self.items) == 1 and not self.items[0].children

    @property
    def heading_only(self) -> bool:
        """``"Heading\\n-"`` - a bold lead-in with no bullet at all."""
        return self.compact and not self.items[0].text


def parse_list(content: str) -> ListModel:
    lines = content.split("\n")
    model = ListModel()

    index = 0
    first = lines[0].strip() if lines else ""
    if first and not first.startswith("-"):
        model.heading = first
        index = 1

    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("-"):
            index += 1
            continue

        item = ListItem(text=line[1:].strip())
        index += 1
        while index < len(lines):
            child = lines[index].strip()
            if not child:
                index += 1
                continue
            if not lines[index].startswith(_SUB_ITEM_PREFIXES):
                break
            item.children.append(child[1:].strip())
            index += 1
        model.items.append(item)

    return model
