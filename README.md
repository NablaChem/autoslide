# AutoSlide

A tool to convert Markdown presentations to LaTeX Beamer slides.

## Overview

AutoSlide converts a custom Markdown syntax into LaTeX Beamer presentations. The tool parses Markdown files with special syntax for slides, sections, equations, images, and annotations, then generates LaTeX code that can be compiled with LuaLaTeX.

## Usage

```bash
# Convert markdown to LaTeX
python render.py examples/test.md > slides.tex

# Compile to PDF
latexmk -lualatex slides.tex
```

## Markdown Syntax

The tool supports a custom Markdown syntax for presentations:

- `## Section Title` - Creates section slides
- `### Slide Title` - Creates regular slides
- `### !Hidden Title` - Creates hidden slides
- `### ?Summary Title` - Creates section summary slides with orange title bar
- `-|-` - Column break for two-column layouts
- `$$ equation $$` - Math equations with annotations (see examples)
- `:::image.pdf: Caption` - Images with captions
- `[1] Footnote text` - Footnotes with numbers
- `[*] Footnote without number`
- Standard Markdown lists and text

## Requirements

- Python 3.x
- Click library (`pip install click`)
- LuaLaTeX for compilation
- Fira Sans font (used in the beamer theme)

## Output

The generated LaTeX uses a custom beamer theme. Customisation / custom templating currently is not supported.

![Example annotations](example.png)

```
### Molecular Hamiltonian ###################################################

$$\hat{H} = \hat{H}(Z_i, \mathbf{R}_i, N_e, \sigma)$$
                    ---  ------------  ---  ------
1^ Nuclear charges
2^ Nuclear positions
3^ \# electrons
4^ Net spin
3v Close to $\sum_i Z_i$
4v Mostly 1 or 3
1v test
2v test2

-|-

Implicit
- foobar
- snafu

[*] footline content without number

```