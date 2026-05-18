import pytest
from autoslide.models import BlockType


@pytest.mark.parametrize("line,number,text", [
    ("[1] First footnote",     "1",  "First footnote"),
    ("[2] Second footnote",    "2",  "Second footnote"),
    ("[12] Long list item",    "12", "Long list item"),
    ("[*] Starred footnote",   "*",  "Starred footnote"),
])
def test_footnote_type_number_content(parse, line, number, text):
    block = parse(line)[0][0]
    assert block.type == BlockType.FOOTNOTE
    assert block.metadata["number"] == number
    assert block.content == text


def test_footnote_numbered_type(parse):
    block = parse("[1] Some note")[0][0]
    assert block.type == BlockType.FOOTNOTE


def test_footnote_starred_type(parse):
    block = parse("[*] Some note")[0][0]
    assert block.type == BlockType.FOOTNOTE


def test_multiple_footnotes_on_same_slide(parse):
    md = "### Slide ###\n\n[1] First\n[2] Second"
    slides = parse(md)
    footnote_blocks = [b for b in slides[0] if b.type == BlockType.FOOTNOTE]
    assert len(footnote_blocks) == 2
    numbers = {b.metadata["number"] for b in footnote_blocks}
    assert numbers == {"1", "2"}
