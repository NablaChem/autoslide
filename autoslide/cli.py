import os
import sys
import shutil
import subprocess

import click

from .parser import MarkdownBeamerParser
from .renderer import PosterRenderer, SlideRenderer

#: Markers that make a document a poster rather than a slide deck.
POSTER_MARKERS = ("=|=", "===")


@click.command()
@click.argument("markdown_file", type=click.Path(exists=True, readable=True))
@click.option(
    "--no-cache",
    is_flag=True,
    help="Disable reading from cache (writing to cache still enabled)",
)
@click.option(
    "--poster/--no-poster",
    default=None,
    help="Force poster or slide mode (default: auto-detect)",
)
@click.option(
    "--tracing",
    is_flag=True,
    help="Draw red border around every block for layout debugging",
)
def main(markdown_file, no_cache, poster, tracing):
    """Convert markdown file to LaTeX beamer presentation or A0 poster."""
    base_name = os.path.splitext(os.path.basename(markdown_file))[0]
    source_dir = os.path.dirname(os.path.abspath(markdown_file))

    with open(markdown_file, "r", encoding="utf-8") as handle:
        markdown_content = handle.read()

    is_poster = poster
    if is_poster is None:
        is_poster = any(marker in markdown_content for marker in POSTER_MARKERS)

    suffix = "autoposter" if is_poster else "autoslide"
    output_dir = f"{base_name}-{suffix}"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{base_name}.tex")

    slides = MarkdownBeamerParser(markdown_file, output_dir).parse(markdown_content)
    print(
        f"Parsed {len(slides)} slides ({'poster' if is_poster else 'slides'} mode)",
        file=sys.stderr,
    )

    renderer_class = PosterRenderer if is_poster else SlideRenderer
    renderer = renderer_class(
        output_dir,
        no_cache=no_cache,
        tracing=tracing,
        source_dir=source_dir,
    )
    latex_output = renderer.render_document(slides, base_name)

    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(latex_output)
    print(f"Generated {output_file}", file=sys.stderr)

    if not _compile(output_dir, base_name):
        return

    pdf_source = os.path.join(output_dir, f"{base_name}.pdf")
    pdf_destination = os.path.join(source_dir, f"{base_name}.pdf")
    if os.path.exists(pdf_source):
        shutil.copy2(pdf_source, pdf_destination)
        print(f"PDF copied to {pdf_destination}", file=sys.stderr)
    else:
        print(f"PDF file not found at {pdf_source}", file=sys.stderr)


def _compile(output_dir: str, base_name: str) -> bool:
    print("Compiling LaTeX to PDF...", file=sys.stderr)
    try:
        subprocess.run(
            ["latexmk", "-xelatex", "-interaction=nonstopmode", f"{base_name}.tex"],
            cwd=output_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        print(f"LaTeX compilation failed: {error}", file=sys.stderr)
        print(f"stdout: {error.stdout}", file=sys.stderr)
        print(f"stderr: {error.stderr}", file=sys.stderr)
        return False
    print("LaTeX compilation successful", file=sys.stderr)
    return True


if __name__ == "__main__":
    main()
