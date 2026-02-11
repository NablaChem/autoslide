import sys
import os
import click
import subprocess
import shutil

from .parser import MarkdownBeamerParser
from .generator import BeamerGenerator


@click.command()
@click.argument("markdown_file", type=click.Path(exists=True, readable=True))
@click.option("--no-cache", is_flag=True, help="Disable reading from cache (writing to cache still enabled)")
def main(markdown_file, no_cache):
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

    generator = BeamerGenerator(output_dir, no_cache=no_cache)
    latex_output = generator.generate_beamer(slides, "My Presentation")

    # Write output to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(latex_output)

    print(f"Generated {output_file}", file=sys.stderr)

    # Compile LaTeX to PDF using latexmk
    print(f"Compiling LaTeX to PDF...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["latexmk", "-xelatex", "-interaction=nonstopmode", f"{base_name}.tex"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            check=True
        )
        print(f"LaTeX compilation successful", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"LaTeX compilation failed: {e}", file=sys.stderr)
        print(f"stdout: {e.stdout}", file=sys.stderr)
        print(f"stderr: {e.stderr}", file=sys.stderr)
        return

    # Copy PDF back to original directory
    pdf_source = os.path.join(output_dir, f"{base_name}.pdf")
    markdown_dir = os.path.dirname(os.path.abspath(markdown_file))
    pdf_destination = os.path.join(markdown_dir, f"{base_name}.pdf")

    if os.path.exists(pdf_source):
        shutil.copy2(pdf_source, pdf_destination)
        print(f"PDF copied to {pdf_destination}", file=sys.stderr)
    else:
        print(f"PDF file not found at {pdf_source}", file=sys.stderr)


if __name__ == "__main__":
    main()