import re
import sys
import os
from typing import List, Dict, Tuple
from tqdm import tqdm

from .models import Block, BlockType
from . import figures


class MarkdownBeamerParser:
    def __init__(self, input_filename=None, output_dir="."):
        self.blocks = []
        self.footnotes = {}
        self.current_slide_blocks = []
        self.slides = []
        self.figure_counter = 0
        self.input_filename = input_filename
        self.output_dir = output_dir
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

                self.current_slide_blocks.append(Block(BlockType.TITLE_PAGE, title))
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

            # Check for column section break
            if line == "---":
                if current_block_lines:
                    self._process_block_lines(current_block_lines)
                    current_block_lines = []
                self.current_slide_blocks.append(Block(BlockType.COLUMN_SECTION_BREAK, ""))
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
            figures.generate_figure_file(
                figure_info["code"],
                figure_info["block_type"],
                figure_info["filename"],
                has_columns,
                self.output_dir,
            )


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