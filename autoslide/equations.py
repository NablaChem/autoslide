"""
Annotated equations: where each label goes, and the geometry to get it there.

This module owns the placement *algorithm* - measuring the typeset equation,
then searching for a set of label positions that collide with neither the
equation's ink nor each other. The LaTeX it produces lives in
``templates/blocks/equation.tex.j2``, and the measurement document it compiles
in ``templates/measure/document.tex.j2``.
"""

import re
import sys
import tempfile
import os
import subprocess
import shutil
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

from .models import Block
from .theme import Theme, default_theme
from . import ink, templating


@dataclass
class AnnotationDraw:
    """One label, resolved to the lengths ``blocks/equation.tex.j2`` needs."""

    node: str
    side: str  # "above" | "below"
    text: str
    corner: str  # tikz anchor the highlight tint grows from
    stem_pt: float  # where the leader line starts, relative to the baseline
    leader_pt: float  # where it ends
    label_offset_pt: float  # distance passed to tikz's above=/below=
    anchor: str
    xshift: str
    yshift: str


def render_annotated_equation(
    block: Block,
    engine: templating.TemplateEngine,
    has_columns: bool = False,
    node_counter: int = 0,
    output_dir: str = ".",
) -> Tuple[str, int]:
    """Render an equation block, placing any annotations. Returns (latex, counter)."""
    theme = engine.theme
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

    def _render(equation_body: str, draws: List[AnnotationDraw], above: float, below: float) -> str:
        return engine.render(
            "blocks/equation.tex.j2",
            heading=heading,
            equation=equation_body,
            annotations=draws,
            above_vspace_pt=above,
            below_vspace_pt=below,
        )

    # If no annotations, render as simple equation
    if not annotation_specs:
        return _render(equation_content, [], 0.0, 0.0), node_counter

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
            output_dir, equation_content=equation_content, theme=theme,
        )
    )

    draws = build_annotation_draws(
        annotation_specs, node_names, above_placements, below_placements, theme
    )
    if not draws:
        return _render(annotated_equation, [], 0.0, 0.0), node_counter

    return (
        _render(annotated_equation, draws, above_vspace_pt, below_vspace_pt),
        node_counter,
    )


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
        theme = default_theme()
        wrapped = (
            f"\\tikzmarknode[fill={theme.colors.node_fill},"
            f"inner sep={theme.annotations.node_inner_sep},outer sep=0pt]"
            f"{{{node_name}}}{{{exact_string}\\mathstrut}}"
        )
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
    theme: Optional[Theme] = None,
) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]], float, float]:
    """Determine optimal placement for annotations using bounding box analysis.

    Returns:
        Tuple of (above_placements, below_placements, above_vspace_pt, below_vspace_pt)
    """
    if not annotation_specs:
        return {}, {}, 0.0, 0.0

    theme = theme or default_theme()
    config = theme.annotations
    if has_columns:
        available_width_pt = (config.page_width_pt - config.column_gutter_pt) / 2.0
    else:
        available_width_pt = config.page_width_pt

    # Step 1: Measure bounding boxes, node positions, and equation bbox using LaTeX
    try:
        bounding_boxes, node_positions, node_shifts, eq_dimensions, eq_ink = (
            measure_annotation_bounding_boxes(
                equation_with_nodes, annotation_specs, node_names, node_counter,
                output_dir, has_columns, equation_content=equation_content,
                theme=theme,
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
        available_width_pt,
        config.horizontal_padding_pt,
        node_shifts,
        has_columns,
        eq_ink=eq_ink,
        theme=theme,
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

    # The same minimum gap used everywhere else in this module to keep labels
    # from touching other ink - applying it here too means a label's far edge
    # isn't flush against whatever block follows the equation.
    top_needed_y = natural_top_y
    for i, (level, _) in above_placements.items():
        height_pt = bounding_boxes.get(i, (0.0, 0.0))[1]
        node_y = baseline_y - node_shifts.get(i, 0.0)
        far_y = node_y - level - height_pt - config.clearance_pt
        top_needed_y = min(top_needed_y, far_y)
    above_vspace_pt = max(0.0, natural_top_y - top_needed_y)

    bottom_needed_y = natural_bottom_y
    for i, (level, _) in below_placements.items():
        height_pt = bounding_boxes.get(i, (0.0, 0.0))[1]
        node_y = baseline_y - node_shifts.get(i, 0.0)
        far_y = node_y + level + height_pt + config.clearance_pt
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
    theme: Optional[Theme] = None,
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
    theme = theme or default_theme()

    # Create a temporary directory for LaTeX compilation within the output directory
    temp_dir = tempfile.mkdtemp(dir=output_dir)

    try:
        # Create a temporary LaTeX document to measure all annotations
        measurement_latex, _ = create_measurement_document(
            equation_with_nodes, annotation_specs, node_names, node_counter, has_columns,
            equation_content=equation_content,
            engine=templating.engine(theme),
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
                    pdf_path,
                    baseline_y,
                    theme.annotations.ink_dpi,
                    theme.annotations.clearance_pt,
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
    engine: Optional[templating.TemplateEngine] = None,
) -> Tuple[str, int]:
    """Build the LaTeX document whose log reports annotation geometry.

    A baseline node is injected at the start of the equation; every measurement
    is reported relative to it. Returns (document, updated node_counter).
    """
    engine = engine or templating.engine()

    node_counter += 1
    baseline_node = f"baseline{node_counter}"

    equation_lines = [line.strip() for line in equation_with_nodes.strip().split("\n")]
    equation_lines = [line for line in equation_lines if line] or [""]
    equation_lines[0] = f"\\tikzmarknode{{{baseline_node}}}{{ }} {equation_lines[0]}".rstrip()

    document = engine.render(
        "measure/document.tex.j2",
        mode="measure",
        tracing=False,
        pygments_styles="",
        equation="\n".join(equation_lines),
        equation_body=equation_content or equation_with_nodes,
        # Savebox names must be letters, not digits: \measureboxA, \measureboxB, ...
        labels=[
            (chr(ord("A") + index - 1), index, label)
            for index, (_exact, label) in enumerate(annotation_specs, 1)
        ],
        nodes=sorted(node_names.items()),
        baseline_node=baseline_node,
        has_columns=has_columns,
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
    config=None,
):
    """Build (label_rect, leader_rect) for one candidate (position, level, anchor)
    placement of annotation i, checked in isolation (forced side, page margin,
    equation ink). Returns None if this option is invalid regardless of what else
    is placed. Returns (None, None) if there's nothing to check (no measured
    geometry for this annotation) - such an option never conflicts with anything."""
    config = config or default_theme().annotations
    if node_shifts[i] < 0 and position == "above":
        return None
    if node_shifts[i] > 0 and position == "below":
        return None
    if i not in bounding_boxes or i not in node_positions:
        return (None, None)

    left_margin = config.margin_column_pt if has_columns else config.margin_full_pt
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
        node_x - config.leader_half_width_pt,
        node_x + config.leader_half_width_pt,
        leader_bottom,
        leader_top,
    )

    return (label_rect, leader_rect)


def _obstacles_conflict(rect_a, is_leader_a, rect_b, is_leader_b, config=None) -> bool:
    """Buffered rectangle overlap - catches close (including diagonal) contacts.
    A pair where either side is a leader line uses a smaller clearance, since
    leader lines are already thin by design."""
    config = config or default_theme().annotations
    l1, r1, b1, t1 = rect_a
    l2, r2, b2, t2 = rect_b
    clearance = (
        config.leader_clearance_pt
        if (is_leader_a or is_leader_b)
        else config.clearance_pt
    )
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
    theme: Optional[Theme] = None,
) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]]]:
    """Find optimal placement using a pruned backtracking search over a fixed,
    regularly-spaced grid of levels.

    Annotations are free to end up above or below the equation (whichever a given
    node's position allows). Options are tried cheapest-level-first and a
    branch-and-bound cutoff on total vertical space keeps the search from ever
    materializing the full cartesian product of placement choices - which, with
    8+ annotations and a handful of levels, is far too large to enumerate.
    """
    config = (theme or default_theme()).annotations
    num_annotations = len(annotation_specs)
    baseline_y = eq_ink.baseline_y if eq_ink is not None else 0.0
    indices = list(range(1, num_annotations + 1))

    step = config.level_step_pt
    for num_levels in range(1, config.max_level_tiers + 1):
        # Regular, fixed-step grid of levels, tried innermost-first.
        levels_below = [config.first_level_below_pt + i * step for i in range(num_levels)]
        levels_above = [config.first_level_above_pt + i * step for i in range(num_levels)]

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
                            config,
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
            if visits > config.max_backtrack_visits:
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
                        if _obstacles_conflict(
                            label_rect, False, rectj, is_leaderj, config
                        ) or _obstacles_conflict(
                            leader_rect, True, rectj, is_leaderj, config
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

                if visits > config.max_backtrack_visits:
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


def build_annotation_draws(
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    above_placements: Dict[int, Tuple[float, str]],
    below_placements: Dict[int, Tuple[float, str]],
    theme: Optional[Theme] = None,
) -> List[AnnotationDraw]:
    """Turn chosen placements into the concrete lengths the template draws with.

    Above and below labels are mirror images of each other: the leader line, the
    highlight tint and the label offset all flip sign, which is why this is one
    function over a signed axis rather than two near-identical blocks.
    """
    theme = theme or default_theme()
    config = theme.annotations
    draws = []

    for index, (_exact, label) in enumerate(annotation_specs, 1):
        node = node_names.get(index)
        if node is None:
            continue
        if index in above_placements:
            side, (level, anchor) = "above", above_placements[index]
            stem_pt = config.stem_above_pt
            leader_pt = level
            label_offset_pt = level + config.above_label_offset_pt
            xshift = config.label_xshift_above
            yshift = f"{_number(config.label_nudge_pt)}pt"
            corner = "north"
        elif index in below_placements:
            side, (level, anchor) = "below", below_placements[index]
            stem_pt = -config.stem_below_pt
            leader_pt = -level
            label_offset_pt = level
            xshift = config.label_xshift_below
            yshift = f"-{_number(config.label_nudge_pt)}pt"
            corner = "south"
        else:
            continue

        if anchor == "base east":
            xshift = f"-{xshift}"

        draws.append(
            AnnotationDraw(
                node=node,
                side=side,
                text=label,
                corner=corner,
                stem_pt=stem_pt,
                leader_pt=leader_pt,
                label_offset_pt=label_offset_pt,
                anchor=anchor,
                xshift=xshift,
                yshift=yshift,
            )
        )

    return draws


def _number(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else str(value)
