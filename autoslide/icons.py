"""``:icon:`` syntax -> a TikZ badge built from an SVG in ``icons/light/``.

This module does the file work (locate SVG, recolour it, convert to PDF); the
LaTeX badge itself is ``templates/blocks/icon.tex.j2``.
"""

import os
import re
import sys
from typing import Optional

from . import templating
from .theme import Theme, default_theme

_ICON_PATTERN = re.compile(r":([a-zA-Z0-9_-]+):")

#: Repository root, where the shared ``icons/`` directory lives.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def process_icons(
    text: str,
    output_dir: str = ".",
    theme: Optional[Theme] = None,
    engine: Optional[templating.TemplateEngine] = None,
) -> str:
    """Replace every ``:name:`` in ``text`` with a rendered icon badge."""
    theme = theme or default_theme()
    engine = engine or templating.engine(theme)

    for alias, target in theme.icons.aliases.items():
        text = text.replace(f":{alias}:", f":{target}:")

    return _ICON_PATTERN.sub(
        lambda match: render_icon(match.group(1), output_dir, theme, engine), text
    )


def render_icon(
    icon_name: str,
    output_dir: str = ".",
    theme: Optional[Theme] = None,
    engine: Optional[templating.TemplateEngine] = None,
) -> str:
    """Return LaTeX for one icon, or the literal ``:name:`` if unavailable."""
    theme = theme or default_theme()
    engine = engine or templating.engine(theme)

    source = os.path.join(_ROOT, "icons", "light", f"{icon_name}-light.svg")
    if not os.path.exists(source):
        return f":{icon_name}:"

    pdf_filename = f"{icon_name}-light.pdf"
    pdf_path = os.path.join(os.path.abspath(output_dir), pdf_filename)

    if not os.path.exists(pdf_path) or _source_is_newer(source, pdf_path):
        try:
            convert_svg_to_pdf(source, pdf_path, theme.icons.color)
        except Exception as error:  # missing cairosvg, unreadable SVG, ...
            print(
                f"Warning: Could not convert icon {icon_name} to PDF: {error}",
                file=sys.stderr,
            )
            return f":{icon_name}:"

    return engine.render_block("blocks/icon.tex.j2", pdf_filename=pdf_filename)


def _source_is_newer(source_file: str, target_file: str) -> bool:
    try:
        return os.stat(source_file).st_mtime > os.stat(target_file).st_mtime
    except OSError:
        return True


def convert_svg_to_pdf(svg_path: str, pdf_path: str, color: str) -> None:
    """Recolour an SVG and convert it to PDF."""
    import cairosvg

    with open(svg_path, "r", encoding="utf-8") as handle:
        svg_content = apply_color_to_svg(handle.read(), color)
    cairosvg.svg2pdf(bytestring=svg_content.encode("utf-8"), write_to=pdf_path)


def apply_color_to_svg(svg_content: str, color: str) -> str:
    """Force every stroke/fill in the SVG to ``color`` (leaving ``none`` alone)."""
    svg_content = svg_content.replace("currentColor", color)
    for attribute in ("stroke", "fill"):
        svg_content = re.sub(
            rf'{attribute}="(?!none)[^"]*"', f'{attribute}="{color}"', svg_content
        )
        svg_content = re.sub(
            rf"{attribute}='(?!none)[^']*'", f"{attribute}='{color}'", svg_content
        )
    return svg_content
