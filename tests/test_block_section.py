from autoslide.models import BlockType


def test_section_block_type(parse):
    slides = parse("## My Section")
    assert slides[0][0].type == BlockType.SECTION


def test_section_content_extracted(parse):
    slides = parse("## My Section")
    assert slides[0][0].content == "My Section"


def test_section_extra_whitespace_stripped(parse):
    slides = parse("##   Spaced Section  ")
    assert slides[0][0].content == "Spaced Section"


def test_section_single_word(parse):
    slides = parse("## Intro")
    assert slides[0][0].content == "Intro"


def test_section_is_single_block(parse):
    slides = parse("## My Section")
    assert len(slides[0]) == 1
