from autoslide.models import BlockType


def test_comment_only_input_produces_no_slides(parse):
    assert len(parse("// This is a comment")) == 0


def test_multiple_comments_produce_no_slides(parse):
    assert len(parse("// first\n// second\n// third")) == 0


def test_comment_in_slide_not_emitted_as_block(parse):
    md = "### Slide ###\n// ignored\nsome text"
    slides = parse(md)
    # Comment line must not appear as any block's content
    assert not any("// ignored" in b.content for b in slides[0])


def test_comment_between_blocks_not_emitted(parse):
    md = "### Slide ###\n\nFirst text\n\n// comment\n\nSecond text"
    slides = parse(md)
    text_blocks = [b for b in slides[0] if b.type == BlockType.TEXT]
    assert len(text_blocks) == 2
    assert not any("// comment" in b.content for b in text_blocks)


def test_comment_before_slide_title(parse):
    md = "// preamble comment\n### My Slide ###"
    slides = parse(md)
    assert len(slides) == 1
    assert slides[0][0].type == BlockType.SLIDE_TITLE
