"""
Equation formatting functionality for autoslide.

This module contains functions for formatting annotated equations with tikzmark nodes,
including complex annotation placement algorithms that avoid overlaps and fit within page bounds.
"""

import re
import sys
import tempfile
import os
import subprocess
import shutil
from typing import List, Dict, Tuple, Optional
from .models import Block
from . import ink

# Raster ink-collision configuration (see determine_annotation_placement).
INK_DPI = 300
CLEARANCE_PT = 3.0


def format_annotated_equation(block: Block, has_columns: bool = False, node_counter: int = 0, output_dir: str = ".") -> Tuple[str, int]:
    """Format an annotated equation with tikzmarknode annotations."""
    equation = block.metadata["equation"]
    annotations = block.metadata["annotations"]
    heading = block.metadata.get("heading", "")

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
    annotation_source_lines = {}  # 1-indexed annotation position -> source line number
    annotation_start_line = block.metadata.get("annotation_start_line")
    source_filename = block.metadata.get("source_filename")
    if annotations.strip():
        for offset, raw_line in enumerate(annotations.split("\n")):
            line = raw_line.strip()
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
                if annotation_start_line is not None:
                    annotation_source_lines[len(annotation_specs)] = (
                        annotation_start_line + offset
                    )

    def _prepend_heading(latex: str) -> str:
        if not heading:
            return latex
        rendered = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", heading)
        return f"\\textbf{{\\textcolor{{ncblue}}{{{rendered}}}}}\n{latex}"

    # If no annotations, render as simple equation
    if not annotation_specs:
        return _prepend_heading(f"\\begin{{align}}\\abovedisplayskip=0pt\\belowdisplayskip=0pt{equation_content}\\end{{align}}"), node_counter

    # Create tikzmarknode-wrapped equation
    annotated_equation, node_names, node_counter = create_tikzmarknode_equation_new(
        equation_content, annotation_specs, node_counter,
        annotation_source_lines=annotation_source_lines,
        source_filename=source_filename,
    )

    # Determine optimal placement for annotations
    heading_hint = f" [{heading[:40]}]" if heading else ""
    print(f"Placing annotations for equation{heading_hint}", file=sys.stderr, flush=True)
    above_placements, below_placements, above_vspace_pt, below_vspace_pt = (
        determine_annotation_placement(
            annotated_equation, annotation_specs, node_names, has_columns, node_counter,
            output_dir, equation_content=equation_content,
        )
    )

    # Convert placements to label map for tikzpicture generation
    annotations_above = {}
    annotations_below = {}
    for i, (exact_string, label) in enumerate(annotation_specs, 1):
        if i in above_placements:
            annotations_above[i] = label
        elif i in below_placements:
            annotations_below[i] = label

    # Generate tikzpicture with annotations
    if annotations_above or annotations_below:
        tikz_code, _ = generate_tikzpicture_annotations(
            annotations_above,
            annotations_below,
            node_names,
            above_placements,
            below_placements,
        )

        # Generate the complete LaTeX output
        latex_parts = []

        # Space above equation to contain above annotations within the tcolorbox bbox
        if above_vspace_pt > 0:
            latex_parts.append(f"\\vspace{{{above_vspace_pt:.2f}pt}}")

        # Add the equation first so nodes are defined
        latex_parts.append(
            f"\\begin{{align}}\\abovedisplayskip=0pt\\belowdisplayskip=0pt{annotated_equation}\\end{{align}}"
        )

        # Add annotation lines and text (background fill is now handled by tikzmarknode)
        latex_parts.extend(tikz_code)

        # An overlay tikzpicture's zero-size box opens a paragraph that never
        # explicitly closes, so a \vspace placed right after it lands mid-paragraph
        # and is silently absorbed instead of pushing the next block down - \par
        # first forces it back into vertical mode where \vspace actually applies.
        if below_vspace_pt > 0:
            latex_parts.append(f"\\par\\vspace{{{below_vspace_pt:.2f}pt}}")
    else:
        # No annotations, just the equation
        latex_parts = [
            f"\\begin{{align}}\\abovedisplayskip=0pt\\belowdisplayskip=0pt{annotated_equation}\\end{{align}}"
        ]

    return _prepend_heading("\n".join(latex_parts)), node_counter


def create_tikzmarknode_equation_new(
    equation_content: str,
    annotation_specs: List[Tuple[str, str]],
    node_counter: int,
    annotation_source_lines: Dict[int, int] = None,
    source_filename: str = None,
) -> Tuple[str, Dict[int, str], int]:
    """Create equation with tikzmarknode wrappers based on exact string matching."""
    result = equation_content
    node_names = {}  # Map annotation position to node name
    annotation_source_lines = annotation_source_lines or {}

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
            location_parts = []
            if source_filename:
                location_parts.append(source_filename)
            if i in annotation_source_lines:
                location_parts.append(f"line {annotation_source_lines[i]}")
            location = f" ({', '.join(location_parts)})" if location_parts else ""
            raise ValueError(
                f"Annotation string '[[ {exact_string} ]]'{location} not found in equation (or only found inside existing annotations)"
            )

        # Generate unique node name
        node_counter += 1
        node_name = f"node{node_counter}"
        node_names[i] = node_name

        # Replace the exact string with tikzmarknode wrapper that includes background fill
        before = result[:pos]
        after = result[pos + len(exact_string) :]
        wrapped = f"\\tikzmarknode[fill=ncblue!15,inner sep=1pt,outer sep=0pt]{{{node_name}}}{{{exact_string}\\mathstrut}}"
        result = before + wrapped + after

    return result, node_names, node_counter


def determine_annotation_placement(
    equation_with_nodes: str,
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    has_columns: bool = False,
    node_counter: int = 0,
    output_dir: str = ".",
    equation_content: str = "",
) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]], float, float]:
    """Determine optimal placement for annotations using bounding box analysis.

    Returns:
        Tuple of (above_placements, below_placements, above_vspace_pt, below_vspace_pt)
    """
    if not annotation_specs:
        return {}, {}, 0.0, 0.0

    # Configuration - all values in pt (points)
    BASE_WIDTH_PT = 455.0  # Full page width in points
    if has_columns:
        PAGE_WIDTH_PT = (BASE_WIDTH_PT - 20.0) / 2.0
    else:
        PAGE_WIDTH_PT = BASE_WIDTH_PT
    HORIZONTAL_PADDING_PT = 10.0

    # Step 1: Measure bounding boxes, node positions, and equation bbox using LaTeX
    try:
        bounding_boxes, node_positions, node_shifts, eq_dimensions, eq_ink = (
            measure_annotation_bounding_boxes(
                equation_with_nodes, annotation_specs, node_names, node_counter,
                output_dir, has_columns, equation_content=equation_content,
            )
        )
    except Exception as e:
        print(f"Error measuring bounding boxes: {e}", file=sys.stderr)
        print(f"Equation: {equation_with_nodes}", file=sys.stderr)
        print(f"Annotations: {annotation_specs}", file=sys.stderr)
        raise

    # Step 2: Find optimal placement using brute force search
    above_placements, below_placements = find_optimal_placement(
        annotation_specs,
        bounding_boxes,
        node_positions,
        node_names,
        PAGE_WIDTH_PT,
        HORIZONTAL_PADDING_PT,
        node_shifts,
        has_columns,
        eq_ink=eq_ink,
    )

    # Step 3: Compute the tight vspace needed beyond the equation's own natural
    # typeset extent, using exactly the same geometry (baseline_y, node_shifts,
    # bounding_boxes, chosen level/anchor) the placement search itself used - no
    # separate heuristic buffer, no em-per-pt approximation. eq_height/eq_depth
    # are the equation's own natural extent above/below its baseline (from a
    # plain \ht/\dp box measurement, so unaffected by the page-coordinate sign
    # convention); annotations only need extra room for whatever they add
    # beyond that natural extent.
    eq_height, eq_depth = eq_dimensions
    baseline_y = eq_ink.baseline_y if eq_ink is not None else 0.0
    natural_top_y = baseline_y - eq_height
    natural_bottom_y = baseline_y + eq_depth

    # CLEARANCE_PT is the same minimum gap used everywhere else in this module
    # to keep labels from touching other ink - applying it here too means a
    # label's far edge isn't flush against whatever block follows the equation.
    top_needed_y = natural_top_y
    for i, (level, _) in above_placements.items():
        height_pt = bounding_boxes.get(i, (0.0, 0.0))[1]
        node_y = baseline_y - node_shifts.get(i, 0.0)
        far_y = node_y - level - height_pt - CLEARANCE_PT
        top_needed_y = min(top_needed_y, far_y)
    above_vspace_pt = max(0.0, natural_top_y - top_needed_y)

    bottom_needed_y = natural_bottom_y
    for i, (level, _) in below_placements.items():
        height_pt = bounding_boxes.get(i, (0.0, 0.0))[1]
        node_y = baseline_y - node_shifts.get(i, 0.0)
        far_y = node_y + level + height_pt + CLEARANCE_PT
        bottom_needed_y = max(bottom_needed_y, far_y)
    below_vspace_pt = max(0.0, bottom_needed_y - natural_bottom_y)

    return above_placements, below_placements, above_vspace_pt, below_vspace_pt


def measure_annotation_bounding_boxes(
    equation_with_nodes: str,
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    node_counter: int,
    output_dir: str = ".",
    has_columns: bool = False,
    equation_content: str = "",
) -> Tuple[
    Dict[int, Tuple[float, float]],
    Dict[int, float],
    Dict[int, float],
    Tuple[float, float],
    Optional[ink.EquationInk],
]:
    """Measure bounding boxes of annotation text and tikzmarknode positions using LaTeX,
    and rasterize the compiled equation to build an ink-collision mask.

    Returns:
        Tuple of (bounding_boxes, node_positions, node_shifts, eq_dimensions, eq_ink) where:
        - bounding_boxes: Dict mapping annotation index -> (width_pt, height_pt)
        - node_positions: Dict mapping annotation index -> x_position_pt
        - node_shifts: Dict mapping annotation index -> y_shift_from_baseline_pt
        - eq_dimensions: (height_pt, depth_pt) of the equation box
        - eq_ink: EquationInk with the dilated ink mask + coordinate metadata, or
          None if rasterization failed (callers should fall back to eq_dimensions only)
    """
    import tempfile
    import os
    import subprocess
    import re
    import shutil

    # Create a temporary directory for LaTeX compilation within the output directory
    temp_dir = tempfile.mkdtemp(dir=output_dir)

    try:
        # Create a temporary LaTeX document to measure all annotations
        measurement_latex, _ = create_measurement_document(
            equation_with_nodes, annotation_specs, node_names, node_counter, has_columns,
            equation_content=equation_content,
        )

        # Write to temporary file in the temporary directory
        temp_tex_path = os.path.join(temp_dir, "measurement.tex")
        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(measurement_latex)

        # Create empty navigation file to satisfy beamer requirements
        with open(os.path.join(temp_dir, "measurement.nav"), "w") as f:
            f.write("")

        # Run latexmk with XeLaTeX to compile and measure (handles multiple runs automatically)
        n = len(annotation_specs)
        print(f"  Measuring annotation layout ({n} annotation{'s' if n != 1 else ''})...", file=sys.stderr, flush=True)
        result = subprocess.run(
            ["latexmk", "-xelatex", "-interaction=nonstopmode", "measurement.tex"],
            capture_output=True,
            text=True,
            cwd=temp_dir,
        )
        print(f"  Done.", file=sys.stderr, flush=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"LaTeX compilation failed with return code {result.returncode}, see {temp_dir} for details.\n"
            )

        # Parse measurements from log file
        log_path = os.path.join(temp_dir, "measurement.log")

        bounding_boxes, node_positions, node_shifts, eq_dimensions, page_size_pt, baseline_y = (
            parse_measurements_from_log(log_path, len(annotation_specs))
        )

        eq_ink = None
        page_width_pt, page_height_pt = page_size_pt
        if page_height_pt > 0:
            try:
                pdf_path = os.path.join(temp_dir, "measurement.pdf")
                eq_ink = ink.build_equation_ink(
                    pdf_path, baseline_y, INK_DPI, CLEARANCE_PT
                )
            except Exception as e:
                print(f"Warning: could not build equation ink mask: {e}", file=sys.stderr)

        return bounding_boxes, node_positions, node_shifts, eq_dimensions, eq_ink

    finally:
        # Clean up entire temporary directory
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass


def create_measurement_document(
    equation_with_nodes: str,
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    node_counter: int,
    has_columns: bool = False,
    equation_content: str = "",
) -> Tuple[str, int]:
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
\definecolor{ncblue}{RGB}{221,150,51}
\definecolor{ncblue}{RGB}{10,45,100}

\usepackage[para]{footmisc}
\setbeamercolor{section title}{fg=navyblue}
\setbeamerfont{section title}{series=\bfseries}

\setbeamercolor{frametitle}{bg=ncblue, fg=white}
\setbeamertemplate{navigation symbols}{}
\setbeamertemplate{itemize item}{\textcolor{ncblue}{\textendash}}
\setbeamertemplate{itemize subitem}{\textcolor{ncblue}{\textendash}}
\setbeamertemplate{itemize subsubitem}{\textcolor{ncblue}{\textendash}}
\setlength{\leftmargini}{1em}
\setlength{\leftmarginii}{2em}
\setlength{\leftmarginiii}{3em}
\setbeamercolor{footnote mark}{fg=ncblue}
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
\renewcommand{\theequation}{\textcolor{ncblue}{\arabic{equation}}}
\makeatletter
\renewcommand{\tagform@}[1]{\maketag@@@{\textcolor{ncblue}{(#1)}}}
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
\newsavebox{\eqmeasurebox}
\begin{frame}[t]
\typeout{PAGESIZE: width=\the\paperwidth, height=\the\paperheight}
"""

    # Add column setup if needed
    if has_columns:
        preamble += r"""
% Set up two-column environment to match actual rendering context
\begin{columns}[t]
\column{0.48\textwidth}
% Content goes in right column to match typical equation placement
\column{0.48\textwidth}
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
    node_counter += 1
    baseline_node_name = f"baseline{node_counter}"

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

    # Measure equation bounding box using an hbox with displaystyle math.
    # \ht gives height above the math baseline, \dp gives depth below — the same
    # coordinate origin as the TikZ node_shifts (which are relative to the baseline node).
    # \vbox would put the baseline at the box bottom, making \ht = total height and \dp = 0,
    # which is incompatible with the TikZ coordinate system.
    eq_to_measure = equation_content if equation_content else equation_with_nodes
    measurement_commands.append(
        f"""
% Measure equation bounding box (height above math baseline, depth below math baseline)
\\sbox{{\\eqmeasurebox}}{{$\\displaystyle\\begin{{aligned}}{eq_to_measure}\\end{{aligned}}$}}
\\typeout{{EQMEASURE: height=\\the\\ht\\eqmeasurebox, depth=\\the\\dp\\eqmeasurebox}}
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

    # Close column environment if needed
    column_close = ""
    if has_columns:
        column_close = "\n\\end{columns}"

    document = (
        preamble
        + "\n".join(measurement_commands)
        + column_close
        + "\n\\end{frame}\n\\end{document}"
    )
    return document, node_counter


def parse_measurements_from_log(
    log_path: str, num_annotations: int
) -> Tuple[
    Dict[int, Tuple[float, float]],
    Dict[int, float],
    Dict[int, float],
    Tuple[float, float],
    Tuple[float, float],
    float,
]:
    """Parse bounding box measurements and node positions from LaTeX log file.

    Returns:
        Tuple of (bounding_boxes, node_positions, node_shifts, eq_dimensions, page_size_pt, baseline_y) where:
        - bounding_boxes: Dict mapping annotation index -> (width_pt, height_pt)
        - node_positions: Dict mapping annotation index -> x_position_pt
        - node_shifts: Dict mapping annotation index -> y_shift_from_baseline_pt
        - eq_dimensions: (height_pt, depth_pt) of the equation box
        - page_size_pt: (paperwidth_pt, paperheight_pt) of the beamer frame
        - baseline_y: absolute y-position (in the tikz "current page" coordinate
          system) of the equation's baseline node
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

    # Parse equation bounding box measurement
    eq_height = 0.0
    eq_depth = 0.0
    eq_match = re.search(r"EQMEASURE: height=([0-9.]+)pt, depth=([0-9.]+)pt", log_content)
    if eq_match:
        eq_height = float(eq_match.group(1))
        eq_depth = float(eq_match.group(2))
    else:
        print("Warning: Could not find equation bbox measurement (EQMEASURE)", file=sys.stderr)

    page_width_pt = 0.0
    page_height_pt = 0.0
    page_match = re.search(
        r"PAGESIZE: width=([0-9.]+)pt, height=([0-9.]+)pt", log_content
    )
    if page_match:
        page_width_pt = float(page_match.group(1))
        page_height_pt = float(page_match.group(2))
    else:
        print("Warning: Could not find page size measurement (PAGESIZE)", file=sys.stderr)

    return (
        bounding_boxes,
        node_positions,
        node_shifts,
        (eq_height, eq_depth),
        (page_width_pt, page_height_pt),
        baseline_y,
    )


LEADER_HALF_WIDTH_PT = 2.0
LEADER_CLEARANCE_PT = 2.0
MAX_BACKTRACK_VISITS = 500_000  # safety valve against pathological inputs


def _annotation_option_obstacles(
    i: int,
    position: str,
    level: float,
    anchor: str,
    bounding_boxes: Dict[int, Tuple[float, float]],
    node_positions: Dict[int, float],
    node_shifts: Dict[int, float],
    baseline_y: float,
    page_width_pt: float,
    horizontal_padding_pt: float,
    has_columns: bool,
    eq_ink,
):
    """Build (label_rect, leader_rect) for one candidate (position, level, anchor)
    placement of annotation i, checked in isolation (forced side, page margin,
    equation ink). Returns None if this option is invalid regardless of what else
    is placed. Returns (None, None) if there's nothing to check (no measured
    geometry for this annotation) - such an option never conflicts with anything."""
    if node_shifts[i] < 0 and position == "above":
        return None
    if node_shifts[i] > 0 and position == "below":
        return None
    if i not in bounding_boxes or i not in node_positions:
        return (None, None)

    left_margin = 5.0 if has_columns else 20.0
    right_margin = left_margin

    width_pt, height_pt = bounding_boxes[i]
    node_x = node_positions[i]
    padded_width = width_pt + horizontal_padding_pt

    # Only the label's growing edge (away from the node) is a placement choice
    # and gets margin-checked; the anchor-side edge is just the symbol's own
    # fixed position, which annotation placement has no control over.
    if anchor == "base west":  # Left-aligned text extends right from node
        left_bound = node_x
        right_bound = node_x + padded_width
        if right_bound > page_width_pt - right_margin:
            return None
    else:  # "base east" - Right-aligned text extends left from node
        left_bound = node_x - padded_width
        right_bound = node_x
        if left_bound < left_margin:
            return None

    # node_shifts is y_pt - baseline_y in the raw "current page" coordinate
    # system, which (verified empirically by rendering a known superscript/
    # subscript pair and checking where they land on the rasterized page)
    # increases *downward* - the opposite of the "positive means above"
    # convention its own docstring assumes. Negate it here so "above"/"below"
    # below correctly mean smaller/larger raw y (and therefore smaller/larger
    # pixel row, matching ink.pt_to_px's direct y*scale).
    node_y = baseline_y - node_shifts[i]
    if position == "above":
        near_y, far_y = node_y - level, node_y - level - height_pt
    else:
        near_y, far_y = node_y + level, node_y + level + height_pt
    bottom, top = (near_y, far_y) if near_y <= far_y else (far_y, near_y)

    label_rect = (left_bound, right_bound, bottom, top)

    if eq_ink is not None and ink.equation_ink_overlaps_rect(
        eq_ink, left_bound, right_bound, bottom, top
    ):
        return None

    leader_bottom, leader_top = (node_y, near_y) if node_y <= near_y else (near_y, node_y)
    leader_rect = (
        node_x - LEADER_HALF_WIDTH_PT,
        node_x + LEADER_HALF_WIDTH_PT,
        leader_bottom,
        leader_top,
    )

    return (label_rect, leader_rect)


def _obstacles_conflict(rect_a, is_leader_a, rect_b, is_leader_b) -> bool:
    """Buffered rectangle overlap - catches close (including diagonal) contacts.
    A pair where either side is a leader line uses a smaller clearance, since
    leader lines are already thin by design."""
    l1, r1, b1, t1 = rect_a
    l2, r2, b2, t2 = rect_b
    clearance = LEADER_CLEARANCE_PT if (is_leader_a or is_leader_b) else CLEARANCE_PT
    el1, er1 = l1 - clearance, r1 + clearance
    eb1, et1 = b1 - clearance, t1 + clearance
    return el1 < r2 and er1 > l2 and eb1 < t2 and et1 > b2


def find_optimal_placement(
    annotation_specs: List[Tuple[str, str]],
    bounding_boxes: Dict[int, Tuple[float, float]],
    node_positions: Dict[int, float],
    node_names: Dict[int, str],
    page_width_pt: float,
    horizontal_padding_pt: float,
    node_shifts: Dict[int, float],
    has_columns: bool = False,
    eq_ink=None,
) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]]]:
    """Find optimal placement using a pruned backtracking search over a fixed,
    regularly-spaced grid of levels.

    Annotations are free to end up above or below the equation (whichever a given
    node's position allows). Options are tried cheapest-level-first and a
    branch-and-bound cutoff on total vertical space keeps the search from ever
    materializing the full cartesian product of placement choices - which, with
    8+ annotations and a handful of levels, is far too large to enumerate.
    """
    num_annotations = len(annotation_specs)
    baseline_y = eq_ink.baseline_y if eq_ink is not None else 0.0
    indices = list(range(1, num_annotations + 1))

    max_attempts = 8  # Safety limit on how many level tiers to try
    LEVEL_STEP_PT = 7.5  # spacing between successive levels (halved from 15pt)

    for num_levels in range(1, max_attempts + 1):
        # Regular, fixed-step grid of levels. The innermost distance (equation
        # to first level) is unchanged; only the spacing between subsequent
        # levels is halved.
        base_level_pt = 15.0  # First level at 15pt below equation
        levels_below = [base_level_pt + i * LEVEL_STEP_PT for i in range(num_levels)]
        levels_above = [20.0 + i * LEVEL_STEP_PT for i in range(num_levels)]

        options_per_annotation = {}
        for i in indices:
            opts = []
            for position, levels in (("above", levels_above), ("below", levels_below)):
                for level in levels:
                    for anchor in ("base west", "base east"):
                        obs = _annotation_option_obstacles(
                            i, position, level, anchor,
                            bounding_boxes, node_positions, node_shifts, baseline_y,
                            page_width_pt, horizontal_padding_pt, has_columns, eq_ink,
                        )
                        if obs is not None:
                            opts.append((position, level, anchor, obs))
            opts.sort(key=lambda o: o[1])  # cheapest level first: finds a good solution fast
            options_per_annotation[i] = opts

        if any(not options_per_annotation[i] for i in indices):
            continue  # some annotation has no viable option at all at this tier

        # Most-constrained-first ordering (classic CSP heuristic): annotations
        # with fewer options are the likeliest to fail, so resolve them early.
        order = sorted(indices, key=lambda i: len(options_per_annotation[i]))

        best = {"combo": None, "cost": None}
        placed_obstacles = []  # list of (is_leader, rect)
        assignment = {}
        visits = 0

        def backtrack(pos_in_order, cur_above_max, cur_below_max):
            nonlocal visits
            visits += 1
            if visits > MAX_BACKTRACK_VISITS:
                return
            if best["cost"] is not None and (cur_above_max + cur_below_max) >= best["cost"]:
                return  # branch-and-bound: can't possibly beat the best found so far
            if pos_in_order == len(order):
                cost = cur_above_max + cur_below_max
                if best["cost"] is None or cost < best["cost"]:
                    best["cost"] = cost
                    best["combo"] = dict(assignment)
                return

            i = order[pos_in_order]
            for position, level, anchor, (label_rect, leader_rect) in options_per_annotation[i]:
                new_above_max = max(cur_above_max, level) if position == "above" else cur_above_max
                new_below_max = max(cur_below_max, level) if position == "below" else cur_below_max
                if best["cost"] is not None and (new_above_max + new_below_max) >= best["cost"]:
                    continue

                conflict = False
                if label_rect is not None:
                    for is_leaderj, rectj in placed_obstacles:
                        if _obstacles_conflict(label_rect, False, rectj, is_leaderj) or (
                            _obstacles_conflict(leader_rect, True, rectj, is_leaderj)
                        ):
                            conflict = True
                            break
                if conflict:
                    continue

                assignment[i] = (position, level, anchor)
                added = 0
                if label_rect is not None:
                    placed_obstacles.append((False, label_rect))
                    placed_obstacles.append((True, leader_rect))
                    added = 2
                backtrack(pos_in_order + 1, new_above_max, new_below_max)
                for _ in range(added):
                    placed_obstacles.pop()
                del assignment[i]

                if visits > MAX_BACKTRACK_VISITS:
                    return

        backtrack(0, 0.0, 0.0)

        if best["combo"] is not None:
            above_placements = {}
            below_placements = {}
            for i, (position, level, anchor) in best["combo"].items():
                if i in node_names:
                    if position == "above":
                        above_placements[i] = (level, anchor)
                    else:
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


def generate_tikzpicture_annotations(
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
            f"\path[fill=ncblue!15,draw=none,line width=0pt] ({node_name}.north west) -- ({node_name}.north east) -- ([yshift=13pt]{node_name}.base east) -- ([yshift=13pt]{node_name}.base west) -- cycle;"
        )

        tikz_parts.append(
            f"    \\draw[ncblue, line width=0.4mm] ([yshift=13pt]{node_name}.base west) -- ([yshift=13pt]{node_name}.base east);"
        )
        tikz_parts.append(
            f"    \\draw[ncblue,] ([yshift=13pt]{node_name}.base) -- ([yshift={height}pt]{node_name}.base);"
        )
        tikz_parts.append(
            f"    \\node[above={reduced_height}pt of {node_name}.base,anchor={anchor},inner sep=0,outer sep=0,xshift={xshift},yshift={yshift},text=ncblue] {{\\scriptsize {text}}};"
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
            f"\path[fill=ncblue!15,draw=none,line width=0pt] ({node_name}.south west) -- ({node_name}.south east) -- ([yshift=-8pt]{node_name}.base east) -- ([yshift=-8pt]{node_name}.base west) -- cycle;"
        )

        # Draw the annotation line and connecting line
        tikz_parts.append(
            f"    \\draw[ncblue, line width=0.4mm] ([yshift=-8pt]{node_name}.base west) -- ([yshift=-8pt]{node_name}.base east);"
        )
        tikz_parts.append(
            f"    \\draw[ncblue,] ([yshift=-8pt]{node_name}.base) -- ([yshift=-{height}pt]{node_name}.base);"
        )
        tikz_parts.append(
            f"    \\node[below={height}pt of {node_name}.base,anchor={anchor},inner sep=0,outer sep=0,xshift={xshift},yshift=-3pt,text=ncblue] {{\\scriptsize {text}}};"
        )
        tikz_parts.append("")

    tikz_parts.append("\\end{tikzpicture}")
    return tikz_parts, space_requirements