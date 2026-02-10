from .models import Block


def format_image(block: Block, has_columns: bool = False) -> str:
    """Format image block with auto-scaling and plain grey caption."""
    image_file = block.content
    caption = block.metadata.get("caption", "")

    # optional scaling of image via filename pattern imagefile.ext*scale
    parts = image_file.split("*")
    scale_factor = 1.0
    if len(parts) == 2:
        image_file = parts[0]
        scale_factor = float(parts[1])

    # Use different base scaling for single-column vs two-column layouts
    if has_columns:
        # Two-column layout: use linewidth (fits within column)
        width_limit = 1.0
        height_limit = 0.6
        width_setting = "width=\\linewidth"
        height_setting = "height=0.6\\textheight"
    else:
        # Single-column layout: use larger scaling to fill more space
        width_limit = 1.5
        height_limit = 0.7

    # calculate final scaling
    width_setting = f"width={width_limit * scale_factor}\\linewidth"
    height_setting = f"height={height_limit * scale_factor}\\textheight"

    return f"""\\begin{{center}}
\\includegraphics[{width_setting},{height_setting},keepaspectratio]{{{image_file}}}
\\end{{center}}
\\vspace{{-1em}}
\\textcolor{{gray}}{{{caption}}}"""