from autoslide.models import BlockType


def test_title_page_block_type(parse):
    slides = parse("##### My Presentation #####")
    assert slides[0][0].type == BlockType.TITLE_PAGE


def test_title_page_content_extracted(parse):
    slides = parse("##### My Presentation #####")
    assert slides[0][0].content == "My Presentation"


def test_title_page_trailing_hashes_stripped(parse):
    slides = parse("##### Multi Word Title #####")
    assert slides[0][0].content == "Multi Word Title"


def test_title_page_without_trailing_hashes(parse):
    slides = parse("##### Title Without Trailing")
    assert slides[0][0].content == "Title Without Trailing"


def test_title_page_is_single_block(parse):
    slides = parse("##### My Talk #####")
    assert len(slides[0]) == 1
