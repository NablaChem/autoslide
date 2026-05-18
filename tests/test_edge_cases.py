from autoslide.models import BlockType


def test_empty_string_produces_no_slides(parse):
    assert len(parse("")) == 0


def test_only_whitespace_produces_no_slides(parse):
    assert len(parse("   \n  \n   ")) == 0


def test_only_comments_produces_no_slides(parse):
    assert len(parse("// one\n// two\n// three")) == 0


def test_slide_with_no_content_has_only_title_block(parse):
    slides = parse("### Empty Slide ###")
    assert len(slides) == 1
    assert len(slides[0]) == 1
    assert slides[0][0].type == BlockType.SLIDE_TITLE


def test_multiple_blank_lines_treated_as_block_separator(parse):
    md = "### Slide ###\n\n\n\nSome text"
    slides = parse(md)
    types = [b.type for b in slides[0]]
    assert BlockType.TEXT in types


def test_single_blank_line_between_blocks(parse):
    md = "### Slide ###\n\nFirst\n\nSecond"
    slides = parse(md)
    text_blocks = [b for b in slides[0] if b.type == BlockType.TEXT]
    assert len(text_blocks) == 2


def test_content_before_any_header_forms_slide(parse):
    slides = parse("Orphan text\n\n### Later Slide ###")
    assert len(slides) == 2
    assert slides[0][0].type == BlockType.TEXT


def test_slide_title_with_many_trailing_hashes(parse):
    slides = parse("### Title #########")
    assert slides[0][0].content == "Title"
