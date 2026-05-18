from autoslide.models import BlockType


_TABLE = "| Col 1 | Col 2 |\n| --- | --- |\n| A | B |"


def test_table_block_type(parse):
    slides = parse(_TABLE)
    assert slides[0][0].type == BlockType.TABLE


def test_table_content_preserved(parse):
    slides = parse(_TABLE)
    content = slides[0][0].content
    assert "Col 1" in content
    assert "Col 2" in content
    assert "A" in content


def test_table_with_alignment_markers(parse):
    md = "| Left | Right |\n| :--- | ---: |\n| a | b |"
    slides = parse(md)
    assert slides[0][0].type == BlockType.TABLE


def test_two_column_table(parse):
    slides = parse(_TABLE)
    assert slides[0][0].type == BlockType.TABLE


def test_minimal_table_two_rows(parse):
    md = "| A |\n| - |"
    slides = parse(md)
    assert slides[0][0].type == BlockType.TABLE
