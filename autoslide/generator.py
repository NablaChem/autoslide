"""
BeamerGenerator class for autoslide.

This module contains the main BeamerGenerator class that orchestrates slide generation
by delegating formatting tasks to specialized modules and providing caching functionality.
"""

import re
import os
import sys
import json
import hashlib
import tempfile
import subprocess
import shutil
from typing import List, Dict, Tuple

from .models import Block, BlockType
from . import document, text, tables, lists, images, icons, equations


class BeamerGenerator:
    def __init__(self, output_dir=".", no_cache=False):
        self.node_counter = 0
        self.output_dir = output_dir
        self.cache_file = os.path.join(output_dir, ".autoslide.cache")
        self._slide_cache = None
        self.no_cache = no_cache

    def _load_cache(self) -> Dict[str, str]:
        """Load slide cache from disk. Returns empty dict if cache doesn't exist or is corrupted."""
        if self._slide_cache is not None:
            return self._slide_cache

        self._slide_cache = {}

        # If no_cache is enabled, return empty cache (don't read from file)
        if self.no_cache:
            return self._slide_cache

        if not os.path.exists(self.cache_file):
            return self._slide_cache

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        self._slide_cache[entry["hash"]] = entry["latex_source"]
        except (json.JSONDecodeError, KeyError, OSError):
            # Corrupted cache - drop everything and start fresh
            self._slide_cache = {}

        return self._slide_cache

    def _save_to_cache(self, cache_hash: str, latex_source: str) -> None:
        """Save a cache entry to disk."""
        try:
            with open(self.cache_file, "a", encoding="utf-8") as f:
                entry = {"hash": cache_hash, "latex_source": latex_source}
                f.write(json.dumps(entry) + "\n")
            # Update in-memory cache
            if self._slide_cache is None:
                self._slide_cache = {}
            self._slide_cache[cache_hash] = latex_source
        except OSError:
            # Ignore write errors - caching is best effort
            pass

    def _hash_blocks(self, blocks: List[Block]) -> str:
        """Generate a deterministic hash for a list of blocks."""
        # Convert blocks to a deterministic JSON representation
        block_data = []
        for block in blocks:
            block_dict = {
                "type": block.type.value,
                "content": block.content,
                "metadata": block.metadata or {},
            }
            block_data.append(block_dict)

        # Sort metadata keys for deterministic output
        def sort_dict(obj):
            if isinstance(obj, dict):
                return {k: sort_dict(obj[k]) for k in sorted(obj.keys())}
            return obj

        sorted_data = [sort_dict(block) for block in block_data]
        json_str = json.dumps(sorted_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    def generate_beamer(
        self, slides: List[List[Block]], title: str = "Presentation"
    ) -> str:
        """Generate LaTeX beamer code from parsed slides."""
        latex_parts = []

        # Document header
        latex_parts.append(document.generate_header(title))

        # Process each slide
        for slide in slides:
            slide_latex = self._generate_slide(slide)
            if slide_latex:  # Only add non-empty slides
                latex_parts.append(slide_latex)

        # Document footer
        latex_parts.append(document.generate_footer())

        return "\n".join(latex_parts)

    def _split_blocks_into_sections(self, blocks: List[Block]) -> List[List[Block]]:
        """Split blocks into sections separated by COLUMN_SECTION_BREAK."""
        sections = []
        current_section = []

        for block in blocks:
            if block.type == BlockType.COLUMN_SECTION_BREAK:
                # End current section and start new one
                sections.append(current_section)
                current_section = []
            else:
                current_section.append(block)

        # Add final section
        sections.append(current_section)

        return sections

    def _section_has_columns(self, section_blocks: List[Block]) -> bool:
        """Check if a section has column breaks."""
        return any(block.type == BlockType.COLUMN_BREAK for block in section_blocks)

    def _process_slide_blocks(
        self,
        blocks: List[Block],
        slide_parts: List[str],
        in_columns: bool,
        has_columns: bool = False,
    ) -> bool:
        """Process blocks for slide content with section-aware column handling."""
        sections = self._split_blocks_into_sections(blocks)

        for i, section in enumerate(sections):
            # Skip empty sections
            if not section:
                continue

            section_has_columns = self._section_has_columns(section)

            # End previous section's columns environment if this isn't the first section
            if i > 0:
                slide_parts.append("\\end{column}")
                slide_parts.append("\\end{columns}")
                slide_parts.append("\\vspace{1em}")

            # Start new columns environment for this section
            slide_parts.append("\\begin{columns}[t]")
            if section_has_columns:
                slide_parts.append("\\begin{column}[t]{0.484\\textwidth}")
            else:
                slide_parts.append("\\begin{column}[t]{\\textwidth}")

            # Process blocks in this section
            self._process_section_blocks(section, slide_parts, section_has_columns)

        # Always end the final column and columns environment
        slide_parts.append("\\end{column}")
        slide_parts.append("\\end{columns}")

        return in_columns

    def _process_section_blocks(
        self,
        blocks: List[Block],
        slide_parts: List[str],
        has_columns: bool,
    ) -> None:
        """Process blocks within a single section."""
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
                slide_parts.append("\\end{column}")
                slide_parts.append("\\begin{column}[t]{0.484\\textwidth}")
            else:
                slide_parts.append(self._format_block(block, has_columns))

    def _finalize_slide(self, slide_parts: List[str], footnotes: List[Block]):
        """Finalize slide with vfill and footnotes."""
        # Add vfill to push footnotes to bottom
        slide_parts.append("")
        slide_parts.append("\\vfill")
        slide_parts.append("")

        # Add fake footnotes if any exist
        if footnotes:
            slide_parts.append(
                "\\parbox[t]{0.95\\paperwidth}{"
                + self._format_fake_footnotes(footnotes)
                + "}"
            )

        # End minipage and frame
        slide_parts.append("\\end{minipage}")
        slide_parts.append("\\end{frame}")
        slide_parts.append("")  # Empty line between slides

    def _generate_slide(self, blocks: List[Block]) -> str:
        """Generate LaTeX for a single slide with caching."""
        # Generate hash for this slide
        cache_hash = self._hash_blocks(blocks)

        # Check cache first
        cache = self._load_cache()
        if cache_hash in cache:
            return cache[cache_hash]

        # Cache miss - generate the slide
        latex_source = self._generate_slide_uncached(blocks)

        # Save to cache
        self._save_to_cache(cache_hash, latex_source)

        return latex_source

    def _generate_slide_uncached(self, blocks: List[Block]) -> str:
        """Generate LaTeX for a single slide."""
        slide_parts = []
        slide_title = ""
        slide_metadata = {}
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
            "\\vspace{-1.5em}\\begin{minipage}[t][0.88\\textheight]{\\textwidth}"
        )

        # Process blocks with section-aware column handling
        in_columns = self._process_slide_blocks(blocks, slide_parts, True)

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
                lines = content.split("\n")
                for line in lines:
                    line = line.strip()
                    if line.startswith(":author:"):
                        author = line[8:].strip()  # Remove :author: prefix
                    elif line.startswith(":email:"):
                        email = (
                            ":email: " + line[7:].strip()
                        )  # Keep :email: for icon processing
                    elif line.startswith(":web:"):
                        web = (
                            ":web: " + line[5:].strip()
                        )  # Keep :web: for icon processing

        # Start frame with special template that hides page number
        slide_parts.append("\\setbeamertemplate{frametitle}{%")
        slide_parts.append("  \\vskip-0.2ex")
        slide_parts.append("  \\makebox[\\paperwidth][s]{%")
        slide_parts.append(
            "    \\begin{beamercolorbox}[wd=\\paperwidth,ht=2.5ex,dp=1ex,leftskip=1em,rightskip=1em]{frametitle}%"
        )
        slide_parts.append("      \\usebeamerfont{frametitle}%")
        slide_parts.append("      \\insertframetitle")
        slide_parts.append("    \\end{beamercolorbox}%")
        slide_parts.append("  }%")
        slide_parts.append("  \\tikzset{tikzmark prefix=frame\\insertframenumber}")
        slide_parts.append("}")
        slide_parts.append("\\begin{frame}[t]")
        slide_parts.append("\\frametitle{\\,}")

        # Start minipage matching inspiration.tex layout, shifted 2em to the right
        slide_parts.append(
            "\\vspace{-2.5em}\\hspace{2em}\\begin{minipage}[t][0.88\\textheight]{\\textwidth}"
        )
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
            processed_email = icons.process_heading_icons(email, self.output_dir)
            contact_parts.append(processed_email)
        if web:
            processed_web = icons.process_heading_icons(web, self.output_dir)
            contact_parts.append(processed_web)

        if contact_parts:
            slide_parts.append(
                "\\hspace{2em}".join(contact_parts)
            )  # 2em space between email and web
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
        slide_parts.append(
            "    \\begin{beamercolorbox}[wd=\\paperwidth,ht=2.5ex,dp=1ex,leftskip=1em,rightskip=1em]{frametitle}%"
        )
        slide_parts.append("      \\usebeamerfont{frametitle}%")
        slide_parts.append(
            "      \\insertframetitle\\ifx\\insertframetitle\\@empty\\else\\def\\tempcomma{\\,}\\ifx\\insertframetitle\\tempcomma\\else\\hfill{\\footnotesize \\insertframenumber}\\fi\\fi"
        )
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
        footnotes = []

        # Extract footnotes
        for block in blocks:
            if block.type == BlockType.FOOTNOTE:
                footnotes.append(block)

        # Set blue color before frame begins
        slide_parts.append("\\setbeamercolor{frametitle}{bg=ncblue, fg=white}")

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

        # Process blocks with section-aware column handling
        in_columns = self._process_slide_blocks(blocks, slide_parts, True)

        # Finalize slide
        self._finalize_slide(slide_parts, footnotes)

        # Reset frametitle color back to original blue
        slide_parts.append("\\setbeamercolor{frametitle}{bg=ncblue, fg=white}")

        return "\n".join(slide_parts)

    def _format_block(self, block: Block, has_columns: bool = False) -> str:
        """Format a single block based on its type."""
        if block.type == BlockType.ANNOTATED_EQUATION:
            latex_output, self.node_counter = equations.format_annotated_equation(
                block, has_columns, self.node_counter, self.output_dir
            )
            return latex_output
        elif block.type == BlockType.TABLE:
            return tables.format_table(block.content)
        elif block.type == BlockType.LIST:
            return lists.format_list(
                block.content, lambda x: icons.process_heading_icons(x, self.output_dir)
            )
        elif block.type == BlockType.IMAGE:
            return images.format_image(block, has_columns, self.output_dir)
        elif block.type == BlockType.FOOTNOTE:
            return f"\\footnote[{block.metadata['number']}]{{{block.content}}}"
        elif block.type == BlockType.TEXT:
            return text.format_text(block.content)
        else:
            return block.content

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

        # Add numbered footnotes with blue markers and pipes, gray text
        for footnote in numbered_footnotes:
            number = footnote.metadata.get("number", "")
            # Apply italic formatting to footnote content
            content = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", footnote.content)
            footnote_parts.append(
                f"\\textcolor{{ncblue}}{{{number}}}\\textcolor{{ncblue}}{{|}}~\\textcolor{{gray}}{{{content}}}"
            )

        return " ".join(footnote_parts)
