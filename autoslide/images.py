from .models import Block


def format_image(block: Block, has_columns: bool = False, output_dir: str = ".", is_poster: bool = False) -> str:
    """Format image block with auto-scaling and plain grey caption."""
    image_file = block.content
    caption = block.metadata.get("caption", "")

    # optional scaling of image via filename pattern imagefile.ext*scale
    parts = image_file.split("*")
    scale_factor = 1.0
    if len(parts) == 2:
        image_file = parts[0]
        scale_factor = float(parts[1])

    # Use different base scaling for poster vs slide layouts
    if is_poster:
        width_limit = 0.95
        height_limit = 0.55
        shift_up = 0
    elif has_columns:
        # Two-column layout: use linewidth (fits within column)
        width_limit = 1.0
        height_limit = 0.7
        shift_up = -0.5
    else:
        # Single-column layout: use larger scaling to fill more space
        width_limit = 1.5
        height_limit = 0.7
        shift_up = 0

    # calculate final scaling
    width_setting = f"width={width_limit * scale_factor}\\linewidth"
    height_setting = f"height={height_limit * scale_factor}\\textheight"

    # Determine image path based on whether it's generated or from assets
    if block.metadata.get("generated", False):
        image_path = f"../assets/generated/{image_file}"
    else:
        image_path = f"../assets/{image_file}"

    caption_latex = f"\n\\vspace{{-1em}}\n\\textcolor{{gray}}{{{caption}}}" if caption else ""
    return f"""\\begin{{center}}
    \\vspace{{{shift_up}em}}
\\includegraphics[{width_setting},{height_setting},keepaspectratio]{{{image_path}}}
\\end{{center}}{caption_latex}"""
