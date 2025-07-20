import re
from typing import List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum
import click
import subprocess
import os
import tempfile


class BlockType(Enum):
    SECTION = "section"
    SLIDE_TITLE = "slide_title"
    EQUATION = "equation"
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
                image_match = re.match(r"^::: ([^:]+): (.+)$", line)
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
        return self.slides

    def _parse_fenced_code_block(self, lines: List[str], start_i: int) -> Tuple[Block, int]:
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
            raise ValueError(f"Unclosed fenced code block starting at line {start_i + 1}")
        
        # Generate the figure
        code = "\n".join(code_lines)
        figure_filename = self._generate_figure(code, block_type, caption)
        
        # Create image block pointing to generated figure
        metadata = {"caption": caption, "generated": True}
        image_block = Block(BlockType.IMAGE, figure_filename, metadata)
        
        return image_block, i + 1

    def _generate_figure(self, code: str, block_type: BlockType, caption: str) -> str:
        """Generate a matplotlib figure from Python code and return filename."""
        self.figure_counter += 1
        
        # Determine base filename
        if self.input_filename:
            base_name = os.path.splitext(os.path.basename(self.input_filename))[0]
        else:
            base_name = "figure"
        
        figure_filename = f"{base_name}.figure{self.figure_counter}.pdf"
        
        # Create Python script for subplot execution
        python_script = self._create_matplotlib_script(code, block_type, figure_filename)
        
        # Write script to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(python_script)
            temp_script_path = temp_file.name
        
        try:
            # Execute Python script using subprocess
            result = subprocess.run(
                ['python', temp_script_path],
                capture_output=True,
                text=True,
                cwd=os.getcwd()
            )
            
            if result.returncode != 0:
                raise RuntimeError(
                    f"Error generating figure {self.figure_counter} ({block_type.value}):\n"
                    f"Code:\n{code}\n\n"
                    f"Error output:\n{result.stderr}"
                )
                
        finally:
            # Clean up temporary script
            try:
                os.unlink(temp_script_path)
            except OSError:
                pass
        
        return figure_filename

    def _create_matplotlib_script(self, user_code: str, block_type: BlockType, output_filename: str) -> str:
        """Create complete Python script for matplotlib figure generation."""
        
        # Configure schematic vs plot styling
        if block_type == BlockType.SCHEMATIC:
            style_config = """
# Configure for schematic (no tick marks, thick axes in navy blue)
ncblue = '#0A2D64'  # Navy blue color from beamer theme
ax = plt.gca()
ax.spines['left'].set_linewidth(3)
ax.spines['left'].set_color(ncblue)
ax.spines['bottom'].set_linewidth(3)
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
            style_config = """
# Configure for plot (with tick marks, thick axes in navy blue)
ncblue = '#0A2D64'  # Navy blue color from beamer theme
ax = plt.gca()
ax.spines['left'].set_linewidth(3)
ax.spines['left'].set_color(ncblue)
ax.spines['bottom'].set_linewidth(3)
ax.spines['bottom'].set_color(ncblue)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

# Set axis label colors to navy blue
ax.xaxis.label.set_color(ncblue)
ax.yaxis.label.set_color(ncblue)

# Keep tick marks for plots with navy blue color
plt.tick_params(axis='both', which='major', labelsize=18, width=2, length=6, colors=ncblue)
"""
        
        script = f'''
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend

# Configure matplotlib for 4:3 aspect ratio
plt.figure(figsize=(8, 6))  # 4:3 aspect ratio, good for both single/two-column

# Set font to match beamer (Fira Sans if available, fallback to sans-serif)
try:
    plt.rcParams['font.family'] = ['Fira Sans', 'DejaVu Sans', 'sans-serif']
except:
    plt.rcParams['font.family'] = 'sans-serif'

plt.rcParams['font.size'] = 16
plt.rcParams['axes.labelsize'] = 30  # About 3x larger for presentations
plt.rcParams['xtick.labelsize'] = 15
plt.rcParams['ytick.labelsize'] = 15
plt.rcParams['lines.linewidth'] = 3  # Doubled default line width
plt.rcParams['lines.markersize'] = 12  # Doubled default marker size

# User code
{user_code}

{style_config}

# Save figure
plt.tight_layout()
plt.savefig('{output_filename}', format='pdf', bbox_inches='tight', dpi=300)
plt.close()
'''
        return script

    def _process_block_lines(self, lines: List[str]):
        """Process a block of lines to determine its type and content."""
        if not lines:
            return

        content = "\n".join(lines)

        # Check for annotated equation (starts with $$ and has content after)
        if lines[0].startswith("$$") and len(lines) > 1:
            # Find where equation ends
            equation_end = -1
            for i, line in enumerate(lines):
                if line.endswith("$$"):
                    equation_end = i
                    break

            if equation_end >= 0:
                equation_lines = lines[: equation_end + 1]
                annotation_lines = lines[equation_end + 1 :]

                if annotation_lines:  # Has annotations
                    self.current_slide_blocks.append(
                        Block(
                            BlockType.ANNOTATED_EQUATION,
                            content,
                            {
                                "equation": "\n".join(equation_lines),
                                "annotations": "\n".join(annotation_lines),
                            },
                        )
                    )
                    return

        # Check for simple equation block
        if lines[0].startswith("$$") and lines[-1].endswith("$$") and len(lines) == 1:
            equation = lines[0]
            self.current_slide_blocks.append(Block(BlockType.EQUATION, equation))
            return

        # Check for multi-line equation block (only equation, no annotations)
        if lines[0].startswith("$$") and lines[-1].endswith("$$"):
            equation = "\n".join(lines)
            self.current_slide_blocks.append(Block(BlockType.EQUATION, equation))
            return

        # Check for table (lines with --- separators)
        if any("---" in line for line in lines):
            self.current_slide_blocks.append(Block(BlockType.TABLE, content))
            return

        # Check for list (lines starting with - or numbered, or heading followed by dashes)
        has_dashes = any(line.strip().startswith("-") for line in lines)
        has_heading = (
            len(lines) > 1 and not lines[0].strip().startswith("-") and has_dashes
        )
        is_all_dashes = all(
            line.strip().startswith("-") or not line.strip()
            for line in lines
            if line.strip()
        )

        if has_dashes and (is_all_dashes or has_heading):
            self.current_slide_blocks.append(Block(BlockType.LIST, content))
            return

        # Default to text block
        self.current_slide_blocks.append(Block(BlockType.TEXT, content))

    def _finish_current_slide(self):
        """Finish current slide and add to slides list."""
        if self.current_slide_blocks:
            self.slides.append(self.current_slide_blocks.copy())
            self.current_slide_blocks = []


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
\setbeamertemplate{itemize item}{\textendash}
\setbeamertemplate{itemize subitem}{\textendash}
\setbeamertemplate{itemize subsubitem}{\textendash}
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
  % make sure all tikz node labels only exist on the same frame
  \tikzset{tikzmark prefix=frame\insertframenumber}
}
\usepackage{amsmath}
\usepackage{tikz}
\usetikzlibrary{tikzmark,calc,positioning}


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
        self, blocks: List[Block], slide_parts: List[str], in_columns: bool
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
                slide_parts.append(self._format_block(block))
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
                "\\hspace*{-2em}" + self._format_fake_footnotes(footnotes)
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
        in_columns = self._process_slide_blocks(blocks, slide_parts, in_columns)

        # Finalize slide
        self._finalize_slide(slide_parts, footnotes)

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
        in_columns = self._process_slide_blocks(blocks, slide_parts, in_columns)

        # Finalize slide
        self._finalize_slide(slide_parts, footnotes)

        # Reset frametitle color back to original blue
        slide_parts.append("\\setbeamercolor{frametitle}{bg=ncblue, fg=white}")

        return "\n".join(slide_parts)

    def _format_block(self, block: Block) -> str:
        """Format a single block based on its type."""
        if block.type == BlockType.EQUATION:
            return block.content
        elif block.type == BlockType.ANNOTATED_EQUATION:
            return self._format_annotated_equation(block)
        elif block.type == BlockType.TABLE:
            return self._format_table(block.content)
        elif block.type == BlockType.LIST:
            return self._format_list(block.content)
        elif block.type == BlockType.IMAGE:
            return self._format_image(block)
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

        # Parse annotations
        annotation_lines = annotations.split("\n")

        # Find the dash marker line (contains only spaces and dashes)
        dash_line = None
        annotation_specs = []

        for line in annotation_lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Check if this is the dash marker line (preserve original spacing)
            if re.match(r"^[\s\-]+$", line):
                dash_line = line  # Keep original line with spaces
            # Check if this is an annotation spec (N^ or Nv format)
            elif re.match(r"^\d+[v^]", line_stripped):
                annotation_specs.append(line_stripped)

        if not dash_line:
            # Fallback to old behavior if no dash line found
            return self._format_annotated_equation_old(block)

        # Parse the equation (remove $$ markers)
        equation_content = equation.strip()
        if equation_content.startswith("$$") and equation_content.endswith("$$"):
            equation_content = equation_content[2:-2].strip()

        # Parse dash markers and create tikzmarknode-wrapped equation
        annotated_equation, node_names = self._create_tikzmarknode_equation(
            equation_content, dash_line
        )

        # Parse annotation specifications
        annotations_above, annotations_below = self._parse_annotation_specs(
            annotation_specs
        )

        # Generate tikzpicture with annotations
        if annotations_above or annotations_below:
            tikz_code, space_requirements = self._generate_tikzpicture_annotations(
                annotations_above, annotations_below, node_names
            )

            # Calculate required spacing
            above_space = space_requirements["above"]
            below_space = space_requirements["below"]

            # Generate the complete LaTeX output with proper spacing
            latex_parts = []

            # Add space above for annotations
            if above_space > 0:
                latex_parts.append(f"\\vspace{{{above_space}em}}")

            # Add the equation
            latex_parts.append(f"$${annotated_equation}$$")
            latex_parts.append("")

            # Add the tikzpicture
            latex_parts.extend(tikz_code)

            # Add space below for annotations
            latex_parts.append("\n")
            if below_space > 0:
                latex_parts.append(f"\\vspace{{{below_space}em}}")
        else:
            # No annotations, just the equation
            latex_parts = []
            latex_parts.append(f"$${annotated_equation}$$")

        return "\n".join(latex_parts)

    def _create_tikzmarknode_equation(
        self, equation_content: str, dash_line: str
    ) -> Tuple[str, Dict[int, str]]:
        """Create equation with tikzmarknode wrappers based on dash positions."""
        # Find dash segments in the dash line
        dash_segments = []
        in_dash = False
        start_pos = None

        for i, char in enumerate(dash_line):
            if char == "-" and not in_dash:
                start_pos = i
                in_dash = True
            elif char != "-" and in_dash:
                if start_pos is not None:
                    dash_segments.append((start_pos, i - 1))
                in_dash = False

        # Handle case where dash continues to end of line
        if in_dash and start_pos is not None:
            dash_segments.append((start_pos, len(dash_line) - 1))

        # Build the annotated equation
        result = ""
        last_end = 0
        node_names = {}  # Map annotation position to node name

        for i, (start, end) in enumerate(dash_segments):
            # Apply 2-position offset to align with intended segments
            adj_start = max(0, start - 2)
            adj_end = max(0, end - 2)

            # Add content before this segment
            if adj_start > last_end:
                result += equation_content[last_end:adj_start]

            # Extract the segment content, ensuring bounds
            if adj_end + 1 <= len(equation_content):
                segment_content = equation_content[adj_start : adj_end + 1]
            else:
                segment_content = equation_content[adj_start:]

            # Generate unique node name
            self.node_counter += 1
            node_name = f"node{self.node_counter}"
            node_names[i + 1] = node_name  # Position 1, 2, 3, 4...

            # Wrap in tikzmarknode
            result += f"\\tikzmarknode{{{node_name}}}{{{segment_content}}}"

            last_end = adj_end + 1

        # Add remaining content
        if last_end < len(equation_content):
            result += equation_content[last_end:]

        return result, node_names

    def _parse_annotation_specs(
        self, annotation_specs: List[str]
    ) -> Tuple[Dict[int, str], Dict[int, str]]:
        """Parse annotation specifications into above and below dictionaries."""
        annotations_above = {}
        annotations_below = {}

        for spec in annotation_specs:
            # Parse format: "N^" or "Nv" followed by text
            match = re.match(r"^(\d+)([v^])\s*(.*)$", spec)
            if match:
                position = int(match.group(1))
                direction = match.group(2)
                text = match.group(3).strip()

                if direction == "^":
                    annotations_above[position] = text
                elif direction == "v":
                    annotations_below[position] = text

        return annotations_above, annotations_below

    def _generate_tikzpicture_annotations(
        self,
        annotations_above: Dict[int, str],
        annotations_below: Dict[int, str],
        node_names: Dict[int, str],
    ) -> Tuple[List[str], Dict[str, int]]:
        """Generate tikzpicture code for annotations and return space requirements."""
        tikz_parts = []
        tikz_parts.append("\\begin{tikzpicture}[remember picture, overlay]")

        # Calculate heights with left/right alignment optimization
        above_heights = {}
        below_heights = {}
        above_anchors = {}  # Track which side each annotation goes on
        below_anchors = {}

        # Assign heights for above annotations with left/right pairing
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
                # Position 3 gets height of position 2, position 4 gets height of position 1
                right_index = len(sorted_above) - 1 - i  # Reverse mapping
                above_heights[pos] = 2 + right_index  # 3em, 2em (descending)
                above_anchors[pos] = "base west"  # Left-aligned text (anchored to west)

        # Assign heights for below annotations with left/right pairing
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

        # Calculate space requirements
        max_above_height = max(above_heights.values()) if above_heights else 0
        max_below_height = max(below_heights.values()) if below_heights else 0

        # Add buffer for below annotations since they extend down from equation baseline
        # The annotation extends down by the height value, plus some padding
        adjusted_below_height = max_below_height + 1 if max_below_height > 0 else 0

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

            # Reduce height by 0.5em and adjust yshift to align text anchor with line end
            reduced_height = height - 0.5
            yshift = "0.3em"  # Shift down slightly like bottom annotations

            tikz_parts.append(f"    %above annotation {pos}")
            tikz_parts.append(
                f"    \\draw[ncorange, line width=0.4mm] ([yshift=1em]{node_name}.base west) -- ([yshift=1em]{node_name}.base east);"
            )
            tikz_parts.append(
                f"    \\draw[ncorange,] ([yshift=1em]{node_name}.base) -- ([yshift={height}em]{node_name}.base);"
            )
            tikz_parts.append(
                f"    \\node[above={reduced_height}em of {node_name}.base,anchor={anchor},inner sep=0,xshift={xshift},yshift={yshift},text=ncorange] {{{text}}};"
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
            xshift = "-0.2em" if anchor == "base east" else "0.2em"

            tikz_parts.append(f"    %below annotation {pos}")
            tikz_parts.append(
                f"    \\draw[ncorange, line width=0.4mm] ([yshift=-.5em]{node_name}.base west) -- ([yshift=-.5em]{node_name}.base east);"
            )
            tikz_parts.append(
                f"    \\draw[ncorange,] ([yshift=-.5em]{node_name}.base) -- ([yshift=-{height}em]{node_name}.base);"
            )
            tikz_parts.append(
                f"    \\node[below={height}em of {node_name}.base,anchor={anchor},inner sep=0,xshift={xshift},yshift=-0.3em,text=ncorange] {{{text}}};"
            )
            tikz_parts.append("")

        tikz_parts.append("\\end{tikzpicture}")
        return tikz_parts, space_requirements

    def _format_annotated_equation_old(self, block: Block) -> str:
        """Fallback method for old annotation format."""
        equation = block.metadata["equation"]
        annotations = block.metadata["annotations"]

        # Parse annotations
        annotation_lines = annotations.split("\n")
        latex_parts = []

        latex_parts.append("\\begin{columns}")
        latex_parts.append("\\begin{column}{0.6\\textwidth}")
        latex_parts.append(equation)
        latex_parts.append("\\end{column}")
        latex_parts.append("\\begin{column}{0.4\\textwidth}")
        latex_parts.append("\\footnotesize")

        # Process annotation lines
        for line in annotation_lines:
            line = line.strip()
            if not line:
                continue

            # Handle numbered annotations (1^, 2^, etc.)
            if re.match(r"^\d+\^", line):
                num = line[0]
                text = line[2:].strip()
                latex_parts.append(f"\\textbf{{{num}.}} {text}\\\\")
            # Handle value annotations (3v, 4v, etc.)
            elif re.match(r"^\d+v", line):
                num = line[0]
                text = line[2:].strip()
                latex_parts.append(f"\\textit{{{num}.}} {text}\\\\")
            # Handle table-like annotations with ---
            elif "---" in line:
                parts = line.split("---")
                if len(parts) >= 2:
                    headers = parts[0].strip().split()
                    values = parts[1].strip().split()

                    latex_parts.append("\\begin{tabular}{ll}")
                    for i, (header, value) in enumerate(zip(headers, values)):
                        latex_parts.append(f"{header} & {value} \\\\")
                    latex_parts.append("\\end{tabular}")
            else:
                latex_parts.append(line + "\\\\")

        latex_parts.append("\\end{column}")
        latex_parts.append("\\end{columns}")

        return "\n".join(latex_parts)

    def _format_table(self, content: str) -> str:
        """Format table content."""
        lines = content.split("\n")
        table_lines = []

        for line in lines:
            if "---" in line:
                # Parse table structure
                parts = line.split("---")
                if len(parts) >= 2:
                    headers = parts[0].strip().split()
                    values = parts[1].strip().split()

                    table_lines.append("\\begin{tabular}{|" + "c|" * len(headers) + "}")
                    table_lines.append("\\hline")
                    table_lines.append(" & ".join(headers) + " \\\\")
                    table_lines.append("\\hline")
                    table_lines.append(" & ".join(values) + " \\\\")
                    table_lines.append("\\hline")
                    table_lines.append("\\end{tabular}")
            elif line.strip() and not line.startswith(
                ("1^", "2^", "3^", "4^", "3v", "4v")
            ):
                # Handle annotation lines
                if line.startswith(("1^", "2^", "3^", "4^")):
                    table_lines.append(f"\\footnotesize {line[2:].strip()}")
                elif line.startswith(("3v", "4v")):
                    table_lines.append(f"\\footnotesize {line[2:].strip()}")

        return "\n".join(table_lines)

    def _format_list(self, content: str) -> str:
        """Format list content with optional heading and nested items."""
        lines = content.split("\n")
        list_lines = []

        # Check if first line is a heading (no dash)
        first_line = lines[0].strip()
        start_idx = 0

        if first_line and not first_line.startswith("-"):
            # First line is a heading
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

    def _format_image(self, block: Block) -> str:
        """Format image block with auto-scaling and plain grey caption."""
        image_file = block.content
        caption = block.metadata.get("caption", "")

        return f"""\\begin{{center}}
\\includegraphics[width=\\linewidth,height=0.6\\textheight,keepaspectratio]{{{image_file}}}
\\end{{center}}
\\vspace{{-1em}}
\\textcolor{{gray}}{{{caption}}}"""

    def _format_text(self, content: str) -> str:
        """Format text content."""
        # Handle footnote references
        content = re.sub(r"\[\^(\d+)\]", r"\\footnotemark[\1]", content)
        return content

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
            footnote_parts.append(f"\\textcolor{{gray}}{{{footnote.content}}}")

        # Add numbered footnotes with orange markers and pipes, gray text
        for footnote in numbered_footnotes:
            number = footnote.metadata.get("number", "")
            footnote_parts.append(
                f"\\textcolor{{orange}}{{{number}}} \\textcolor{{orange}}{{|}} \\textcolor{{gray}}{{{footnote.content}}}"
            )

        return " ".join(footnote_parts)


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

    generator = BeamerGenerator()
    latex_output = generator.generate_beamer(slides, "My Presentation")

    print(latex_output)


if __name__ == "__main__":
    main()
