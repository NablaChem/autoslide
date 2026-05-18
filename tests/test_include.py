import pytest
from autoslide.models import BlockType


def test_include_inlines_content(parse, tmp_path):
    included = tmp_path / "part.md"
    included.write_text("### Included Slide ###\n\nIncluded text")
    main = tmp_path / "main.md"
    main.write_text("># part.md\n### After ###")

    slides = parse(main.read_text(), input_filename=str(main))
    all_first_blocks = [s[0] for s in slides]
    titles = [b.content for b in all_first_blocks if b.type == BlockType.SLIDE_TITLE]
    assert "Included Slide" in titles


def test_include_content_appears_before_following_content(parse, tmp_path):
    included = tmp_path / "part.md"
    included.write_text("### First ###")
    main = tmp_path / "main.md"
    main.write_text("># part.md\n### Second ###")

    slides = parse(main.read_text(), input_filename=str(main))
    assert slides[0][0].content == "First"
    assert slides[1][0].content == "Second"


def test_include_missing_file_does_not_raise(parse, tmp_path):
    main = tmp_path / "main.md"
    slides = parse("># nonexistent.md\n### After ###", input_filename=str(main))
    assert len(slides) >= 1


def test_include_missing_file_continues_parsing(parse, tmp_path):
    main = tmp_path / "main.md"
    slides = parse("># nonexistent.md\n### After ###", input_filename=str(main))
    titles = [b.content for s in slides for b in s if b.type == BlockType.SLIDE_TITLE]
    assert "After" in titles


def test_include_missing_file_prints_warning(parse, tmp_path, capsys):
    main = tmp_path / "main.md"
    parse("># nonexistent.md", input_filename=str(main))
    captured = capsys.readouterr()
    assert "nonexistent.md" in captured.err
