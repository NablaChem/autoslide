"""Layout model: decides *what goes where*, without emitting any LaTeX.

The generators used to interleave these decisions with string building - a
state machine whose branches differed only in the order they appended
``\\begin{column}``. Here the decisions produce a plain tree that templates
render, which makes both halves testable on their own.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

from .models import Block, BlockType

#: Blocks consumed by the frame itself rather than by the content flow.
FRAME_LEVEL_TYPES = {
    BlockType.SLIDE_TITLE,
    BlockType.TITLE_PAGE,
    BlockType.FOOTLINE,
    BlockType.FOOTNOTE,
    BlockType.SECTION,
}

#: Blocks that only mark structure and never render anything themselves.
STRUCTURAL_TYPES = {
    BlockType.COLUMN_BREAK,
    BlockType.COLUMN_SECTION_BREAK,
    BlockType.POSTER_COLUMN_BREAK,
    BlockType.POSTER_COLUMN_CLOSE,
}


@dataclass
class LayoutItem:
    """One renderable block plus the context a renderer needs to space it."""

    block: Block
    #: True when the next renderable block in this column is another list -
    #: consecutive single-item lists need a wider break between them.
    followed_by_list: bool = False


@dataclass
class Column:
    items: List[LayoutItem] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.items)


@dataclass
class Section:
    """A horizontal band of the slide: either one full-width or two columns."""

    columns: List[Column] = field(default_factory=list)

    @property
    def has_columns(self) -> bool:
        return len(self.columns) > 1


@dataclass
class SlideLayout:
    sections: List[Section] = field(default_factory=list)

    def __bool__(self) -> bool:
        return any(any(c for c in s.columns) for s in self.sections)


def build_slide_layout(blocks: List[Block]) -> SlideLayout:
    """Split slide blocks into sections (``---``) and columns (``-|-``)."""
    sections = []
    for section_blocks in _split_on(blocks, BlockType.COLUMN_SECTION_BREAK):
        content = [b for b in section_blocks if b.type not in FRAME_LEVEL_TYPES]
        if not any(b.type not in STRUCTURAL_TYPES for b in content):
            continue
        columns = [
            _build_column(column_blocks)
            for column_blocks in _split_on(content, BlockType.COLUMN_BREAK)
        ]
        sections.append(Section(columns=columns))
    return SlideLayout(sections=sections)


def _split_on(blocks: List[Block], separator: BlockType) -> List[List[Block]]:
    groups: List[List[Block]] = [[]]
    for block in blocks:
        if block.type == separator:
            groups.append([])
        else:
            groups[-1].append(block)
    return groups


def _build_column(blocks: List[Block]) -> Column:
    renderable = [b for b in blocks if b.type not in STRUCTURAL_TYPES]
    items = [LayoutItem(block=b) for b in renderable]
    for index, item in enumerate(items[:-1]):
        item.followed_by_list = renderable[index + 1].type == BlockType.LIST
    return Column(items=items)


# ----------------------------------------------------------------------
# Poster layout
# ----------------------------------------------------------------------


@dataclass
class PosterBox:
    """One ``###`` box on the poster."""

    title: str
    layout: SlideLayout
    footnotes: List[Block] = field(default_factory=list)


@dataclass
class ColumnGroup:
    """A two-column band of the poster; either side may be empty."""

    left: List[PosterBox] = field(default_factory=list)
    right: List[PosterBox] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.left or self.right)


def build_poster_layout(
    slides: List[List[Block]],
) -> Tuple[List[ColumnGroup], List[str]]:
    """Group poster boxes into two-column bands.

    ``=|=`` switches to the right column, ``===`` closes the band. Returns the
    bands plus any warnings about ignored content.
    """
    groups: List[ColumnGroup] = []
    warnings: List[str] = []
    current: ColumnGroup = None
    side = "left"

    for slide in slides:
        types = {b.type for b in slide}

        if BlockType.TITLE_PAGE in types:
            continue

        if BlockType.POSTER_COLUMN_BREAK in types:
            if current is None:
                current = ColumnGroup()
            elif side == "right":
                groups.append(current)
                current = ColumnGroup()
            side = "right"
            continue

        if BlockType.POSTER_COLUMN_CLOSE in types:
            if current is not None:
                groups.append(current)
            current = None
            side = "left"
            continue

        if BlockType.SECTION in types:
            warnings.append("## Section is ignored in poster mode.")
            continue

        box = _build_poster_box(slide)
        if box is None:
            continue
        if current is None:
            current = ColumnGroup()
            side = "left"
        getattr(current, side).append(box)

    if current is not None:
        groups.append(current)

    return [g for g in groups if g], warnings


def _build_poster_box(blocks: List[Block]) -> PosterBox:
    title = ""
    footnotes = []
    for block in blocks:
        if block.type == BlockType.SLIDE_TITLE:
            if block.metadata.get("hide_slide", False):
                return None
            title = block.content
        elif block.type == BlockType.FOOTNOTE:
            footnotes.append(block)
    return PosterBox(
        title=title, layout=build_slide_layout(blocks), footnotes=footnotes
    )
