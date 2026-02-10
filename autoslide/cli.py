import sys
import os
import click

from .parser import MarkdownBeamerParser
from .generator import BeamerGenerator


@click.command()
@click.argument("markdown_file", type=click.Path(exists=True, readable=True))
def main(markdown_file):
    """Convert markdown file to LaTeX beamer presentation."""

    # Create output directory based on input filename
    base_name = os.path.splitext(os.path.basename(markdown_file))[0]
    output_dir = f"{base_name}-autoslide"

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Output filename
    output_file = os.path.join(output_dir, f"{base_name}.tex")

    # Read the markdown file
    with open(markdown_file, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    # Parse and generate
    parser = MarkdownBeamerParser(markdown_file, output_dir)
    slides = parser.parse(markdown_content)

    print(f"Parsed {len(slides)} slides", file=sys.stderr)

    generator = BeamerGenerator(output_dir)
    latex_output = generator.generate_beamer(slides, "My Presentation")

    # Write output to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(latex_output)

    print(f"Generated {output_file}", file=sys.stderr)


if __name__ == "__main__":
    main()