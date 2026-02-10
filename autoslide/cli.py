import sys
import click

from .parser import MarkdownBeamerParser
from .generator import BeamerGenerator


@click.command()
@click.argument("markdown_file", type=click.Path(exists=True, readable=True))
def main(markdown_file):
    """Convert markdown file to LaTeX beamer presentation."""

    # Read the markdown file
    with open(markdown_file, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    # Parse and generate
    parser = MarkdownBeamerParser(markdown_file)
    slides = parser.parse(markdown_content)

    print(f"Parsed {len(slides)} slides", file=sys.stderr)

    generator = BeamerGenerator()
    latex_output = generator.generate_beamer(slides, "My Presentation")

    print(latex_output)


if __name__ == "__main__":
    main()