from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import LatexFormatter

STYLE = "default"


def style_defs() -> str:
    """Pygments colour definitions for the preamble."""
    return LatexFormatter(style=STYLE).get_style_defs()


def format_code(content: str, language: str) -> str:
    """Format code block using Pygments to generate LaTeX.

    Args:
        content: The code content
        language: The programming language for syntax highlighting

    Returns:
        LaTeX code with syntax highlighting
    """
    try:
        # Get the appropriate lexer for the language
        lexer = get_lexer_by_name(language, stripall=True)
    except Exception:
        # Fallback to plain text if language is not recognized
        lexer = TextLexer()

    # Configure LaTeX formatter
    # Options:
    # - style: color scheme (default is good, can also use 'monokai', 'friendly', etc.)
    # - linenos: False (no line numbers based on user preference)
    # - verboptions: additional options for Verbatim environment (e.g., fontsize)
    from .theme import default_theme

    formatter = LatexFormatter(
        style=STYLE,
        linenos=False,
        verboptions=f"fontsize={default_theme().fonts.code_size}",
    )

    # Generate LaTeX code
    latex_code = highlight(content, lexer, formatter)

    return latex_code
