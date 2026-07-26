import pytest
from autoslide.parser import MarkdownBeamerParser
from autoslide.models import BlockType


@pytest.fixture
def parse_poster(monkeypatch):
    """Return a factory that gives back the parser (not just slides) for poster tests."""
    monkeypatch.setattr("autoslide.figures.generate_figure_file", lambda *a, **kw: None)

    def _parse(text, **kwargs):
        parser = MarkdownBeamerParser(**kwargs)
        parser.parse(text)
        return parser

    return _parse


# ---------------------------------------------------------------------------
# Basic separator parsing
# ---------------------------------------------------------------------------

def test_poster_column_break_creates_sentinel_slide(parse):
    slides = parse("=|=")
    assert len(slides) == 1
    assert slides[0][0].type == BlockType.POSTER_COLUMN_BREAK


def test_poster_column_close_creates_sentinel_slide(parse):
    slides = parse("===")
    assert len(slides) == 1
    assert slides[0][0].type == BlockType.POSTER_COLUMN_CLOSE


def test_poster_column_break_sentinel_has_one_block(parse):
    slides = parse("=|=")
    assert len(slides[0]) == 1


def test_poster_column_close_sentinel_has_one_block(parse):
    slides = parse("===")
    assert len(slides[0]) == 1


# ---------------------------------------------------------------------------
# Separator between boxes
# ---------------------------------------------------------------------------

def test_column_break_between_boxes(parse):
    md = "### Box A ###\ncontent\n\n=|=\n\n### Box B ###\ncontent"
    slides = parse(md)
    # slide 0: Box A, slide 1: sentinel, slide 2: Box B
    assert len(slides) == 3
    assert slides[0][0].type == BlockType.SLIDE_TITLE
    assert slides[1][0].type == BlockType.POSTER_COLUMN_BREAK
    assert slides[2][0].type == BlockType.SLIDE_TITLE


def test_column_close_between_boxes(parse):
    md = "### Box A ###\ncontent\n\n===\n\n### Box B ###\ncontent"
    slides = parse(md)
    assert len(slides) == 3
    assert slides[1][0].type == BlockType.POSTER_COLUMN_CLOSE


def test_alternating_separators(parse):
    md = (
        "### A ###\ncontent\n\n"
        "=|=\n\n"
        "### B ###\ncontent\n\n"
        "===\n\n"
        "### C ###\ncontent\n\n"
        "=|=\n\n"
        "### D ###\ncontent"
    )
    slides = parse(md)
    types = [s[0].type for s in slides]
    assert types == [
        BlockType.SLIDE_TITLE,
        BlockType.POSTER_COLUMN_BREAK,
        BlockType.SLIDE_TITLE,
        BlockType.POSTER_COLUMN_CLOSE,
        BlockType.SLIDE_TITLE,
        BlockType.POSTER_COLUMN_BREAK,
        BlockType.SLIDE_TITLE,
    ]


# ---------------------------------------------------------------------------
# is_poster flag
# ---------------------------------------------------------------------------

def test_is_poster_set_by_column_break(parse_poster):
    parser = parse_poster("=|=")
    assert parser.is_poster is True


def test_is_poster_set_by_column_close(parse_poster):
    parser = parse_poster("===")
    assert parser.is_poster is True


def test_is_poster_false_without_separators(parse_poster):
    parser = parse_poster("### Slide ###\ncontent")
    assert parser.is_poster is False


# ---------------------------------------------------------------------------
# Validation: separator must be alone on its slide
# ---------------------------------------------------------------------------

def test_column_break_with_content_after_raises(parse):
    md = "=|=\nstray content\n\n### Box B ###\ncontent"
    with pytest.raises(ValueError, match="poster separator"):
        parse(md)


def test_column_close_with_content_after_raises(parse):
    md = "===\nstray content\n\n### Box B ###\ncontent"
    with pytest.raises(ValueError, match="poster separator"):
        parse(md)
