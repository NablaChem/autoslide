import re


def format_text(content: str) -> str:
    """Format text content."""
    # Handle footnote references
    content = re.sub(r"\[\^(\d+)\]", r"\\footnotemark[\1]", content)
    # Handle italic formatting: *text* -> \textit{text}
    content = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", content)
    # Always add empty line after text blocks to preserve paragraph spacing
    return content + "\n"