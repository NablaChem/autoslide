"""Layout decisions are now plain data, so they can be asserted directly."""

from autoslide.layout import build_poster_layout, build_slide_layout
from autoslide.models import Block, BlockType


def _blocks(*types_and_content):
    return [Block(t, c) for t, c in types_and_content]


def test_single_section_single_column(parse):
    layout = build_slide_layout(parse("### Slide ###\nHello")[0])
    assert len(layout.sections) == 1
    assert len(layout.sections[0].columns) == 1
    assert not layout.sections[0].has_columns


def test_column_break_splits_into_two_columns(parse):
    layout = build_slide_layout(parse("### Slide ###\nleft\n-|-\nright")[0])
    section = layout.sections[0]
    assert section.has_columns
    assert len(section.columns) == 2
    assert section.columns[0].items[0].block.content.strip() == "left"
    assert section.columns[1].items[0].block.content.strip() == "right"


def test_section_break_starts_a_new_band(parse):
    layout = build_slide_layout(parse("### Slide ###\ntop\n---\nbottom")[0])
    assert len(layout.sections) == 2
    assert all(not s.has_columns for s in layout.sections)


def test_frame_level_blocks_are_not_content(parse):
    layout = build_slide_layout(parse("### Slide ###\nHello\n[^1]: note")[0])
    types = [
        item.block.type
        for section in layout.sections
        for column in section.columns
        for item in column.items
    ]
    assert BlockType.SLIDE_TITLE not in types
    assert BlockType.FOOTNOTE not in types


def test_title_only_slide_has_no_sections(parse):
    assert not build_slide_layout(parse("### Slide ###")[0]).sections


def test_list_followed_by_list_is_flagged(parse):
    layout = build_slide_layout(parse("### Slide ###\n- one\n\n- two")[0])
    items = layout.sections[0].columns[0].items
    assert [i.followed_by_list for i in items] == [True, False]


def test_list_followed_by_text_is_not_flagged(parse):
    layout = build_slide_layout(parse("### Slide ###\n- one\n\nsome text")[0])
    assert layout.sections[0].columns[0].items[0].followed_by_list is False


# -- poster ---------------------------------------------------------------


def _poster(text, parse):
    return build_poster_layout(parse(text))


def test_poster_boxes_default_to_the_left_column(parse):
    groups, warnings = _poster("### One ###\na\n\n### Two ###\nb", parse)
    assert len(groups) == 1
    assert len(groups[0].left) == 2
    assert groups[0].right == []
    assert warnings == []


def test_poster_column_break_moves_to_the_right(parse):
    groups, _ = _poster("### One ###\na\n\n=|=\n\n### Two ###\nb", parse)
    assert len(groups) == 1
    assert [b.title for b in groups[0].left] == ["One"]
    assert [b.title for b in groups[0].right] == ["Two"]


def test_poster_close_starts_a_new_band(parse):
    groups, _ = _poster("### One ###\na\n\n===\n\n### Two ###\nb", parse)
    assert len(groups) == 2
    assert [b.title for b in groups[0].left] == ["One"]
    assert [b.title for b in groups[1].left] == ["Two"]


def test_poster_second_break_in_a_band_opens_a_new_band(parse):
    groups, _ = _poster(
        "### A ###\na\n\n=|=\n\n### B ###\nb\n\n=|=\n\n### C ###\nc", parse
    )
    assert len(groups) == 2
    assert [b.title for b in groups[1].left] == []
    assert [b.title for b in groups[1].right] == ["C"]


def test_poster_warns_about_section_slides(parse):
    groups, warnings = _poster("## Ignored\n\n### Box ###\na", parse)
    assert len(warnings) == 1
    assert "Section" in warnings[0]
    assert [b.title for b in groups[0].left] == ["Box"]
