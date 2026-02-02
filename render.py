import re
from typing import List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum
import click
import subprocess
import os
import tempfile
import sys
from tqdm import tqdm


class BlockType(Enum):
    SECTION = "section"
    SLIDE_TITLE = "slide_title"
    TITLE_PAGE = "title_page"
    ANNOTATED_EQUATION = "annotated_equation"
    TABLE = "table"
    LIST = "list"
    IMAGE = "image"
    FOOTNOTE = "footnote"
    FOOTLINE = "footline"
    TEXT = "text"
    COLUMN_BREAK = "column_break"
    PLOT = "plot"
    SCHEMATIC = "schematic"


@dataclass
class Block:
    type: BlockType
    content: str
    metadata: Dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MarkdownBeamerParser:
    def __init__(self, input_filename=None):
        self.blocks = []
        self.footnotes = {}
        self.current_slide_blocks = []
        self.slides = []
        self.figure_counter = 0
        self.input_filename = input_filename
        self.pending_figures = []  # Store figure info for later generation

    def parse(self, markdown_text: str) -> List[List[Block]]:
        """Parse markdown text and return list of slides, each containing blocks."""
        lines = markdown_text.strip().split("\n")
        current_block_lines = []

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Skip comment lines (starting with //)
            if line.startswith("//"):
                i += 1
                continue

            # Handle include lines (starting with >#)
            if line.startswith("># "):
                include_path = line[3:].strip()
                try:
                    include_content = self._read_include_file(include_path)
                    # Insert the content lines at current position
                    include_lines = include_content.strip().split("\n")
                    lines[i : i + 1] = (
                        include_lines  # Replace current line with include content
                    )
                    # Don't increment i since we want to process the first included line
                    continue
                except Exception as e:
                    # If include fails, treat as comment and skip
                    print(
                        f"Warning: Could not include file '{include_path}': {e}",
                        file=sys.stderr,
                    )
                    i += 1
                    continue

            # Empty line - end current block
            if not line:
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                i += 1
                continue

            # Check for section header
            if line.startswith("## "):
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                self._finish_current_slide()
                section_title = line[3:].strip()
                self.current_slide_blocks.append(
                    Block(BlockType.SECTION, section_title)
                )
                i += 1
                continue

            # Check for title page (five #)
            if line.startswith("##### "):
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                self._finish_current_slide()

                # Extract title from five # format
                title = line[6:].strip()  # Remove "##### "
                title = re.sub(r"#+$", "", title).strip()  # Remove trailing #

                self.current_slide_blocks.append(
                    Block(BlockType.TITLE_PAGE, title)
                )
                i += 1
                continue

            # Check for slide title
            if line.startswith("### "):
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                self._finish_current_slide()

                # Extract title and check for special markers
                title_match = re.match(r"### (!?)(\??) (.+?) #+", line)
                if title_match:
                    hide_slide = title_match.group(1) == "!"
                    section_summary = title_match.group(2) == "?"
                    title = title_match.group(3).strip()

                    metadata = {
                        "hide_slide": hide_slide,
                        "section_summary": section_summary,
                    }
                    self.current_slide_blocks.append(
                        Block(BlockType.SLIDE_TITLE, title, metadata)
                    )
                else:
                    # Fallback for simple titles
                    title = line[4:].strip()
                    title = re.sub(r"#+$", "", title).strip()
                    metadata = {"hide_slide": False, "section_summary": False}
                    self.current_slide_blocks.append(
                        Block(BlockType.SLIDE_TITLE, title, metadata)
                    )
                i += 1
                continue

            # Check for column break
            if line == "-|-":
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                self.current_slide_blocks.append(Block(BlockType.COLUMN_BREAK, ""))
                i += 1
                continue

            # Check for footnote definition (numbered or starred)
            if re.match(r"^\[[\d\*]+\] ", line):
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                footnote_match = re.match(r"^\[([^\]]+)\] (.+)", line)
                if footnote_match:
                    footnote_num = footnote_match.group(1)
                    footnote_text = footnote_match.group(2)
                    self.footnotes[footnote_num] = footnote_text
                    self.current_slide_blocks.append(
                        Block(
                            BlockType.FOOTNOTE, footnote_text, {"number": footnote_num}
                        )
                    )
                i += 1
                continue

            # Check for image
            if line.startswith(":::") and ":" in line[3:]:
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                # Parse image syntax: "::: filename.svg: Caption"
                image_match = re.match(r"^::: ([^:]+):(.*)$", line)
                if image_match:
                    image_file = image_match.group(1).strip()
                    caption = image_match.group(2).strip()
                    self.current_slide_blocks.append(
                        Block(BlockType.IMAGE, image_file, {"caption": caption})
                    )
                i += 1
                continue

            # Check for fenced code blocks (plot/schematic)
            if line.startswith("```") and ("plot" in line or "schematic" in line):
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []

                # Parse fenced code block
                plot_block, new_i = self._parse_fenced_code_block(lines, i)
                if plot_block:
                    self.current_slide_blocks.append(plot_block)
                i = new_i
                continue

            # Collect lines for current block (preserve original spacing)
            current_block_lines.append(
                lines[i]
            )  # Use original line, not stripped version
            i += 1

        # Process final block
        if current_block_lines:
            self._process_block_lines(current_block_lines)

        self._finish_current_slide()

        # Generate all pending figures now that we know each slide's layout
        self._generate_all_pending_figures()

        return self.slides

    def _parse_fenced_code_block(
        self, lines: List[str], start_i: int
    ) -> Tuple[Block, int]:
        """Parse a fenced code block (plot or schematic) and generate figure."""
        start_line = lines[start_i].strip()

        # Parse the opening line: ```plot[:caption] or ```schematic[:caption]
        if start_line.startswith("```plot"):
            block_type = BlockType.PLOT
            caption_part = start_line[7:]  # Remove "```plot"
        elif start_line.startswith("```schematic"):
            block_type = BlockType.SCHEMATIC
            caption_part = start_line[12:]  # Remove "```schematic"
        else:
            return None, start_i + 1

        # Extract caption if present
        caption = ""
        if caption_part.startswith(":"):
            caption = caption_part[1:].strip()

        # Find the closing ```
        code_lines = []
        i = start_i + 1
        while i < len(lines):
            if lines[i].strip() == "```":
                break
            code_lines.append(lines[i])
            i += 1

        if i >= len(lines):
            raise ValueError(
                f"Unclosed fenced code block starting at line {start_i + 1}"
            )

        # Store figure info for later generation (after we know full slide layout)
        code = "\n".join(code_lines)
        self.figure_counter += 1

        # Determine base filename
        if self.input_filename:
            base_name = os.path.splitext(os.path.basename(self.input_filename))[0]
        else:
            base_name = "figure"

        figure_filename = f"{base_name}.figure{self.figure_counter}.pdf"

        # Store figure info for later generation
        figure_info = {
            "code": code,
            "block_type": block_type,
            "caption": caption,
            "filename": figure_filename,
            "slide_index": len(self.slides),  # Current slide index
        }
        self.pending_figures.append(figure_info)

        # Create image block pointing to future generated figure
        metadata = {"caption": caption, "generated": True}
        image_block = Block(BlockType.IMAGE, figure_filename, metadata)

        return image_block, i + 1

    def _generate_all_pending_figures(self):
        """Generate all pending figures now that we know each slide's complete layout."""
        if not self.pending_figures:
            return

        print(f"Generating {len(self.pending_figures)} figures...", file=sys.stderr)

        for figure_info in tqdm(
            self.pending_figures,
            desc="Generating figures",
            unit="figure",
            file=sys.stderr,
        ):
            slide_index = figure_info["slide_index"]

            # Check if this slide has columns
            if slide_index < len(self.slides):
                slide_blocks = self.slides[slide_index]
                has_columns = any(
                    block.type == BlockType.COLUMN_BREAK for block in slide_blocks
                )
            else:
                # Figure is on current slide being built
                has_columns = any(
                    block.type == BlockType.COLUMN_BREAK
                    for block in self.current_slide_blocks
                )

            # Generate the figure with correct layout parameters
            self._generate_figure_file(
                figure_info["code"],
                figure_info["block_type"],
                figure_info["filename"],
                has_columns,
            )

    def _generate_figure_file(
        self, code: str, block_type: BlockType, filename: str, has_columns: bool = False
    ):
        """Generate a single figure file with the specified parameters."""
        # Create Python script for subplot execution
        python_script = self._create_matplotlib_script(
            code, block_type, filename, has_columns
        )

        # Write script to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as temp_file:
            temp_file.write(python_script)
            temp_script_path = temp_file.name

        try:
            # Execute Python script using subprocess
            result = subprocess.run(
                ["python", temp_script_path],
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Error generating figure {filename} ({block_type.value}):\n"
                    f"Code:\n{code}\n\n"
                    f"Error output:\n{result.stderr}"
                )

        finally:
            # Clean up temporary script
            try:
                os.unlink(temp_script_path)
            except OSError:
                pass

    def _create_matplotlib_script(
        self,
        user_code: str,
        block_type: BlockType,
        output_filename: str,
        has_columns: bool = False,
    ) -> str:
        """Create complete Python script for matplotlib figure generation."""

        # Determine figure parameters based on layout FIRST
        if has_columns:
            # Two-column layout: 4:3 aspect ratio with standard sizes
            figsize = "(8, 6)"
        else:
            # Single-column layout: 16:9 aspect ratio
            figsize = "(10, 5.625)"  # 16:9 aspect ratio

        font_size = "16"
        label_size = "25"
        tick_size = "18"
        line_width = "2"
        marker_size = "12"
        spine_width = "3"
        # Configure schematic vs plot styling
        if block_type == BlockType.SCHEMATIC:
            style_config = f"""
# Configure for schematic (no tick marks, thick axes in navy blue)
ncblue = '#0A2D64'  # Navy blue color from beamer theme
ax = plt.gca()
ax.spines['left'].set_linewidth({spine_width})
ax.spines['left'].set_color(ncblue)
ax.spines['bottom'].set_linewidth({spine_width})
ax.spines['bottom'].set_color(ncblue)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

# Set axis label colors to navy blue
ax.xaxis.label.set_color(ncblue)
ax.yaxis.label.set_color(ncblue)

# Remove all ticks
ax.set_xticks([])
ax.set_yticks([])
"""
        else:  # PLOT
            style_config = f"""
# Configure for plot (with tick marks, thick axes in navy blue)
ncblue = '#0A2D64'  # Navy blue color from beamer theme
ax = plt.gca()
ax.spines['left'].set_linewidth({spine_width})
ax.spines['left'].set_color(ncblue)
ax.spines['bottom'].set_linewidth({spine_width})
ax.spines['bottom'].set_color(ncblue)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

# Set axis label colors to navy blue
ax.xaxis.label.set_color(ncblue)
ax.yaxis.label.set_color(ncblue)

# Keep tick marks for plots with navy blue color  
plt.tick_params(axis='both', which='major', width=2, length=6, colors=ncblue)
"""

        script = f"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend

# Configure matplotlib with layout-specific parameters
plt.figure(figsize={figsize})

# Set font to match beamer (Fira Sans if available, fallback to sans-serif)
try:
    plt.rcParams['font.family'] = ['Fira Sans', 'DejaVu Sans', 'sans-serif']
except:
    plt.rcParams['font.family'] = 'sans-serif'

plt.rcParams['font.size'] = {font_size}
plt.rcParams['axes.labelsize'] = {label_size}
plt.rcParams['xtick.labelsize'] = {tick_size}
plt.rcParams['ytick.labelsize'] = {tick_size}
plt.rcParams['lines.linewidth'] = {line_width}
plt.rcParams['lines.markersize'] = {marker_size}

# Set default label positions to axis ends
plt.rcParams['xaxis.labellocation'] = 'right'
plt.rcParams['yaxis.labellocation'] = 'top'

# User code
{user_code}

{style_config}

# Save figure
plt.tight_layout()
plt.savefig('{output_filename}', format='pdf', bbox_inches='tight', dpi=300)
plt.close()
"""
        return script

    def _process_block_lines(self, lines: List[str]):
        """Process a block of lines to determine its type and content."""
        if not lines:
            return

        content = "\n".join(lines)

        # Check for equation (starts with $$)
        if lines[0].startswith("$$"):
            # Find where equation ends
            equation_end = -1
            for i, line in enumerate(lines):
                # For multiline equations, skip the first line which starts with $$
                # Only consider a line ending if it's not the first line or if it's a single line equation
                if line.endswith("$$") and (i > 0 or lines[0].strip() != "$$"):
                    equation_end = i
                    break

            if equation_end >= 0:
                equation_lines = lines[: equation_end + 1]
                annotation_lines = (
                    lines[equation_end + 1 :] if equation_end + 1 < len(lines) else []
                )

                # Always use ANNOTATED_EQUATION type, even if no annotations
                self.current_slide_blocks.append(
                    Block(
                        BlockType.ANNOTATED_EQUATION,
                        content,
                        {
                            "equation": "\n".join(equation_lines),
                            "annotations": (
                                "\n".join(annotation_lines) if annotation_lines else ""
                            ),
                        },
                    )
                )
                return

        # Check for table (markdown table syntax)
        if self._is_markdown_table(lines):
            self.current_slide_blocks.append(Block(BlockType.TABLE, content))
            return

        # Check for list (lines starting with - or numbered, or heading followed by dashes)
        has_dashes = any(line.strip().startswith("-") for line in lines)

        # Check for proper heading followed by list items
        # All lines after the first must be either empty or start with optional whitespace + dash + whitespace
        has_proper_heading = False
        if len(lines) > 1 and not lines[0].strip().startswith("-") and has_dashes:
            # Check that all lines after the first are either empty or proper list items
            lines_after_heading = lines[1:]
            has_proper_heading = all(
                not line.strip() or re.match(r"^\s*-\s", line)
                for line in lines_after_heading
            )

        is_all_dashes = all(
            line.strip().startswith("-") or not line.strip()
            for line in lines
            if line.strip()
        )

        if has_dashes and (is_all_dashes or has_proper_heading):
            self.current_slide_blocks.append(Block(BlockType.LIST, content))
            return

        # Default to text block
        self.current_slide_blocks.append(Block(BlockType.TEXT, content))

    def _is_markdown_table(self, lines: List[str]) -> bool:
        """Check if lines represent a markdown table."""
        if len(lines) < 2:
            return False

        # Look for separator line (second line should contain |---|---|)
        for i, line in enumerate(lines):
            line = line.strip()
            if i == 0:
                # First line should have pipes
                if not ("|" in line):
                    continue
            elif re.match(r"^\s*\|?[\s\-\|:]+\|?\s*$", line):
                # This is a separator line, check if previous line had pipes
                if i > 0 and "|" in lines[i - 1]:
                    return True
        return False

    def _finish_current_slide(self):
        """Finish current slide and add to slides list."""
        if self.current_slide_blocks:
            self.slides.append(self.current_slide_blocks.copy())
            self.current_slide_blocks = []

    def _read_include_file(self, include_path: str) -> str:
        """Read and return the content of an include file."""
        import os

        # Handle relative paths relative to the input file's directory
        if self.input_filename and not os.path.isabs(include_path):
            input_dir = os.path.dirname(self.input_filename)
            include_path = os.path.join(input_dir, include_path)

        with open(include_path, "r", encoding="utf-8") as f:
            return f.read()


class BeamerGenerator:
    def __init__(self):
        self.footnote_counter = 0
        self.node_counter = 0

    def generate_beamer(
        self, slides: List[List[Block]], title: str = "Presentation"
    ) -> str:
        """Generate LaTeX beamer code from parsed slides."""
        latex_parts = []

        # Document header
        latex_parts.append(self._generate_header(title))

        # Process each slide
        for slide in slides:
            slide_latex = self._generate_slide(slide)
            if slide_latex:  # Only add non-empty slides
                latex_parts.append(slide_latex)

        # Document footer
        latex_parts.append(self._generate_footer())

        return "\n".join(latex_parts)

    def _generate_header(self, title: str) -> str:
        """Generate LaTeX document header."""
        return r"""\documentclass[aspectratio=169,t]{beamer}
% Theme and font setup
\usetheme{default}
\usepackage{graphicx}
\usepackage{fontspec}
\usefonttheme{professionalfonts} % using non standard fonts for beamer
\usefonttheme{serif} % default family is serif
\setmainfont{Fira Sans}[
  UprightFont = *-Light,
  BoldFont = *,
  ItalicFont = *-Light Italic,
  BoldItalicFont = * Italic
]
\usepackage{xcolor}
\definecolor{navyblue}{RGB}{10,45,100}
\definecolor{ncorange}{RGB}{221,150,51}
\definecolor{ncblue}{RGB}{10,45,100}

\usepackage[para]{footmisc}
\setbeamercolor{section title}{fg=navyblue}
\setbeamerfont{section title}{series=\bfseries}

\setbeamercolor{frametitle}{bg=ncblue, fg=white}
%\setbeamertemplate{frametitle}[default][left]

\setbeamertemplate{navigation symbols}{}
\setbeamertemplate{itemize item}{\textcolor{navyblue}{\textendash}}
\setbeamertemplate{itemize subitem}{\textcolor{navyblue}{\textendash}}
\setbeamertemplate{itemize subsubitem}{\textcolor{navyblue}{\textendash}}
\setlength{\leftmargini}{1em}
\setlength{\leftmarginii}{2em}
\setlength{\leftmarginiii}{3em}
\setbeamercolor{footnote mark}{fg=orange}
\setbeamertemplate{footnote mark}{[\insertfootnotemark]}
\setbeamertemplate{frametitle}{%
  \vskip-0.2ex
  \makebox[\paperwidth][s]{%
    \begin{beamercolorbox}[wd=\paperwidth,ht=2.5ex,dp=1ex,leftskip=1em,rightskip=1em]{frametitle}%
      \usebeamerfont{frametitle}%
      \insertframetitle\ifx\insertframetitle\@empty\else\def\tempcomma{\,}\ifx\insertframetitle\tempcomma\else\hfill{\footnotesize \insertframenumber}\fi\fi
    \end{beamercolorbox}%
  }%
  % make sure all tikz node labels only exist on the same frame
  \tikzset{tikzmark prefix=frame\insertframenumber}
}
\usepackage{amsmath}
% Set equation numbers to orange color with orange parentheses
\renewcommand{\theequation}{\textcolor{ncorange}{\arabic{equation}}}
\makeatletter
\renewcommand{\tagform@}[1]{\maketag@@@{\textcolor{ncorange}{(#1)}}}
\makeatother
\usepackage{tikz}
\usetikzlibrary{tikzmark,calc,positioning}
\pgfdeclarelayer{background}
\pgfsetlayers{background,main}
\usepackage{colortbl}
\usepackage{array}
\usepackage{booktabs}
\setlength{\parskip}{1.5em}
\setlength{\parindent}{0pt}
\setlength{\abovedisplayskip}{0pt}
\setlength{\belowdisplayskip}{0pt}
\setlength{\abovedisplayshortskip}{0pt}
\setlength{\belowdisplayshortskip}{0pt}
\begin{document}"""

    def _generate_footer(self) -> str:
        """Generate LaTeX document footer."""
        return "\\end{document}"

    def _setup_slide_columns(self, slide_parts: List[str], has_columns: bool) -> bool:
        """Setup columns environment for consistent positioning."""
        slide_parts.append("\\begin{columns}[t]")
        if has_columns:
            slide_parts.append("\\begin{column}[t]{0.5\\textwidth}")
            return True
        else:
            # For single column, use full width and shift 2em left
            slide_parts.append("\\hspace{-2em}")
            slide_parts.append("\\begin{column}[t]{\\textwidth}")
            return True

    def _process_slide_blocks(
        self,
        blocks: List[Block],
        slide_parts: List[str],
        in_columns: bool,
        has_columns: bool = False,
    ) -> bool:
        """Process blocks for slide content."""
        for block in blocks:
            if block.type in [
                BlockType.SLIDE_TITLE,
                BlockType.FOOTLINE,
                BlockType.FOOTNOTE,
            ]:
                continue
            elif block.type == BlockType.SECTION:
                slide_parts.append(f"\\section{{{block.content}}}")
            elif block.type == BlockType.COLUMN_BREAK:
                if in_columns:
                    slide_parts.append("\\end{column}")
                    slide_parts.append("\\begin{column}[t]{0.5\\textwidth}")
                else:
                    slide_parts.append("\\begin{columns}[t]")
                    slide_parts.append("\\begin{column}[t]{0.5\\textwidth}")
                    in_columns = True
            else:
                slide_parts.append(self._format_block(block, has_columns))
        return in_columns

    def _finalize_slide(self, slide_parts: List[str], footnotes: List[Block]):
        """Finalize slide with columns ending, vfill, and footnotes."""
        # Always end columns since we always start them
        slide_parts.append("\\end{column}")
        slide_parts.append("\\end{columns}")

        # Add vfill to push footnotes to bottom
        slide_parts.append("")
        slide_parts.append("\\vfill")
        slide_parts.append("")

        # Add fake footnotes if any exist
        if footnotes:
            slide_parts.append(
                "\\hspace*{-2em}\\parbox[t]{0.95\\paperwidth}{"
                + self._format_fake_footnotes(footnotes)
                + "}"
            )

        # End minipage and frame
        slide_parts.append("\\end{minipage}")
        slide_parts.append("\\end{frame}")
        slide_parts.append("")  # Empty line between slides

    def _generate_slide(self, blocks: List[Block]) -> str:
        """Generate LaTeX for a single slide."""
        slide_parts = []
        slide_title = ""
        slide_metadata = {}
        has_columns = any(block.type == BlockType.COLUMN_BREAK for block in blocks)
        footline_content = ""
        footnotes = []

        # Extract slide title, footline, and footnotes
        for block in blocks:
            if block.type == BlockType.SLIDE_TITLE:
                slide_title = block.content
                slide_metadata = block.metadata
            elif block.type == BlockType.TITLE_PAGE:
                # Title page slides have different style
                return self._generate_title_page_slide(blocks)
            elif block.type == BlockType.FOOTLINE:
                footline_content = block.content
            elif block.type == BlockType.FOOTNOTE:
                footnotes.append(block)
            elif block.type == BlockType.SECTION:
                # Section slides have different style
                return self._generate_section_slide(block.content)

        # Skip hidden slides
        if slide_metadata.get("hide_slide", False):
            return ""

        # Handle section summary style
        if slide_metadata.get("section_summary", False):
            return self._generate_section_summary_slide(
                blocks, slide_title, footline_content
            )

        # Start normal frame with [t] option for top alignment
        frame_options = "[t]"
        if footline_content:
            frame_options = f"[t,{footline_content}]"

        if slide_title:
            slide_parts.append(f"\\begin{{frame}}{frame_options}{{{slide_title}}}")
        else:
            slide_parts.append(f"\\begin{{frame}}{frame_options}")

        # Start minipage for content
        slide_parts.append(
            "\\vspace{-1.5em}\\hspace{-0.3em}\\begin{minipage}[t][0.88\\textheight]{\\textwidth}"
        )

        # Setup columns and process blocks
        in_columns = self._setup_slide_columns(slide_parts, has_columns)
        in_columns = self._process_slide_blocks(
            blocks, slide_parts, in_columns, has_columns
        )

        # Finalize slide
        self._finalize_slide(slide_parts, footnotes)

        return "\n".join(part.rstrip() for part in slide_parts)

    def _generate_title_page_slide(self, blocks: List[Block]) -> str:
        """Generate a title page slide with blue bar and no page number."""
        slide_parts = []
        title = ""
        author = ""
        email = ""
        web = ""

        # Extract title and metadata from blocks
        for block in blocks:
            if block.type == BlockType.TITLE_PAGE:
                title = block.content
            elif block.type == BlockType.TEXT:
                content = block.content.strip()
                # Parse metadata fields
                lines = content.split('\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith(':author:'):
                        author = line[8:].strip()  # Remove :author: prefix
                    elif line.startswith(':email:'):
                        email = ":email: " + line[7:].strip()  # Keep :email: for icon processing
                    elif line.startswith(':web:'):
                        web = ":web: " + line[5:].strip()  # Keep :web: for icon processing

        # Start frame with special template that hides page number
        slide_parts.append("\\setbeamertemplate{frametitle}{%")
        slide_parts.append("  \\vskip-0.2ex")
        slide_parts.append("  \\makebox[\\paperwidth][s]{%")
        slide_parts.append("    \\begin{beamercolorbox}[wd=\\paperwidth,ht=2.5ex,dp=1ex,leftskip=1em,rightskip=1em]{frametitle}%")
        slide_parts.append("      \\usebeamerfont{frametitle}%")
        slide_parts.append("      \\insertframetitle")
        slide_parts.append("    \\end{beamercolorbox}%")
        slide_parts.append("  }%")
        slide_parts.append("  \\tikzset{tikzmark prefix=frame\\insertframenumber}")
        slide_parts.append("}")
        slide_parts.append("\\begin{frame}[t]")
        slide_parts.append("\\frametitle{\\,}")

        # Start minipage matching inspiration.tex layout
        slide_parts.append("\\vspace{-1.5em}\\hspace{-0.3em}\\begin{minipage}[t][0.88\\textheight]{\\textwidth}")
        slide_parts.append("")
        slide_parts.append("\\vfill")
        slide_parts.append("")

        # Add title with huge blue formatting
        slide_parts.append(f"{{\\huge\\color{{ncblue}} {title}}}")
        slide_parts.append("")

        # Add author if present
        if author:
            slide_parts.append(author)
            slide_parts.append("")

        slide_parts.append("\\vfill")
        slide_parts.append("")

        # Add email and web with icon processing
        contact_parts = []
        if email:
            processed_email = self._process_heading_icons(email)
            contact_parts.append(processed_email)
        if web:
            processed_web = self._process_heading_icons(web)
            contact_parts.append(processed_web)

        if contact_parts:
            slide_parts.append("\\hspace{2em}".join(contact_parts))  # 2em space between email and web
            slide_parts.append("")
            slide_parts.append("\\vspace{1em}")  # Add 1em space under web
            slide_parts.append("")

        slide_parts.append("")
        slide_parts.append("\\end{minipage}")
        slide_parts.append("\\end{frame}")
        slide_parts.append("% Restore original frametitle template")
        slide_parts.append("\\setbeamertemplate{frametitle}{%")
        slide_parts.append("  \\vskip-0.2ex")
        slide_parts.append("  \\makebox[\\paperwidth][s]{%")
        slide_parts.append("    \\begin{beamercolorbox}[wd=\\paperwidth,ht=2.5ex,dp=1ex,leftskip=1em,rightskip=1em]{frametitle}%")
        slide_parts.append("      \\usebeamerfont{frametitle}%")
        slide_parts.append("      \\insertframetitle\\ifx\\insertframetitle\\@empty\\else\\def\\tempcomma{\\,}\\ifx\\insertframetitle\\tempcomma\\else\\hfill{\\footnotesize \\insertframenumber}\\fi\\fi")
        slide_parts.append("    \\end{beamercolorbox}%")
        slide_parts.append("  }%")
        slide_parts.append("  \\tikzset{tikzmark prefix=frame\\insertframenumber}")
        slide_parts.append("}")
        slide_parts.append("")

        return "\n".join(slide_parts)

    def _generate_section_slide(self, section_title: str) -> str:
        """Generate a section slide with different styling."""
        return f"""\\setbeamercolor{{background canvas}}{{bg=ncblue}}\\begin{{frame}}[c]
\\begin{{center}}
{{\\color{{white}}\\Huge \\textbf{{{section_title}}}}}
\\end{{center}}
\\end{{frame}}
\\setbeamercolor{{background canvas}}{{bg=white}}
"""

    def _generate_section_summary_slide(
        self, blocks: List[Block], slide_title: str, footline_content: str
    ) -> str:
        """Generate a section summary slide with orange title bar."""
        slide_parts = []
        has_columns = any(block.type == BlockType.COLUMN_BREAK for block in blocks)
        footnotes = []

        # Extract footnotes
        for block in blocks:
            if block.type == BlockType.FOOTNOTE:
                footnotes.append(block)

        # Set orange color before frame begins
        slide_parts.append("\\setbeamercolor{frametitle}{bg=ncorange, fg=white}")

        # Start normal frame with [t] option for top alignment
        frame_options = "[t]"
        if footline_content:
            frame_options = f"[t,{footline_content}]"

        slide_parts.append(f"\\begin{{frame}}{frame_options}")

        # Add frame title if present
        if slide_title:
            slide_parts.append(f"\\frametitle{{{slide_title}}}")

        # Start minipage for content
        slide_parts.append(
            "\\vspace{-1.5em}\\hspace{-0.3em}\\begin{minipage}[t][0.88\\textheight]{\\textwidth}"
        )

        # Setup columns and process blocks
        in_columns = self._setup_slide_columns(slide_parts, has_columns)
        in_columns = self._process_slide_blocks(
            blocks, slide_parts, in_columns, has_columns
        )

        # Finalize slide
        self._finalize_slide(slide_parts, footnotes)

        # Reset frametitle color back to original blue
        slide_parts.append("\\setbeamercolor{frametitle}{bg=ncblue, fg=white}")

        return "\n".join(slide_parts)

    def _format_block(self, block: Block, has_columns: bool = False) -> str:
        """Format a single block based on its type."""
        if block.type == BlockType.ANNOTATED_EQUATION:
            return self._format_annotated_equation(block)
        elif block.type == BlockType.TABLE:
            return self._format_table(block.content)
        elif block.type == BlockType.LIST:
            return self._format_list(block.content)
        elif block.type == BlockType.IMAGE:
            return self._format_image(block, has_columns)
        elif block.type == BlockType.FOOTNOTE:
            return f"\\footnote[{block.metadata['number']}]{{{block.content}}}"
        elif block.type == BlockType.TEXT:
            return self._format_text(block.content)
        else:
            return block.content

    def _format_annotated_equation(self, block: Block) -> str:
        """Format an annotated equation with tikzmarknode annotations."""
        equation = block.metadata["equation"]
        annotations = block.metadata["annotations"]

        # Parse the equation (remove $$ markers but preserve internal spacing)
        equation_content = equation.strip()
        if equation_content.startswith("$$") and equation_content.endswith("$$"):
            # Remove $$ from first and last lines while preserving internal formatting
            lines = equation_content.split("\n")
            if len(lines) == 1:
                # Single line equation
                equation_content = lines[0][2:-2]
            else:
                # Multi-line equation
                lines[0] = lines[0][2:]  # Remove $$ from first line
                lines[-1] = lines[-1][:-2]  # Remove $$ from last line
                equation_content = "\n".join(lines)

        # Parse new annotation format: [[ exact string ]] Label
        annotation_specs = []
        if annotations.strip():
            for line in annotations.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Match [[ exact string ]] Label format
                match = re.match(r"^\[\[\s*(.*)\s*\]\]\s+(.*)$", line)
                if match:
                    exact_string = match.group(
                        1
                    ).strip()  # Trim edges but keep internal whitespace
                    label = match.group(2).strip()
                    annotation_specs.append((exact_string, label))

        # If no annotations, render as simple equation
        if not annotation_specs:
            return f"\\begin{{align}}\\abovedisplayskip=0pt\\belowdisplayskip=0pt{equation_content}\\end{{align}}"

        # Create tikzmarknode-wrapped equation
        annotated_equation, node_names = self._create_tikzmarknode_equation_new(
            equation_content, annotation_specs
        )

        # Determine optimal placement for annotations
        above_placements, below_placements = self._determine_annotation_placement(
            annotated_equation, annotation_specs, node_names
        )

        # Convert placements to old format for existing tikzpicture generation
        annotations_above = {}
        annotations_below = {}
        for i, (exact_string, label) in enumerate(annotation_specs, 1):
            if i in above_placements:
                annotations_above[i] = label
            elif i in below_placements:
                annotations_below[i] = label

        # Generate tikzpicture with annotations
        if annotations_above or annotations_below:
            tikz_code, space_requirements = self._generate_tikzpicture_annotations(
                annotations_above,
                annotations_below,
                node_names,
                above_placements,
                below_placements,
            )

            # Calculate required spacing
            below_space = space_requirements["below"]

            # Generate the complete LaTeX output
            latex_parts = []

            # Add the equation first so nodes are defined
            latex_parts.append(
                f"\\begin{{align}}\\abovedisplayskip=0pt\\belowdisplayskip=0pt{annotated_equation}\\end{{align}}"
            )

            # Add annotation lines and text (background fill is now handled by tikzmarknode)
            latex_parts.extend(tikz_code)

            # Add space below for below annotations (convert from pt to em: 1em ≈ 12pt)
            if below_space > 0:
                # Convert from pt to em and reduce by 2em
                below_space_em = below_space / 12.0  # Convert pt to em
                adjusted_below_space = max(0, below_space_em - 2)
                latex_parts.append("")  # Empty line for proper spacing
                if adjusted_below_space > 0:
                    latex_parts.append(f"\\vspace{{{adjusted_below_space:.1f}em}}")
        else:
            # No annotations, just the equation
            latex_parts = [
                f"\\begin{{align}}\\abovedisplayskip=0pt\\belowdisplayskip=0pt{annotated_equation}\\end{{align}}"
            ]

        return "\n".join(latex_parts)

    def _create_tikzmarknode_equation_new(
        self, equation_content: str, annotation_specs: List[Tuple[str, str]]
    ) -> Tuple[str, Dict[int, str]]:
        """Create equation with tikzmarknode wrappers based on exact string matching."""
        result = equation_content
        node_names = {}  # Map annotation position to node name

        # Process annotations in order from longest to shortest to avoid substring conflicts
        # Sort by string length descending, but preserve original indices for node naming
        sorted_specs = sorted(
            enumerate(annotation_specs, 1), key=lambda x: len(x[1][0]), reverse=True
        )

        for i, (exact_string, label) in sorted_specs:
            # Find the first occurrence of the exact string that's not inside tikzmarknode
            pos = result.find(exact_string)

            # Check if this match is inside an existing tikzmarknode wrapper
            while pos != -1:
                # Look backwards from pos to see if we're inside a tikzmarknode
                before_match = result[:pos]
                # Find the last tikzmarknode opening before this position (including the configuration)
                last_node_start = before_match.rfind("\\tikzmarknode[")
                if last_node_start != -1:
                    # Find the corresponding closing brace
                    brace_count = 0
                    inside_tikzmarknode = False
                    for j in range(
                        last_node_start + len("\\tikzmarknode{"),
                        len(before_match) + len(exact_string),
                    ):
                        if j >= len(result):
                            break
                        char = result[j]
                        if char == "{":
                            brace_count += 1
                            if brace_count == 1:  # This is the content opening brace
                                content_start = j + 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:  # This closes the content
                                content_end = j
                                # Check if our match is within this tikzmarknode content
                                if content_start <= pos < content_end:
                                    inside_tikzmarknode = True
                                break

                    if inside_tikzmarknode:
                        # Look for next occurrence after this tikzmarknode
                        pos = result.find(exact_string, pos + len(exact_string))
                        continue

                # This position is valid (not inside tikzmarknode)
                break

            if pos == -1:
                raise ValueError(
                    f"Annotation string '[[ {exact_string} ]]' not found in equation (or only found inside existing annotations)"
                )

            # Generate unique node name
            self.node_counter += 1
            node_name = f"node{self.node_counter}"
            node_names[i] = node_name

            # Replace the exact string with tikzmarknode wrapper that includes background fill
            before = result[:pos]
            after = result[pos + len(exact_string) :]
            wrapped = f"\\tikzmarknode[fill=ncorange!25,inner sep=1pt,outer sep=0pt]{{{node_name}}}{{{exact_string}}}"
            result = before + wrapped + after

        return result, node_names

    def _determine_annotation_placement(
        self,
        equation_with_nodes: str,
        annotation_specs: List[Tuple[str, str]],
        node_names: Dict[int, str],
    ) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]]]:
        """Determine optimal placement for annotations using bounding box analysis.

        Args:
            equation_with_nodes: LaTeX equation string with tikzmarknode wrappers already inserted
            annotation_specs: List of (exact_string, label) tuples
            node_names: Mapping from annotation position to node name

        Returns:
            Tuple of (above_placements, below_placements) where each is a dict mapping
            annotation position -> (vertical_coordinate_em, anchor_direction)
            anchor_direction is either "base east" (right-aligned) or "base west" (left-aligned)
        """
        if not annotation_specs:
            return {}, {}

        # Configuration - all values in pt (points)
        PAGE_WIDTH_PT = 455.0  # Page width in points
        HORIZONTAL_PADDING_PT = 10.0  # Clearance around annotations in points

        # Step 1: Measure bounding boxes and node positions using LaTeX
        try:
            bounding_boxes, node_positions, node_shifts = (
                self._measure_annotation_bounding_boxes(
                    equation_with_nodes, annotation_specs, node_names
                )
            )
        except Exception as e:
            print(f"Error measuring bounding boxes: {e}", file=sys.stderr)
            print(f"Equation: {equation_with_nodes}", file=sys.stderr)
            print(f"Annotations: {annotation_specs}", file=sys.stderr)
            raise
            # Fallback to simple placement
            below_placements = {}
            for i, (exact_string, label) in enumerate(annotation_specs, 1):
                if i in node_names:
                    below_placements[i] = (2.0, "base west")
            return {}, below_placements

        # Step 2: Find optimal placement using brute force search
        above_placements, below_placements = self._find_optimal_placement(
            annotation_specs,
            bounding_boxes,
            node_positions,
            node_names,
            PAGE_WIDTH_PT,
            HORIZONTAL_PADDING_PT,
            node_shifts,
        )

        # print(f"Debug: Measured node positions: {node_positions}", file=sys.stderr)
        # print(f"Debug: Final above_placements: {above_placements}", file=sys.stderr)
        # print(f"Debug: Final below_placements: {below_placements}", file=sys.stderr)
        return above_placements, below_placements

    def _measure_annotation_bounding_boxes(
        self,
        equation_with_nodes: str,
        annotation_specs: List[Tuple[str, str]],
        node_names: Dict[int, str],
    ) -> Tuple[Dict[int, Tuple[float, float]], Dict[int, float], Dict[int, float]]:
        """Measure bounding boxes of annotation text and tikzmarknode positions using LaTeX.

        Returns:
            Tuple of (bounding_boxes, node_positions, node_shifts) where:
            - bounding_boxes: Dict mapping annotation index -> (width_pt, height_pt)
            - node_positions: Dict mapping annotation index -> x_position_pt
            - node_shifts: Dict mapping annotation index -> y_shift_from_baseline_pt
        """
        import tempfile
        import os
        import subprocess
        import re
        import shutil

        # Create a temporary directory for LaTeX compilation
        temp_dir = tempfile.mkdtemp()

        try:
            # Create a temporary LaTeX document to measure all annotations
            measurement_latex = self._create_measurement_document(
                equation_with_nodes, annotation_specs, node_names
            )

            # Write to temporary file in the temporary directory
            temp_tex_path = os.path.join(temp_dir, "measurement.tex")
            with open(temp_tex_path, "w", encoding="utf-8") as f:
                f.write(measurement_latex)

            # Create empty navigation file to satisfy beamer requirements
            with open(os.path.join(temp_dir, "measurement.nav"), "w") as f:
                f.write("")

            # Run latexmk with XeLaTeX to compile and measure (handles multiple runs automatically)
            result = subprocess.run(
                ["latexmk", "-xelatex", "-interaction=nonstopmode", "measurement.tex"],
                capture_output=True,
                text=True,
                cwd=temp_dir,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"LaTeX compilation failed with return code {result.returncode}, see {temp_dir} for details.\n"
                )

            # Parse measurements from log file
            log_path = os.path.join(temp_dir, "measurement.log")

            # Debug output removed

            bounding_boxes, node_positions, node_shifts = (
                self._parse_measurements_from_log(log_path, len(annotation_specs))
            )

            # Debug: print measurements (only if verbose mode enabled)
            # print(f"Debug: Measured bounding boxes: {bounding_boxes}", file=sys.stderr)
            # print(f"Debug: Measured node positions: {node_positions}", file=sys.stderr)
            # print(f"Debug: Measured node shifts: {node_shifts}", file=sys.stderr)

            return bounding_boxes, node_positions, node_shifts

        finally:
            # Clean up entire temporary directory
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass

    def _create_measurement_document(
        self,
        equation_with_nodes: str,
        annotation_specs: List[Tuple[str, str]],
        node_names: Dict[int, str],
    ) -> str:
        """Create LaTeX document for measuring annotation bounding boxes."""
        # Use exactly the same preamble as the main document
        preamble = r"""\documentclass[aspectratio=169,t]{beamer}
% Theme and font setup
\usetheme{default}
\usepackage{graphicx}
\usepackage{fontspec}
\usefonttheme{professionalfonts} % using non standard fonts for beamer
\usefonttheme{serif} % default family is serif
\setmainfont{Fira Sans}[
  UprightFont = *-Light,
  BoldFont = *,
  ItalicFont = *-Light Italic,
  BoldItalicFont = * Italic
]
\usepackage{xcolor}
\definecolor{navyblue}{RGB}{10,45,100}
\definecolor{ncorange}{RGB}{221,150,51}
\definecolor{ncblue}{RGB}{10,45,100}

\usepackage[para]{footmisc}
\setbeamercolor{section title}{fg=navyblue}
\setbeamerfont{section title}{series=\bfseries}

\setbeamercolor{frametitle}{bg=ncblue, fg=white}
\setbeamertemplate{navigation symbols}{}
\setbeamertemplate{itemize item}{\textcolor{navyblue}{\textendash}}
\setbeamertemplate{itemize subitem}{\textcolor{navyblue}{\textendash}}
\setbeamertemplate{itemize subsubitem}{\textcolor{navyblue}{\textendash}}
\setlength{\leftmargini}{1em}
\setlength{\leftmarginii}{2em}
\setlength{\leftmarginiii}{3em}
\setbeamercolor{footnote mark}{fg=orange}
\setbeamertemplate{footnote mark}{[\insertfootnotemark]}
\setbeamertemplate{frametitle}{%
  \vskip-0.2ex
  \makebox[\paperwidth][s]{%
    \begin{beamercolorbox}[wd=\paperwidth,ht=2.5ex,dp=1ex,leftskip=1em,rightskip=1em]{frametitle}%
      \usebeamerfont{frametitle}%
      \insertframetitle\hfill{\footnotesize \insertframenumber}
    \end{beamercolorbox}%
  }%
  \tikzset{tikzmark prefix=frame\insertframenumber}
}
\usepackage{amsmath}
\renewcommand{\theequation}{\textcolor{ncorange}{\arabic{equation}}}
\makeatletter
\renewcommand{\tagform@}[1]{\maketag@@@{\textcolor{ncorange}{(#1)}}}
\makeatother
\usepackage{tikz}
\usetikzlibrary{tikzmark,calc,positioning}
\pgfdeclarelayer{background}
\pgfsetlayers{background,main}
\usepackage{colortbl}
\usepackage{array}
\usepackage{booktabs}
\setlength{\parskip}{1.5em}
\setlength{\parindent}{0pt}
\setlength{\abovedisplayskip}{0pt}
\setlength{\belowdisplayskip}{0pt}
\setlength{\abovedisplayshortskip}{0pt}
\setlength{\belowdisplayshortskip}{0pt}

\begin{document}
\newlength{\tempx}
\begin{frame}[t]
\scriptsize
"""

        # Add the equation with tikzmarknode wrappers to measure node positions
        # Ensure the equation has proper line endings for align environment
        equation_lines = equation_with_nodes.strip().split("\n")
        formatted_lines = []
        for i, line in enumerate(equation_lines):
            line = line.strip()
            if line and i < len(equation_lines) - 1:
                formatted_lines.append(line)
            elif line:
                formatted_lines.append(line)

        # Add baseline node with space character at the beginning of the equation
        # Generate unique baseline node name
        self.node_counter += 1
        baseline_node_name = f"baseline{self.node_counter}"

        # Insert the baseline node at the start of the first line
        if formatted_lines:
            formatted_lines[0] = (
                f"\\tikzmarknode{{{baseline_node_name}}}{{ }} {formatted_lines[0]}"
            )
        else:
            formatted_lines = [f"\\tikzmarknode{{{baseline_node_name}}}{{ }}"]

        equation_with_baseline = "\n".join(formatted_lines)

        equation_command = f"""
% Render equation with baseline node to measure node positions
\\begin{{align}}{equation_with_baseline}\\end{{align}}
"""

        # Create measurement commands for each annotation text
        measurement_commands = [equation_command]
        for i, (exact_string, label) in enumerate(annotation_specs, 1):
            # Use letters instead of numbers for savebox names (A, B, C, etc.)
            letter = chr(ord("A") + i - 1)  # A=1, B=2, C=3, etc.
            measurement_commands.append(
                f"""
% Measure annotation {i}: {label}
\\newsavebox{{\\measurebox{letter}}}
\\sbox{{\\measurebox{letter}}}{{\\scriptsize {label}}}
\\typeout{{ANNOTATION{i}: width=\\the\\wd\\measurebox{letter}, height=\\the\\ht\\measurebox{letter}}}
"""
            )

        # Add position measurements for each node using tikz coordinate extraction
        # These need to be after the equation is rendered so the nodes exist
        position_measurements = []
        position_measurements.append("\\begin{tikzpicture}[remember picture,overlay]")

        # First measure baseline node position
        position_measurements.append(
            f"""
% Measure position of baseline node ({baseline_node_name})
\\coordinate (temp) at ({baseline_node_name}.base);
\\path let \\p1 = (temp) in \\pgfextra{{
    \\pgfmathsetmacro{{\\tempx}}{{\\x{{1}}/1pt}}
    \\pgfmathsetmacro{{\\tempy}}{{\\y{{1}}/1pt}}
    \\typeout{{BASELINEPOS: x=\\tempx pt, y=\\tempy pt}}
}};
"""
        )

        # Then measure annotation node positions
        for i, node_name in node_names.items():
            position_measurements.append(
                f"""
% Measure position of node {i} ({node_name})
\\coordinate (temp) at ({node_name}.base);
\\path let \\p1 = (temp) in \\pgfextra{{
    \\pgfmathsetmacro{{\\tempx}}{{\\x{{1}}/1pt}}
    \\pgfmathsetmacro{{\\tempy}}{{\\y{{1}}/1pt}}
    \\typeout{{NODEPOS{i}: x=\\tempx pt, y=\\tempy pt}}
}};
"""
            )
        position_measurements.append("\\end{tikzpicture}")

        # Combine all measurements: equation first, then text measurements, then position measurements
        measurement_commands.extend(position_measurements)

        document = (
            preamble
            + "\n".join(measurement_commands)
            + "\n\\end{frame}\n\\end{document}"
        )
        return document

    def _parse_measurements_from_log(
        self, log_path: str, num_annotations: int
    ) -> Tuple[Dict[int, Tuple[float, float]], Dict[int, float], Dict[int, float]]:
        """Parse bounding box measurements and node positions from LaTeX log file.

        Returns:
            Tuple of (bounding_boxes, node_positions, node_shifts) where:
            - bounding_boxes: Dict mapping annotation index -> (width_pt, height_pt)
            - node_positions: Dict mapping annotation index -> x_position_pt
            - node_shifts: Dict mapping annotation index -> y_shift_from_baseline_pt
        """
        bounding_boxes = {}
        node_positions = {}
        node_shifts = {}

        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()

        # Parse baseline position first
        baseline_y = None
        baseline_pattern = "BASELINEPOS: x=([0-9.-]+)pt, y=([0-9.-]+)pt"
        baseline_match = re.search(baseline_pattern, log_content)
        if baseline_match:
            baseline_y = float(baseline_match.group(2))
        else:
            print("Warning: Could not find baseline position", file=sys.stderr)
            baseline_y = 0.0  # Fallback to 0 if baseline not found

        # Parse bounding box measurements from typeout commands
        for i in range(1, num_annotations + 1):
            pattern = f"ANNOTATION{i}: width=([0-9.]+)pt, height=([0-9.]+)pt"
            match = re.search(pattern, log_content)
            if match:
                width_pt = float(match.group(1))
                height_pt = float(match.group(2))
                # Keep values in pt - no conversion needed
                bounding_boxes[i] = (width_pt, height_pt)
            else:
                # Fallback if measurement not found
                print(
                    f"Warning: Could not find measurement for annotation {i}",
                    file=sys.stderr,
                )
                bounding_boxes[i] = (50.0, 12.0)  # Default reasonable size in pt

        # Parse node position measurements and calculate shifts from baseline
        for i in range(1, num_annotations + 1):
            # Look for the format: NODEPOS1: x=123.456pt, y=789.012pt (no space before pt)
            pattern = f"NODEPOS{i}: x=([0-9.-]+)pt, y=([0-9.-]+)pt"
            match = re.search(pattern, log_content)
            if match:
                x_pt = float(match.group(1))
                y_pt = float(match.group(2))
                # Keep x position in pt - no conversion needed
                node_positions[i] = x_pt
                # Calculate shift from baseline (positive means above baseline)
                node_shifts[i] = y_pt - baseline_y

        return bounding_boxes, node_positions, node_shifts

    def _find_optimal_placement(
        self,
        annotation_specs: List[Tuple[str, str]],
        bounding_boxes: Dict[int, Tuple[float, float]],
        node_positions: Dict[int, float],
        node_names: Dict[int, str],
        page_width_pt: float,
        horizontal_padding_pt: float,
        node_shifts: Dict[int, float],
    ) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]]]:
        """Find optimal placement using brute force search with minimal vertical levels."""
        from itertools import product

        num_annotations = len(annotation_specs)

        # Simple brute force: try increasing number of levels until we find a solution
        max_attempts = 5  # Safety limit

        for num_levels in range(1, max_attempts + 1):
            # Try with num_levels below the equation (keep it simple - only below for now)
            # Use 15pt spacing between levels as specified
            base_level_pt = 15.0  # First level at 15pt below equation
            levels_below = [base_level_pt + i * 15.0 for i in range(num_levels)]
            levels_above = [20.0]

            # Try all combinations for this number of levels
            all_combinations = self._generate_placement_combinations(
                num_annotations, levels_above, levels_below
            )
            # Remove debug code - let the normal algorithm run
            c = (
                ("below", 15.0, "base east"),
                ("below", 15.0, "base east"),
                ("below", 15.0, "base east"),
                ("below", 15.0, "base west"),
            )
            # all_combinations = [c]
            for combination in all_combinations:
                if self._check_placement_validity(
                    combination,
                    bounding_boxes,
                    node_positions,
                    page_width_pt,
                    horizontal_padding_pt,
                    node_shifts,
                ):
                    # Found valid placement with num_levels levels
                    above_placements = {}
                    below_placements = {}

                    # print(f"Debug: Found valid placement with {num_levels} levels: {combination}", file=sys.stderr)
                    for i, (position, level, anchor) in enumerate(combination, 1):
                        if i in node_names:
                            if position == "above":
                                above_placements[i] = (level, anchor)
                            else:  # position == "below"
                                below_placements[i] = (level, anchor)

                    return above_placements, below_placements

        # If we get here, no solution found within reasonable bounds
        print(
            "Warning: Could not find valid placement within reasonable bounds",
            file=sys.stderr,
        )
        below_placements = {}
        for i, (exact_string, label) in enumerate(annotation_specs, 1):
            if i in node_names:
                below_placements[i] = (2.0 + i, "base west")
        return {}, below_placements

    def _generate_placement_combinations(
        self, num_annotations: int, levels_above: List[float], levels_below: List[float]
    ) -> List[List[Tuple[str, float, str]]]:
        """Generate all possible placement combinations - simple brute force."""
        from itertools import product

        # For each annotation, generate all possible (position, level, anchor) options
        options_per_annotation = []

        for i in range(num_annotations):
            annotation_options = []

            # Below positions (only using below for simplicity)
            for level in levels_below:
                annotation_options.append(
                    ("below", level, "base west")
                )  # extends right
                annotation_options.append(("below", level, "base east"))  # extends left

            # Above positions (if any levels defined above)
            for level in levels_above:
                annotation_options.append(
                    ("above", level, "base west")
                )  # extends right
                annotation_options.append(("above", level, "base east"))  # extends left

            options_per_annotation.append(annotation_options)

        # Generate all combinations - no sorting, just return them in iterator order
        combinations = list(product(*options_per_annotation))
        return combinations

    def _check_placement_validity(
        self,
        combination: List[Tuple[str, float, str]],
        bounding_boxes: Dict[int, Tuple[float, float]],
        node_positions: Dict[int, float],
        page_width_pt: float,
        horizontal_padding_pt: float,
        node_shifts: Dict[int, float],
    ) -> bool:
        """Check if a placement combination is valid (no overlaps, fits in page width)."""
        # Group annotations by position and level for collision detection
        placements_by_level = {}

        for i, (position, level, anchor) in enumerate(combination, 1):
            if node_shifts[i] < 0 and position == "above":
                # Node is below baseline, cannot place annotation above
                return False
            if node_shifts[i] > 0 and position == "below":
                # Node is above baseline, cannot place annotation below
                return False
            if i not in bounding_boxes or i not in node_positions:
                continue

            width_pt, height_pt = bounding_boxes[i]
            node_x = node_positions[i]
            padded_width = width_pt + 1 * horizontal_padding_pt

            # Calculate annotation bounds based on anchor
            if anchor == "base west":  # Left-aligned text extends right from node
                left_bound = node_x
                right_bound = node_x + padded_width
            else:  # "base east" - Right-aligned text extends left from node
                left_bound = node_x - padded_width
                right_bound = node_x

            key = (position, level)
            if key not in placements_by_level:
                placements_by_level[key] = []

            placements_by_level[key].append(
                (i, left_bound, right_bound, anchor, padded_width)
            )

        # print(placements_by_level, file=sys.stderr)

        # Check each level for overlaps and page width constraints
        for (position, level), annotations in placements_by_level.items():
            # Sort annotations by left bound for overlap detection
            annotations.sort(key=lambda x: x[1])  # Sort by left_bound

            # Check for overlaps between adjacent annotations
            for j in range(len(annotations) - 1):
                curr = annotations[j]
                next_ann = annotations[j + 1]

                curr_right = curr[2]  # right_bound
                next_left = next_ann[1]  # left_bound

                if curr_right > next_left:
                    # print(
                    #     f"Debug: Overlap detected - annotation {curr[0]} ends at {curr_right:.2f}pt, annotation {next_ann[0]} starts at {next_left:.2f}pt",
                    #     file=sys.stderr,
                    # )
                    return False

            # Check if any annotation extends beyond page boundaries
            for i, left_bound, right_bound, anchor, width in annotations:
                if left_bound < 20 or right_bound > page_width_pt - 50:
                    print(
                        f"Debug: Annotation {i} extends beyond page bounds: [{left_bound:.2f}, {right_bound:.2f}]pt",
                        file=sys.stderr,
                    )
                    return False
        print("no overlaps within levels", file=sys.stderr)

        # Check for vertical line crossings: text boxes crossing through vertical lines from other levels
        for (position_1, level_1), annotations_1 in placements_by_level.items():
            for (position_2, level_2), annotations_2 in placements_by_level.items():
                # only check same position
                if position_1 != position_2:
                    continue

                # only check different levels
                if level_1 >= level_2:
                    continue

                # Check if any text box from level_1 crosses through vertical lines from level_2
                for ann_1 in annotations_1:
                    ann_1_id, ann_1_left, ann_1_right, ann_1_anchor, ann_1_width = ann_1

                    for ann_2 in annotations_2:
                        ann_2_id, ann_2_left, ann_2_right, ann_2_anchor, ann_2_width = (
                            ann_2
                        )

                        # Get the vertical line position for annotation 2 (its node position)
                        if ann_2_id in node_positions:
                            vertical_line_x = node_positions[ann_2_id]

                            # Check if annotation 1's text box crosses through annotation 2's vertical line
                            # Use 10pt clearance as specified
                            clearance = 5.0
                            if (
                                ann_1_left < vertical_line_x + clearance
                                and ann_1_right > vertical_line_x - clearance
                            ):
                                return False
        print(placements_by_level, file=sys.stderr)
        print(f"Debug: Placement accepted - no overlaps detected", file=sys.stderr)
        return True

    def _generate_tikzpicture_annotations(
        self,
        annotations_above: Dict[int, str],
        annotations_below: Dict[int, str],
        node_names: Dict[int, str],
        above_placements: Dict[int, Tuple[float, str]] = None,
        below_placements: Dict[int, Tuple[float, str]] = None,
    ) -> Tuple[List[str], Dict[str, int]]:
        """Generate tikzpicture code for annotations and return space requirements."""
        tikz_parts = []
        tikz_parts.append("\\begin{tikzpicture}[remember picture, overlay]")

        # Calculate heights with left/right alignment optimization
        above_heights = {}
        below_heights = {}
        above_anchors = {}  # Track which side each annotation goes on
        below_anchors = {}

        # Use placement information if provided, otherwise fall back to old logic
        if above_placements is not None:
            # Use new placement logic for above annotations
            for pos in annotations_above.keys():
                if pos in above_placements:
                    height, anchor = above_placements[pos]
                    above_heights[pos] = height
                    above_anchors[pos] = anchor
        else:
            # Fall back to old placement logic for above annotations
            sorted_above = sorted(annotations_above.keys())
            for i, pos in enumerate(sorted_above):
                if i < len(sorted_above) / 2:
                    # Left side: positions 1, 2 (ascending heights)
                    above_heights[pos] = 2 + i  # 2em, 3em
                    above_anchors[pos] = (
                        "base east"  # Right-aligned text (anchored to east)
                    )
                else:
                    # Right side: positions 3, 4 - reverse order for pyramid shape
                    right_index = len(sorted_above) - 1 - i  # Reverse mapping
                    above_heights[pos] = 2 + right_index  # 3em, 2em (descending)
                    above_anchors[pos] = (
                        "base west"  # Left-aligned text (anchored to west)
                    )

        if below_placements is not None:
            # Use new placement logic for below annotations
            for pos in annotations_below.keys():
                if pos in below_placements:
                    height, anchor = below_placements[pos]
                    below_heights[pos] = height
                    below_anchors[pos] = anchor
        else:
            # Fall back to old placement logic for below annotations
            sorted_below = sorted(annotations_below.keys())
            for i, pos in enumerate(sorted_below):
                if i < len(sorted_below) / 2:
                    # Left side (ascending heights)
                    below_heights[pos] = 2 + i  # 2em, 3em
                    below_anchors[pos] = "base east"  # Right-aligned text
                else:
                    # Right side - reverse order for pyramid shape
                    right_index = len(sorted_below) - 1 - i  # Reverse mapping
                    below_heights[pos] = 2 + right_index  # 3em, 2em (descending)
                    below_anchors[pos] = "base west"  # Left-aligned text

        # Calculate space requirements in pt
        max_above_height = max(above_heights.values()) if above_heights else 0
        max_below_height = max(below_heights.values()) if below_heights else 0

        # Add buffer for below annotations since they extend down from equation baseline
        # The annotation extends down by the height value, plus some padding (in pt)
        adjusted_below_height = max_below_height + 10 if max_below_height > 0 else 0

        space_requirements = {"above": max_above_height, "below": adjusted_below_height}

        # Generate above annotations
        for pos, text in annotations_above.items():
            if pos not in node_names:
                continue
            node_name = node_names[pos]
            height = above_heights[pos]
            anchor = above_anchors[pos]

            # Determine xshift based on anchor - shift outwards more for space saving
            xshift = "-0.2em" if anchor == "base east" else "0.2em"

            # Convert height from pt to LaTeX output (still using pt)
            reduced_height = height - 5.0  # Reduce by 5pt instead of 0.5em
            yshift = "3pt"  # Shift down slightly like bottom annotations

            tikz_parts.append(f"    %above annotation {pos}")
            tikz_parts.append(
                f"\path[fill=ncorange!25,draw=none,line width=0pt] ({node_name}.north west) -- ({node_name}.north east) -- ([yshift=13pt]{node_name}.base east) -- ([yshift=13pt]{node_name}.base west) -- cycle;"
            )

            tikz_parts.append(
                f"    \\draw[ncorange, line width=0.4mm] ([yshift=13pt]{node_name}.base west) -- ([yshift=13pt]{node_name}.base east);"
            )
            tikz_parts.append(
                f"    \\draw[ncorange,] ([yshift=13pt]{node_name}.base) -- ([yshift={height}pt]{node_name}.base);"
            )
            tikz_parts.append(
                f"    \\node[above={reduced_height}pt of {node_name}.base,anchor={anchor},inner sep=0,outer sep=0,xshift={xshift},yshift={yshift},text=ncorange] {{\\scriptsize {text}}};"
            )
            tikz_parts.append("")

        # Generate below annotations
        for pos, text in annotations_below.items():
            if pos not in node_names:
                continue
            node_name = node_names[pos]
            height = below_heights[pos]
            anchor = below_anchors[pos]

            # Determine xshift based on anchor
            xshift = "-2pt" if anchor == "base east" else "2pt"

            tikz_parts.append(f"    %below annotation {pos}")
            tikz_parts.append(
                f"\path[fill=ncorange!25,draw=none,line width=0pt] ({node_name}.south west) -- ({node_name}.south east) -- ([yshift=-8pt]{node_name}.base east) -- ([yshift=-8pt]{node_name}.base west) -- cycle;"
            )

            # Draw the annotation line and connecting line
            tikz_parts.append(
                f"    \\draw[ncorange, line width=0.4mm] ([yshift=-8pt]{node_name}.base west) -- ([yshift=-8pt]{node_name}.base east);"
            )
            tikz_parts.append(
                f"    \\draw[ncorange,] ([yshift=-8pt]{node_name}.base) -- ([yshift=-{height}pt]{node_name}.base);"
            )
            tikz_parts.append(
                f"    \\node[below={height}pt of {node_name}.base,anchor={anchor},inner sep=0,outer sep=0,xshift={xshift},yshift=-3pt,text=ncorange] {{\\scriptsize {text}}};"
            )
            tikz_parts.append("")

        tikz_parts.append("\\end{tikzpicture}")
        return tikz_parts, space_requirements

    def _format_table(self, content: str) -> str:
        """Format markdown table content."""
        lines = [line.strip() for line in content.split("\n") if line.strip()]

        if len(lines) < 2:
            return content

        # Parse table rows
        table_rows = []
        separator_found = False

        for i, line in enumerate(lines):
            # Skip separator line (|---|---|)
            if re.match(r"^\s*\|?[\s\-\|:]+\|?\s*$", line):
                separator_found = True
                continue

            # Parse table row
            if "|" in line:
                # Remove leading/trailing pipes and split
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                # Apply italic formatting to each cell
                cells = [
                    re.sub(r"\*([^*]+)\*", r"\\textit{\1}", cell) for cell in cells
                ]
                # Handle footnote references in cells
                cells = [
                    re.sub(r"\[\^(\d+)\]", r"\\footnotemark[\1]", cell)
                    for cell in cells
                ]
                table_rows.append(cells)

        if not table_rows:
            return content

        # Determine number of columns
        max_cols = max(len(row) for row in table_rows)

        # Build LaTeX table
        latex_lines = []
        latex_lines.append("\\begin{tabular}{" + "l" * max_cols + "}")

        for i, row in enumerate(table_rows):
            # Pad row to max columns
            padded_row = row + [""] * (max_cols - len(row))

            if i == 0:
                # Add blue line above header matching header background color
                latex_lines.append(
                    "\\arrayrulecolor{ncblue!20}\\specialrule{1.33pt}{0pt}{0pt}\\arrayrulecolor{black}"
                )
                # Header row - blue background and bold text
                formatted_cells = [f"\\textbf{{{cell}}}" for cell in padded_row]
                latex_lines.append(
                    "\\rowcolor{ncblue!20}" + " & ".join(formatted_cells) + " \\\\"
                )
                # Add thinner blue line under header
                latex_lines.append(
                    "\\arrayrulecolor{ncblue}\\specialrule{1.33pt}{0pt}{0pt}\\arrayrulecolor{black}"
                )
            else:
                # Data rows with alternating shading pattern (2 unshaded, 2 shaded)
                # Pattern: rows 1,2 = unshaded, rows 3,4 = shaded, rows 5,6 = unshaded, etc.
                cycle_position = (i - 1) % 4  # 0,1,2,3 for rows 1,2,3,4
                if cycle_position >= 2:  # rows 3,4 in each cycle get light blue shading
                    latex_lines.append(
                        "\\rowcolor{ncblue!10}" + " & ".join(padded_row) + " \\\\"
                    )
                else:
                    latex_lines.append(" & ".join(padded_row) + " \\\\")

        latex_lines.append("\\end{tabular}")
        return "\n".join(latex_lines)

    def _format_list(self, content: str) -> str:
        """Format list content with optional heading and nested items."""
        lines = content.split("\n")
        list_lines = []

        # Check if first line is a heading (no dash)
        first_line = lines[0].strip()
        start_idx = 0

        if first_line and not first_line.startswith("-"):
            # First line is a heading
            # Handle italic formatting in heading
            first_line = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", first_line)
            # Handle icon syntax in heading
            first_line = self._process_heading_icons(first_line)
            list_lines.append(f"\\textbf{{\\textcolor{{navyblue}}{{{first_line}}}}}")
            start_idx = 1

        # Process the list items
        list_lines.append("\\begin{itemize}")

        i = start_idx
        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            if line.startswith("-"):
                item_text = line[1:].strip()
                # Handle footnote references
                item_text = re.sub(
                    r"\[\^(\d+)\]",
                    r"\\footnotemark[\1]",
                    item_text,
                )
                # Handle italic formatting: *text* -> \textit{text}
                item_text = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", item_text)
                list_lines.append(f"\\item {item_text}")

                # Check if next lines are sub-items (indented dashes)
                sub_items = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if not next_line:
                        j += 1
                        continue
                    # Check if it's an indented dash (starts with spaces/tabs followed by dash)
                    if lines[j].startswith(("  -", "\t-", "    -")):
                        sub_item_text = next_line[1:].strip()
                        sub_item_text = re.sub(
                            r"\[\^(\d+)\]",
                            r"\\footnotemark[\1]",
                            sub_item_text,
                        )
                        # Handle italic formatting: *text* -> \textit{text}
                        sub_item_text = re.sub(
                            r"\*([^*]+)\*", r"\\textit{\1}", sub_item_text
                        )
                        sub_items.append(sub_item_text)
                        j += 1
                    else:
                        break

                # Add sub-items if any
                if sub_items:
                    list_lines.append("\\begin{itemize}")
                    for sub_item in sub_items:
                        list_lines.append(f"\\item {sub_item}")
                    list_lines.append("\\end{itemize}")

                i = j
            else:
                i += 1

        list_lines.append("\\end{itemize}")
        list_lines.append("\\vspace{0.5em}")
        return "\n".join(list_lines)

    def _format_image(self, block: Block, has_columns: bool = False) -> str:
        """Format image block with auto-scaling and plain grey caption."""
        image_file = block.content
        caption = block.metadata.get("caption", "")

        # optional scaling of image via filename pattern imagefile.ext*scale
        parts = image_file.split("*")
        scale_factor = 1.0
        if len(parts) == 2:
            image_file = parts[0]
            scale_factor = float(parts[1])

        # Use different base scaling for single-column vs two-column layouts
        if has_columns:
            # Two-column layout: use linewidth (fits within column)
            width_limit = 1.0
            height_limit = 0.6
            width_setting = "width=\\linewidth"
            height_setting = "height=0.6\\textheight"
        else:
            # Single-column layout: use larger scaling to fill more space
            width_limit = 1.5
            height_limit = 0.7

        # calculate final scaling
        width_setting = f"width={width_limit * scale_factor}\\linewidth"
        height_setting = f"height={height_limit * scale_factor}\\textheight"

        return f"""\\begin{{center}}
\\includegraphics[{width_setting},{height_setting},keepaspectratio]{{{image_file}}}
\\end{{center}}
\\vspace{{-1em}}
\\textcolor{{gray}}{{{caption}}}"""

    def _format_text(self, content: str) -> str:
        """Format text content."""
        # Handle footnote references
        content = re.sub(r"\[\^(\d+)\]", r"\\footnotemark[\1]", content)
        # Handle italic formatting: *text* -> \textit{text}
        content = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", content)
        # Always add empty line after text blocks to preserve paragraph spacing
        return content + "\n"

    def _format_fake_footnotes(self, footnotes: List[Block]) -> str:
        """Format fake footnotes with starred footnotes first, then numbered ones with pipe separation."""
        if not footnotes:
            return ""

        # Separate starred footnotes from numbered ones
        starred_footnotes = []
        numbered_footnotes = []

        for footnote in footnotes:
            if footnote.metadata.get("number") == "*":
                starred_footnotes.append(footnote)
            else:
                numbered_footnotes.append(footnote)

        # Sort numbered footnotes by number
        numbered_footnotes.sort(key=lambda x: int(x.metadata.get("number", "0")))

        footnote_parts = []

        # Add starred footnotes first (no markers, just the content in gray)
        for footnote in starred_footnotes:
            # Apply italic formatting to footnote content
            content = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", footnote.content)
            footnote_parts.append(f"\\textcolor{{gray}}{{{content}}}")

        # Add numbered footnotes with orange markers and pipes, gray text
        for footnote in numbered_footnotes:
            number = footnote.metadata.get("number", "")
            # Apply italic formatting to footnote content
            content = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", footnote.content)
            footnote_parts.append(
                f"\\textcolor{{orange}}{{{number}}}\\textcolor{{orange}}{{|}}~\\textcolor{{gray}}{{{content}}}"
            )

        return " ".join(footnote_parts)

    def _process_heading_icons(self, heading_text: str) -> str:
        """Process heading text to replace :icon_name: with rendered SVG icons."""
        # First handle special icon mappings
        heading_text = heading_text.replace(":email:", ":envelope:")
        heading_text = heading_text.replace(":web:", ":globe:")

        # Pattern to match :icon_name: syntax
        icon_pattern = r":([a-zA-Z0-9_-]+):"

        def replace_icon(match):
            icon_name = match.group(1)
            return self._generate_svg_icon(icon_name)

        return re.sub(icon_pattern, replace_icon, heading_text)

    def _generate_svg_icon(self, icon_name: str) -> str:
        """Generate LaTeX code for an SVG icon with colored circle background."""
        import os

        # Get the directory where render.py is located
        render_dir = os.path.dirname(os.path.abspath(__file__))
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
        if not os.path.exists(local_pdf_path) or self._source_is_newer(
            source_icon_path, local_pdf_path
        ):
            try:
                self._convert_svg_to_pdf(
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

    def _source_is_newer(self, source_file: str, target_file: str) -> bool:
        """Check if source file is newer than target file."""
        import os

        try:
            source_stat = os.stat(source_file)
            target_stat = os.stat(target_file)
            return source_stat.st_mtime > target_stat.st_mtime
        except OSError:
            return True  # If target doesn't exist or error, consider source newer

    def _convert_svg_to_pdf(self, svg_path: str, pdf_path: str, color: str) -> None:
        """Convert SVG to PDF with specified color using cairosvg."""
        try:
            import cairosvg
            import xml.etree.ElementTree as ET

            # Read and modify SVG to apply color
            with open(svg_path, "r", encoding="utf-8") as f:
                svg_content = f.read()

            # Parse SVG and apply color
            svg_content = self._apply_color_to_svg(svg_content, color)

            # Convert to PDF
            cairosvg.svg2pdf(bytestring=svg_content.encode("utf-8"), write_to=pdf_path)

        except ImportError:
            # Fallback to reportlab if cairosvg not available
            self._convert_svg_to_pdf_reportlab(svg_path, pdf_path, color)

    def _apply_color_to_svg(self, svg_content: str, color: str) -> str:
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

    def _convert_svg_to_pdf_reportlab(
        self, svg_path: str, pdf_path: str, color: str
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
