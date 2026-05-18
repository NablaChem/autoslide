from autoslide.models import BlockType


def test_equation_block_type(parse):
    slides = parse("$$x + y = z$$")
    assert slides[0][0].type == BlockType.ANNOTATED_EQUATION


def test_single_line_equation_metadata(parse):
    slides = parse("$$x + y = z$$")
    block = slides[0][0]
    assert block.metadata["equation"] == "$$x + y = z$$"


def test_single_line_equation_no_annotations(parse):
    slides = parse("$$x + y = z$$")
    assert slides[0][0].metadata["annotations"] == ""


def test_multiline_equation_type(parse):
    md = "$$\nx + y = z\n$$"
    slides = parse(md)
    assert slides[0][0].type == BlockType.ANNOTATED_EQUATION


def test_multiline_equation_content_in_metadata(parse):
    md = "$$\nx + y = z\n$$"
    slides = parse(md)
    assert "x + y = z" in slides[0][0].metadata["equation"]


def test_equation_with_annotations_type(parse):
    md = "$$x + y = z$$\n[[ x ]] first variable\n[[ z ]] result"
    slides = parse(md)
    assert slides[0][0].type == BlockType.ANNOTATED_EQUATION


def test_equation_annotations_in_metadata(parse):
    md = "$$x + y = z$$\n[[ x ]] first variable\n[[ z ]] result"
    slides = parse(md)
    annotations = slides[0][0].metadata["annotations"]
    assert "[[ x ]] first variable" in annotations
    assert "[[ z ]] result" in annotations


def test_equation_full_content_field(parse):
    # content holds the full raw block text including annotations
    md = "$$x + y = z$$\n[[ x ]] first variable"
    slides = parse(md)
    assert "$$x + y = z$$" in slides[0][0].content
    assert "[[ x ]] first variable" in slides[0][0].content


# --- regression tests for the heading-before-equation bug ---

def test_heading_before_equation_is_annotated_equation(parse):
    # Bug: heading on first line caused the whole block to be classified as TEXT
    md = "My Heading\n$$x + y = z$$"
    slides = parse(md)
    assert slides[0][0].type == BlockType.ANNOTATED_EQUATION


def test_heading_before_equation_stores_heading_in_metadata(parse):
    md = "My Heading\n$$x + y = z$$"
    slides = parse(md)
    assert slides[0][0].metadata["heading"] == "My Heading"


def test_heading_before_equation_equation_correct(parse):
    md = "My Heading\n$$x + y = z$$"
    slides = parse(md)
    assert slides[0][0].metadata["equation"] == "$$x + y = z$$"


def test_annotations_not_leaked_when_heading_present(parse):
    # Bug: [[ ]] lines leaked verbatim into LaTeX as TEXT content
    md = "My Heading\n$$x + y = z$$\n[[ x ]] first variable\n[[ z ]] result"
    slides = parse(md)
    block = slides[0][0]
    assert block.type == BlockType.ANNOTATED_EQUATION
    assert block.metadata["annotations"] == "[[ x ]] first variable\n[[ z ]] result"


def test_equation_without_heading_has_empty_heading(parse):
    slides = parse("$$x + y = z$$")
    assert slides[0][0].metadata.get("heading", "") == ""
