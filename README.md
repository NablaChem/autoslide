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
- `$$ equation $$` - Math equations with annotations (see detailed syntax below)
- `:::image.pdf: Caption` - Images with captions
- `[1] Footnote text` - Footnotes with numbers
- `[*] Footnote without number`
- `// Comment text` - Comments (ignored during parsing)
- Standard Markdown lists and text

## Annotated Math Equations

AutoSlide supports a powerful syntax for annotating mathematical equations. This allows you to highlight specific parts of equations and add explanatory text above or below them.

### Basic Syntax

1. **Write your equation** using standard LaTeX math syntax within `$$ ... $$`
2. **Add a dash line** on the next line to mark which parts to annotate
3. **Specify annotations** using position markers with `^` (above) or `v` (below)

### Example

```markdown
$$\hat{H} = \hat{H}(Z_i, \mathbf{R}_i, N_e, \sigma)$$
                    ---  ------------  ---  ------
1^ Nuclear charges
2^ Nuclear positions  
3^ Number of electrons
4^ Net spin
3v Close to $\sum_i Z_i$
4v Mostly 1 or 3
```

### Annotation Rules

- **Dash positioning**: Use dashes (`---`) under the equation parts you want to annotate
- **Annotation markers**:
  - `N^` places annotation **above** the equation (where N is the position number)
  - `Nv` places annotation **below** the equation (where N is the position number)
- **Position numbering**: Numbers correspond to the order of dash segments from left to right
- **Text formatting**: Annotations support LaTeX math syntax like `$\sum_i Z_i$`

### Layout

- Left annotations (positions 1, 2) are right-aligned
- Right annotations (positions 3, 4+) are left-aligned  
- Multiple annotations create a pyramid-like layout for better readability
- Above and below annotations are automatically spaced to avoid overlap

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