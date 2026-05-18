from autoslide.models import BlockType


def test_pure_list_block_type(parse):
    md = "- Item one\n- Item two\n- Item three"
    slides = parse(md)
    assert slides[0][0].type == BlockType.LIST


def test_pure_list_content_preserved(parse):
    md = "- Item one\n- Item two"
    slides = parse(md)
    assert "Item one" in slides[0][0].content
    assert "Item two" in slides[0][0].content


def test_single_dash_item_is_list(parse):
    slides = parse("- Only item")
    assert slides[0][0].type == BlockType.LIST


def test_heading_with_list_items_is_list(parse):
    md = "My Heading\n- Item one\n- Item two"
    slides = parse(md)
    assert slides[0][0].type == BlockType.LIST


def test_heading_with_list_content_preserved(parse):
    md = "My Heading\n- Item one\n- Item two"
    slides = parse(md)
    content = slides[0][0].content
    assert "My Heading" in content
    assert "Item one" in content


def test_sub_items_produce_list(parse):
    md = "- Main item\n  - Sub item\n  - Another sub"
    slides = parse(md)
    assert slides[0][0].type == BlockType.LIST


def test_heading_with_mixed_prose_is_not_list(parse):
    # Heading followed by non-list prose should NOT be detected as LIST
    md = "My Heading\nSome prose line\n- Item"
    slides = parse(md)
    assert slides[0][0].type == BlockType.TEXT
