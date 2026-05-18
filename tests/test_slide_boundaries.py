from autoslide.models import BlockType


def test_single_section_is_one_slide(parse):
    slides = parse("## My Section")
    assert len(slides) == 1


def test_single_slide_title_is_one_slide(parse):
    slides = parse("### My Slide ###")
    assert len(slides) == 1


def test_two_sections_produce_two_slides(parse):
    slides = parse("## A\n## B")
    assert len(slides) == 2


def test_two_slide_titles_produce_two_slides(parse):
    slides = parse("### A ###\n### B ###")
    assert len(slides) == 2


def test_section_then_slide_title_produce_two_slides(parse):
    slides = parse("## Section\n### Slide ###")
    assert len(slides) == 2
    assert slides[0][0].type == BlockType.SECTION
    assert slides[1][0].type == BlockType.SLIDE_TITLE


def test_title_page_starts_new_slide(parse):
    slides = parse("##### Talk #####\n## Section")
    assert len(slides) == 2
    assert slides[0][0].type == BlockType.TITLE_PAGE
    assert slides[1][0].type == BlockType.SECTION


def test_content_belongs_to_correct_slide(parse):
    md = "### Slide One ###\n\nFirst text\n\n### Slide Two ###\n\nSecond text"
    slides = parse(md)
    assert len(slides) == 2
    assert slides[0][1].content == "First text"
    assert slides[1][1].content == "Second text"


def test_content_without_header_forms_implicit_slide(parse):
    slides = parse("Just some text")
    assert len(slides) == 1


def test_adjacent_titles_each_have_only_title_block(parse):
    slides = parse("### A ###\n### B ###")
    assert all(len(s) == 1 for s in slides)


def test_empty_slide_not_emitted(parse):
    # A title with no content, then another title — each forms its own slide
    slides = parse("### Empty ###\n### Also Empty ###")
    assert len(slides) == 2
    assert all(s[0].type == BlockType.SLIDE_TITLE for s in slides)


def test_multiple_content_blocks_on_same_slide(parse):
    md = "### Slide ###\n\nFirst block\n\nSecond block"
    slides = parse(md)
    assert len(slides) == 1
    types = [b.type for b in slides[0]]
    assert types.count(BlockType.TEXT) == 2
