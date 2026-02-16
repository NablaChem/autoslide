from typing import Dict
from dataclasses import dataclass
from enum import Enum


class BlockType(Enum):
    SECTION = "section"
    SLIDE_TITLE = "slide_title"
    TITLE_PAGE = "title_page"
    ANNOTATED_EQUATION = "annotated_equation"
    TABLE = "table"
    LIST = "list"
    IMAGE = "image"
    FOOTNOTE = "footnote"
    FOOTLINE = "footline"
    TEXT = "text"
    COLUMN_BREAK = "column_break"
    COLUMN_SECTION_BREAK = "column_section_break"
    PLOT = "plot"
    SCHEMATIC = "schematic"
    CODE = "code"


@dataclass
class Block:
    type: BlockType
    content: str
    metadata: Dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}