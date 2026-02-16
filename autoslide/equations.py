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
from typing import List, Dict, Tuple
from .models import Block


def format_annotated_equation(block: Block, has_columns: bool = False, node_counter: int = 0, output_dir: str = ".") -> Tuple[str, int]:
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
        return f"\\begin{{align}}\\abovedisplayskip=0pt\\belowdisplayskip=0pt{equation_content}\\end{{align}}", node_counter

    # Create tikzmarknode-wrapped equation
    annotated_equation, node_names, node_counter = create_tikzmarknode_equation_new(
        equation_content, annotation_specs, node_counter
    )

    # Determine optimal placement for annotations
    above_placements, below_placements = determine_annotation_placement(
        annotated_equation, annotation_specs, node_names, has_columns, node_counter, output_dir
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
        tikz_code, space_requirements = generate_tikzpicture_annotations(
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

    return "\n".join(latex_parts), node_counter


def create_tikzmarknode_equation_new(
    equation_content: str, annotation_specs: List[Tuple[str, str]], node_counter: int
) -> Tuple[str, Dict[int, str], int]:
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
    BASE_WIDTH_PT = 455.0  # Full page width in points
    if has_columns:
        # Double column: subtract margin and halve
        PAGE_WIDTH_PT = (BASE_WIDTH_PT - 20.0) / 2.0  # ~217.5 points per column
    else:
        PAGE_WIDTH_PT = BASE_WIDTH_PT  # Full width for single column
    HORIZONTAL_PADDING_PT = 10.0  # Clearance around annotations in points

    # Step 1: Measure bounding boxes and node positions using LaTeX
    try:
        bounding_boxes, node_positions, node_shifts = (
            measure_annotation_bounding_boxes(
                equation_with_nodes, annotation_specs, node_names, node_counter, output_dir, has_columns
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
    above_placements, below_placements = find_optimal_placement(
        annotation_specs,
        bounding_boxes,
        node_positions,
        node_names,
        PAGE_WIDTH_PT,
        HORIZONTAL_PADDING_PT,
        node_shifts,
        has_columns,
    )

    return above_placements, below_placements


def measure_annotation_bounding_boxes(
    equation_with_nodes: str,
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    node_counter: int,
    output_dir: str = ".",
    has_columns: bool = False,
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

    # Create a temporary directory for LaTeX compilation within the output directory
    temp_dir = tempfile.mkdtemp(dir=output_dir)

    try:
        # Create a temporary LaTeX document to measure all annotations
        measurement_latex, updated_node_counter = create_measurement_document(
            equation_with_nodes, annotation_specs, node_names, node_counter, has_columns
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
            parse_measurements_from_log(log_path, len(annotation_specs))
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


def create_measurement_document(
    equation_with_nodes: str,
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    node_counter: int,
    has_columns: bool = False,
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
\begin{frame}[t]
\scriptsize
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


def find_optimal_placement(
    annotation_specs: List[Tuple[str, str]],
    bounding_boxes: Dict[int, Tuple[float, float]],
    node_positions: Dict[int, float],
    node_names: Dict[int, str],
    page_width_pt: float,
    horizontal_padding_pt: float,
    node_shifts: Dict[int, float],
    has_columns: bool = False,
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
        all_combinations = generate_placement_combinations(
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
            if check_placement_validity(
                combination,
                bounding_boxes,
                node_positions,
                page_width_pt,
                horizontal_padding_pt,
                node_shifts,
                has_columns,
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


def generate_placement_combinations(
    num_annotations: int, levels_above: List[float], levels_below: List[float]
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


def check_placement_validity(
    combination: List[Tuple[str, float, str]],
    bounding_boxes: Dict[int, Tuple[float, float]],
    node_positions: Dict[int, float],
    page_width_pt: float,
    horizontal_padding_pt: float,
    node_shifts: Dict[int, float],
    has_columns: bool = False,
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
        # In two-column mode, use smaller left margin since we're within a column
        left_margin = 5.0 if has_columns else 20.0
        for i, left_bound, right_bound, anchor, width in annotations:
            if left_bound < left_margin or right_bound > page_width_pt:
                return False

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
    return True


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