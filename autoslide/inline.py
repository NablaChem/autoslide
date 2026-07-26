"""Inline markdown -> LaTeX conversion, shared by every block renderer.

Before this existed the same two regexes were copy-pasted into tables, lists,
text, footnotes and equation headings - each with a different order and a
different subset applied.
"""

import re

_FOOTNOTE_REF = re.compile(r"\[\^([0-9,]+)\]")
_ITALIC = re.compile(r"\*([^*]+)\*")


def format_inline(text: str, footnotes: bool = True) -> str:
    """Convert inline markdown (``*italic*``, ``[^1]``) to LaTeX."""
    if footnotes:
        text = _FOOTNOTE_REF.sub(r"\\footnotemark[\1]", text)
    return _ITALIC.sub(r"\\textit{\1}", text)
