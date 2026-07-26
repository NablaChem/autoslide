"""Block parsing is separate from rendering, so the models can be asserted."""

from autoslide.inline import format_inline
from autoslide.lists import parse_list
from autoslide.models import Block, BlockType
from autoslide.images import image_spec
from autoslide.tables import parse_table


def test_list_heading_and_items():
    model = parse_list("Heading\n- one\n- two")
    assert model.heading == "Heading"
    assert [i.text for i in model.items] == ["one", "two"]
    assert not model.compact


def test_list_sub_items():
    model = parse_list("- parent\n  - child")
    assert model.items[0].children == ["child"]
    assert not model.compact


def test_single_item_list_is_compact():
    assert parse_list("- only one").compact


def test_heading_with_no_bullet_is_heading_only():
    model = parse_list("Heading\n-")
    assert model.heading_only
    assert model.compact


def test_table_shading_cycle():
    rows = "\n".join(f"| r{i} | x |" for i in range(6))
    table = parse_table("| A | B |\n| --- | --- |\n" + rows)
    assert [row.shaded for row in table.rows] == [
        False,
        False,
        True,
        True,
        False,
        False,
    ]


def test_table_pads_short_rows():
    table = parse_table("| A | B | C |\n| - | - | - |\n| x |")
    assert table.columns == 3
    assert table.rows[0].cells == ["x", "", ""]


def test_non_table_content_is_rejected():
    assert parse_table("just a line") is None


def test_image_scaling_tiers_differ():
    block = Block(BlockType.IMAGE, "plot.pdf")
    assert image_spec(block, "slide").width != image_spec(block, "column").width
    assert image_spec(block, "poster").height.startswith("0.55")


def test_image_scale_suffix():
    spec = image_spec(Block(BlockType.IMAGE, "plot.pdf*0.5"), "slide")
    assert spec.path == "../assets/plot.pdf"
    assert spec.width == "0.75\\linewidth"


def test_generated_images_come_from_the_generated_dir():
    block = Block(BlockType.IMAGE, "fig.pdf", {"generated": True})
    assert image_spec(block).path == "../assets/generated/fig.pdf"


def test_inline_formatting():
    assert format_inline("*em* and [^2]") == "\\textit{em} and \\footnotemark[2]"


def test_inline_can_skip_footnotes():
    assert format_inline("[^2]", footnotes=False) == "[^2]"
