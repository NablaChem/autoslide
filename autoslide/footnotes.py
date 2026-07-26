"""Footnote ordering. Rendering lives in ``templates/blocks/footnotes.tex.j2``.

Autoslide fakes footnotes: they are collected per slide and typeset in one
parbox at the bottom rather than by LaTeX's footnote machinery.
"""

from dataclasses import dataclass, field
from typing import List

from .models import Block

#: Footnotes marked ``[^*]`` carry no visible marker and come first.
STARRED = "*"


@dataclass
class FootnoteList:
    starred: List[str] = field(default_factory=list)
    numbered: List[tuple] = field(default_factory=list)  # (marker, text)

    def __bool__(self) -> bool:
        return bool(self.starred or self.numbered)


def collect_footnotes(blocks: List[Block]) -> FootnoteList:
    """Split footnote blocks into unmarked and numbered, numbers ascending."""
    result = FootnoteList()
    numbered = []
    for block in blocks:
        marker = block.metadata.get("number", "")
        if marker == STARRED:
            result.starred.append(block.content)
        else:
            numbered.append((marker, block.content))
    numbered.sort(key=lambda entry: int(entry[0] or 0))
    result.numbered = numbered
    return result
