import pytest
from autoslide.models import BlockType


# Normal slide title goes through the fallback path (no regex match for plain "### T ###")
def test_slide_title_block_type(parse):
    slides = parse("### My Slide ###")
    assert slides[0][0].type == BlockType.SLIDE_TITLE


def test_slide_title_content_extracted(parse):
    slides = parse("### My Slide ###")
    assert slides[0][0].content == "My Slide"


def test_slide_title_trailing_hashes_stripped(parse):
    slides = parse("### Title With Hashes ###")
    assert slides[0][0].content == "Title With Hashes"


def test_slide_title_without_trailing_hashes(parse):
    slides = parse("### Plain Title")
    block = slides[0][0]
    assert block.type == BlockType.SLIDE_TITLE
    assert block.content == "Plain Title"


# Special markers: "### ! Title ###" (hidden), "### ? Title ###" (summary)
# The regex r"### (!?)(\??) (.+?) #+" requires a space between the marker and the title.
@pytest.mark.parametrize("line,hide,summary,title", [
    ("### My Slide ###",       False, False, "My Slide"),
    ("### ! My Slide ###",     True,  False, "My Slide"),
    ("### ? My Slide ###",     False, True,  "My Slide"),
    ("### !? My Slide ###",    True,  True,  "My Slide"),
])
def test_slide_title_markers(parse, line, hide, summary, title):
    slides = parse(line)
    block = slides[0][0]
    assert block.type == BlockType.SLIDE_TITLE
    assert block.content == title
    assert block.metadata["hide_slide"] == hide
    assert block.metadata["section_summary"] == summary


def test_slide_title_normal_has_false_metadata(parse):
    block = parse("### Normal ###")[0][0]
    assert block.metadata["hide_slide"] is False
    assert block.metadata["section_summary"] is False
