import os
import sys
import re


def process_heading_icons(heading_text: str) -> str:
    """Process heading text to replace :icon_name: with rendered SVG icons."""
    # First handle special icon mappings
    heading_text = heading_text.replace(":email:", ":envelope:")
    heading_text = heading_text.replace(":web:", ":globe:")

    # Pattern to match :icon_name: syntax
    icon_pattern = r":([a-zA-Z0-9_-]+):"

    def replace_icon(match):
        icon_name = match.group(1)
        return generate_svg_icon(icon_name)

    return re.sub(icon_pattern, replace_icon, heading_text)


def generate_svg_icon(icon_name: str) -> str:
    """Generate LaTeX code for an SVG icon with colored circle background."""
    import os

    # Get the directory where render.py is located
    render_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Construct the source path relative to render.py
    source_icon_path = os.path.join(
        render_dir, "icons", "light", f"{icon_name}-light.svg"
    )

    # Check if the source file exists
    if not os.path.exists(source_icon_path):
        # If icon doesn't exist, return the original text or a placeholder
        return f":{icon_name}:"

    # Destination PDF path in current working directory
    local_pdf_filename = f"{icon_name}-light.pdf"
    local_pdf_path = os.path.join(os.getcwd(), local_pdf_filename)

    # Convert SVG to PDF if it doesn't exist or source is newer
    if not os.path.exists(local_pdf_path) or source_is_newer(
        source_icon_path, local_pdf_path
    ):
        try:
            convert_svg_to_pdf(
                source_icon_path, local_pdf_path, "#0A2D64"
            )  # ncblue color
        except Exception as e:
            # If conversion fails, fall back to original text
            print(
                f"Warning: Could not convert icon {icon_name} to PDF: {e}",
                file=sys.stderr,
            )
            return f":{icon_name}:"

    # Generate TikZ code for icon with circular background using local PDF
    # Use proper LaTeX formatting with inline TikZ and includegraphics for PDF
    # Increased circle diameter by 50% then 20%: 0.4em -> 0.6em -> 0.72em, icon: 0.6em -> 0.9em -> 1.08em
    # Move entire icon to the left by 50% of circle size: 0.72em * 0.5 = 0.36em
    tikz_code = f"\\hspace{{-0.36em}}\\begin{{tikzpicture}}[baseline=-0.5ex] \\fill[ncblue!20] (0,0) circle (0.72em); \\node[inner sep=0pt] at (0,0) {{\\includegraphics[width=1.08em,height=1.08em]{{{local_pdf_filename}}}}}; \\end{{tikzpicture}}"

    return tikz_code


def source_is_newer(source_file: str, target_file: str) -> bool:
    """Check if source file is newer than target file."""
    import os

    try:
        source_stat = os.stat(source_file)
        target_stat = os.stat(target_file)
        return source_stat.st_mtime > target_stat.st_mtime
    except OSError:
        return True  # If target doesn't exist or error, consider source newer


def convert_svg_to_pdf(svg_path: str, pdf_path: str, color: str) -> None:
    """Convert SVG to PDF with specified color using cairosvg."""
    try:
        import cairosvg
        import xml.etree.ElementTree as ET

        # Read and modify SVG to apply color
        with open(svg_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        # Parse SVG and apply color
        svg_content = apply_color_to_svg(svg_content, color)

        # Convert to PDF
        cairosvg.svg2pdf(bytestring=svg_content.encode("utf-8"), write_to=pdf_path)

    except ImportError:
        # Fallback to reportlab if cairosvg not available
        convert_svg_to_pdf_reportlab(svg_path, pdf_path, color)


def apply_color_to_svg(svg_content: str, color: str) -> str:
    """Apply color to SVG content by replacing currentColor and stroke attributes."""
    import re

    # Replace currentColor with the specified color
    svg_content = svg_content.replace("currentColor", color)

    # Replace existing stroke colors (but not "none")
    svg_content = re.sub(
        r'stroke="(?!none)[^"]*"', f'stroke="{color}"', svg_content
    )
    svg_content = re.sub(
        r"stroke='(?!none)[^']*'", f"stroke='{color}'", svg_content
    )

    # Replace existing fill attributes (except "none")
    svg_content = re.sub(r'fill="(?!none)[^"]*"', f'fill="{color}"', svg_content)
    svg_content = re.sub(r"fill='(?!none)[^']*'", f"fill='{color}'", svg_content)

    return svg_content


def convert_svg_to_pdf_reportlab(
    svg_path: str, pdf_path: str, color: str
) -> None:
    """Fallback SVG to PDF conversion using reportlab."""
    try:
        from reportlab.graphics import renderPDF
        from reportlab.graphics.shapes import Drawing
        from reportlab.lib.colors import HexColor
        from svglib.svglib import renderSVG

        # This is a more complex fallback - for now, raise an error to indicate cairosvg is needed
        raise ImportError("cairosvg is required for SVG to PDF conversion")

    except ImportError:
        raise ImportError(
            "Either cairosvg or reportlab+svglib is required for SVG to PDF conversion"
        )