from autoslide.models import BlockType


def test_column_break_type(parse):
    slides = parse("-|-")
    assert slides[0][0].type == BlockType.COLUMN_BREAK


def test_column_break_empty_content(parse):
    slides = parse("-|-")
    assert slides[0][0].content == ""


def test_column_section_break_type(parse):
    slides = parse("---")
    assert slides[0][0].type == BlockType.COLUMN_SECTION_BREAK


def test_column_section_break_empty_content(parse):
    slides = parse("---")
    assert slides[0][0].content == ""


def test_column_break_within_slide(parse):
    md = "### Slide ###\n\n-|-"
    slides = parse(md)
    types = [b.type for b in slides[0]]
    assert BlockType.COLUMN_BREAK in types


def test_column_section_break_within_slide(parse):
    md = "### Slide ###\n\n---"
    slides = parse(md)
    types = [b.type for b in slides[0]]
    assert BlockType.COLUMN_SECTION_BREAK in types


def test_column_break_between_content(parse):
    md = "Left text\n\n-|-\n\nRight text"
    slides = parse(md)
    types = [b.type for b in slides[0]]
    assert types == [BlockType.TEXT, BlockType.COLUMN_BREAK, BlockType.TEXT]
