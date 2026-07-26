"""Image geometry. Rendering lives in ``templates/blocks/image.tex.j2``."""

from dataclasses import dataclass
from typing import Optional

from .models import Block
from .theme import Theme, default_theme


@dataclass
class ImageSpec:
    path: str
    width: str
    height: str
    shift: str
    caption: str = ""


def image_spec(
    block: Block,
    context: str = "slide",
    theme: Optional[Theme] = None,
) -> ImageSpec:
    """Resolve an image block into concrete LaTeX lengths.

    ``context`` is ``"slide"`` (full width), ``"column"`` (inside a two-column
    section) or ``"poster"``; each has its own scaling tier in the theme. A
    trailing ``*factor`` on the filename scales that tier.
    """
    theme = theme or default_theme()
    image_file = block.content
    scale = 1.0
    if "*" in image_file:
        image_file, _, factor = image_file.partition("*")
        scale = float(factor)

    width_limit, height_limit, shift = getattr(theme.images, context)
    shift_length = f"{shift:g}em"
    subdir = "generated/" if block.metadata.get("generated", False) else ""

    return ImageSpec(
        path=f"../assets/{subdir}{image_file}",
        width=f"{width_limit * scale}\\linewidth",
        height=f"{height_limit * scale}\\textheight",
        shift=shift_length,
        caption=block.metadata.get("caption", ""),
    )
