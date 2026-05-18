from autoslide.models import BlockType


def test_image_block_type(parse):
    slides = parse("::: photo.png: My Caption")
    assert slides[0][0].type == BlockType.IMAGE


def test_image_filename_extracted(parse):
    slides = parse("::: photo.png: My Caption")
    assert slides[0][0].content == "photo.png"


def test_image_caption_extracted(parse):
    slides = parse("::: photo.png: My Caption")
    assert slides[0][0].metadata["caption"] == "My Caption"


def test_image_empty_caption(parse):
    slides = parse("::: photo.png: ")
    assert slides[0][0].metadata["caption"] == ""


def test_image_svg_extension(parse):
    slides = parse("::: diagram.svg: A diagram")
    assert slides[0][0].content == "diagram.svg"
    assert slides[0][0].metadata["caption"] == "A diagram"


def test_image_path_with_subdirectory(parse):
    slides = parse("::: assets/photo.png: Caption")
    assert slides[0][0].content == "assets/photo.png"


def test_image_caption_with_spaces(parse):
    slides = parse("::: fig.png: A long multi word caption")
    assert slides[0][0].metadata["caption"] == "A long multi word caption"
