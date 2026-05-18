from autoslide.models import BlockType


def test_plain_text_block_type(parse):
    slides = parse("Hello world")
    assert slides[0][0].type == BlockType.TEXT


def test_plain_text_content_preserved(parse):
    slides = parse("Hello world")
    assert slides[0][0].content == "Hello world"


def test_multiline_text_preserved(parse):
    md = "Line one\nLine two\nLine three"
    slides = parse(md)
    block = slides[0][0]
    assert block.type == BlockType.TEXT
    assert "Line one" in block.content
    assert "Line three" in block.content


def test_text_with_italic_markers_is_still_text(parse):
    slides = parse("Some *italic* word")
    assert slides[0][0].type == BlockType.TEXT


def test_prose_with_mixed_content_is_text(parse):
    # Lines that have a non-dash first line followed by non-list lines → TEXT
    md = "My Heading\nSome prose line\nAnother prose line"
    slides = parse(md)
    assert slides[0][0].type == BlockType.TEXT
