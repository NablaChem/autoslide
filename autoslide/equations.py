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
from dataclasses import dataclass, replace as dataclasses_replace
from typing import List, Dict, NamedTuple, Tuple, Optional

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
    mode: str = "slide",
    in_block: bool = False,
) -> Tuple[str, int]:
    """Render an equation block, placing any annotations. Returns (latex, counter).

    ``mode``/``in_block``/``has_columns`` describe where the equation will be
    typeset; annotations are measured in exactly that environment.
    """
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

    base_above = theme.annotations.base_above_vspace_pt
    base_below = theme.annotations.base_below_vspace_pt

    # If no annotations, render as simple equation
    if not annotation_specs:
        return _render(equation_content, [], base_above, base_below), node_counter

    # Create tikzmarknode-wrapped equation
    annotated_equation, node_names, node_counter = create_tikzmarknode_equation_new(
        equation_content, annotation_specs, node_counter,
        annotation_source_lines=annotation_source_lines,
        source_filename=source_filename,
    )

    # Determine optimal placement for annotations
    heading_hint = f" [{heading[:40]}]" if heading else ""
    print(f"Placing annotations for equation{heading_hint}", file=sys.stderr, flush=True)
    above_placements, below_placements, above_vspace_pt, below_vspace_pt, config = (
        determine_annotation_placement(
            annotated_equation, annotation_specs, node_names, has_columns, node_counter,
            output_dir, equation_content=equation_content, theme=theme,
            mode=mode, in_block=in_block,
        )
    )

    draws = build_annotation_draws(
        annotation_specs, node_names, above_placements, below_placements, config=config
    )
    if not draws:
        return _render(annotated_equation, [], base_above, base_below), node_counter

    return (
        _render(
            annotated_equation,
            draws,
            max(above_vspace_pt, base_above),
            max(below_vspace_pt, base_below),
        ),
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


class LabelBox(NamedTuple):
    """A typeset label, measured about its own baseline."""

    width: float
    height: float  # above the baseline
    depth: float  # below it


def scale_for_label_size(measurements: "Measurements", config):
    r"""Scale the vertical geometry to the label size actually measured.

    The pt constants were chosen against slide-sized annotation text. The same
    ``\scriptsize`` label on an A0 poster is ~2.5x taller, and leaving a 15pt
    first level would draw it straight through the equation. The median label
    height is used, so one unusually tall label doesn't stretch the whole grid.
    """
    heights = [box.height for box in measurements.bounding_boxes.values() if box.height > 0]
    if not heights or config.reference_label_height_pt <= 0:
        return config
    measured = sorted(heights)[len(heights) // 2]
    factor = measured / config.reference_label_height_pt
    if 0.95 < factor < 1.05:
        return config  # slide-sized: leave the tuned values alone
    factor = max(0.5, min(10.0, factor))
    return dataclasses_replace(
        config,
        clearance_pt=config.clearance_pt * factor,
        leader_half_width_pt=config.leader_half_width_pt * factor,
        leader_clearance_pt=config.leader_clearance_pt * factor,
        first_level_below_pt=config.first_level_below_pt * factor,
        first_level_above_pt=config.first_level_above_pt * factor,
        level_step_pt=config.level_step_pt * factor,
        container_padding_pt=config.container_padding_pt * factor,
        horizontal_padding_pt=config.horizontal_padding_pt * factor,
        stem_above_pt=config.stem_above_pt * factor,
        stem_below_pt=config.stem_below_pt * factor,
        above_label_offset_pt=config.above_label_offset_pt * factor,
        label_nudge_pt=config.label_nudge_pt * factor,
    )


def label_geometry(side: str, level: float, config) -> Tuple[float, float]:
    """Where a label at ``level`` actually ends up.

    Returns (tikz ``above=``/``below=`` distance, signed offset of the label's
    own baseline from the node's, y growing downwards). The placement search and
    the drawing code both read this, so what is checked is what is drawn - TikZ
    anchors the label by its *baseline*, so a "below" label grows back up
    towards the equation rather than away from it.
    """
    if side == "above":
        distance = level + config.above_label_offset_pt
        return distance, -(distance + config.label_nudge_pt)
    distance = level
    return distance, distance + config.label_nudge_pt


@dataclass
class Measurements:
    """Everything the measurement pass reports, in absolute page pt.

    All of it comes from one compiled page, so the coordinates are mutually
    consistent: node positions, container edges and the ink raster can be
    compared directly without any assumed page or column width.
    """

    #: annotation index -> the measured box of its typeset label
    bounding_boxes: Dict[int, LabelBox]
    #: annotation index -> x of the marked symbol
    node_positions: Dict[int, float]
    #: annotation index -> y offset of the marked symbol from the baseline
    node_shifts: Dict[int, float]
    #: the equation's own extent above/below its math baseline
    eq_height: float
    eq_depth: float
    #: x of the left/right edge of the container the equation sits in
    content_left_pt: float
    content_right_pt: float
    page_width_pt: float
    page_height_pt: float
    baseline_y: float
    ink: Optional["ink.EquationInk"] = None


def determine_annotation_placement(
    equation_with_nodes: str,
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    has_columns: bool = False,
    node_counter: int = 0,
    output_dir: str = ".",
    equation_content: str = "",
    theme: Optional[Theme] = None,
    mode: str = "slide",
    in_block: bool = False,
) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]], float, float, object]:
    """Place every annotation, measuring in the environment it will end up in.

    ``mode``/``in_block``/``has_columns`` describe that environment: an A0
    poster box is a very different width from a slide sub-column, and a label
    that fits one will overflow the other.

    Returns:
        (above_placements, below_placements, above_vspace_pt, below_vspace_pt,
        config) - the config is the type-size-scaled one the placements were
        computed with, and the drawing code must use the same.
    """
    theme = theme or default_theme()
    if not annotation_specs:
        return {}, {}, 0.0, 0.0, theme.annotations

    config = theme.annotations

    # Step 1: measure the equation, its labels and its container
    try:
        measurements = measure_annotation_bounding_boxes(
            equation_with_nodes, annotation_specs, node_names, node_counter,
            output_dir, has_columns, equation_content=equation_content,
            theme=theme, mode=mode, in_block=in_block,
        )
    except Exception as e:
        print(f"Error measuring bounding boxes: {e}", file=sys.stderr)
        print(f"Equation: {equation_with_nodes}", file=sys.stderr)
        print(f"Annotations: {annotation_specs}", file=sys.stderr)
        raise

    # Step 2: scale the vertical grid to the type size we just measured, then
    # search for a placement that fits inside the measured container
    config = scale_for_label_size(measurements, config)
    above_placements, below_placements = find_optimal_placement(
        annotation_specs, measurements, node_names, config=config
    )

    # Step 3: Compute the tight vspace needed beyond the equation's own natural
    # typeset extent, using exactly the same geometry (baseline_y, node_shifts,
    # bounding_boxes, chosen level/anchor) the placement search itself used - no
    # separate heuristic buffer, no em-per-pt approximation. eq_height/eq_depth
    # are the equation's own natural extent above/below its baseline (from a
    # plain \ht/\dp box measurement, so unaffected by the page-coordinate sign
    # convention); annotations only need extra room for whatever they add
    # beyond that natural extent.
    baseline_y = measurements.baseline_y
    natural_top_y = baseline_y - measurements.eq_height
    natural_bottom_y = baseline_y + measurements.eq_depth

    # The same minimum gap used everywhere else in this module to keep labels
    # from touching other ink - applying it here too means a label's far edge
    # isn't flush against whatever block follows the equation.
    def _label_edges(index: int, side: str, level: float) -> Tuple[float, float]:
        box = measurements.bounding_boxes.get(index)
        if box is None:
            return natural_top_y, natural_bottom_y
        node_y = baseline_y - measurements.node_shifts.get(index, 0.0)
        _distance, baseline_offset = label_geometry(side, level, config)
        label_baseline_y = node_y + baseline_offset
        return (
            label_baseline_y - box.height - config.clearance_pt,
            label_baseline_y + box.depth + config.clearance_pt,
        )

    top_needed_y = min(
        [natural_top_y]
        + [_label_edges(i, "above", level)[0] for i, (level, _) in above_placements.items()]
    )
    bottom_needed_y = max(
        [natural_bottom_y]
        + [_label_edges(i, "below", level)[1] for i, (level, _) in below_placements.items()]
    )

    return (
        above_placements,
        below_placements,
        max(0.0, natural_top_y - top_needed_y),
        max(0.0, bottom_needed_y - natural_bottom_y),
        config,
    )


def measure_annotation_bounding_boxes(
    equation_with_nodes: str,
    annotation_specs: List[Tuple[str, str]],
    node_names: Dict[int, str],
    node_counter: int,
    output_dir: str = ".",
    has_columns: bool = False,
    equation_content: str = "",
    theme: Optional[Theme] = None,
    mode: str = "slide",
    in_block: bool = False,
) -> Measurements:
    """Compile the measurement document and read its log (and its raster).

    The ink mask comes from rasterising the compiled page, so irregular
    protrusions (big operators, lowered subscripts) collide with labels exactly
    where they visually would.
    """
    theme = theme or default_theme()

    # Compile inside the output directory so relative asset paths still resolve
    temp_dir = tempfile.mkdtemp(dir=output_dir)

    try:
        measurement_latex, _ = create_measurement_document(
            equation_with_nodes, annotation_specs, node_names, node_counter, has_columns,
            equation_content=equation_content,
            engine=templating.engine(theme),
            mode=mode,
            in_block=in_block,
        )

        temp_tex_path = os.path.join(temp_dir, "measurement.tex")
        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(measurement_latex)

        # Empty navigation file to satisfy beamer
        with open(os.path.join(temp_dir, "measurement.nav"), "w") as f:
            f.write("")

        n = len(annotation_specs)
        where = "poster box" if in_block else ("column" if has_columns else mode)
        print(
            f"  Measuring annotation layout ({n} annotation{'s' if n != 1 else ''}, {where})...",
            file=sys.stderr, flush=True,
        )
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

        measurements = parse_measurements_from_log(
            os.path.join(temp_dir, "measurement.log"), len(annotation_specs)
        )

        if measurements.page_height_pt > 0:
            try:
                measurements.ink = ink.build_equation_ink(
                    os.path.join(temp_dir, "measurement.pdf"),
                    measurements.baseline_y,
                    theme.annotations.ink_dpi,
                    theme.annotations.clearance_pt,
                    page_size_pt=(measurements.page_width_pt, measurements.page_height_pt),
                    max_megapixels=theme.annotations.ink_max_megapixels,
                )
            except Exception as e:
                print(f"Warning: could not build equation ink mask: {e}", file=sys.stderr)

        return measurements

    finally:
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
    mode: str = "slide",
    in_block: bool = False,
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
        mode=mode,
        in_block=in_block,
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


def parse_measurements_from_log(log_path: str, num_annotations: int) -> Measurements:
    """Read every \typeout the measurement document emitted.

    Missing values fall back to something harmless and warn: a failed
    measurement should degrade placement, not abort the build.
    """
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        log_content = f.read()

    def _find(pattern: str, label: str, default):
        match = re.search(pattern, log_content)
        if match:
            return tuple(float(group) for group in match.groups())
        print(f"Warning: Could not find {label} measurement", file=sys.stderr)
        return default

    (baseline_x, baseline_y) = _find(
        r"BASELINEPOS: x=([0-9.-]+)pt, y=([0-9.-]+)pt", "baseline position", (0.0, 0.0)
    )
    (page_width_pt, page_height_pt) = _find(
        r"PAGESIZE: width=([0-9.]+)pt, height=([0-9.]+)pt", "page size", (0.0, 0.0)
    )
    (eq_height,) = _find(
        r"EQMEASURE: height=([0-9.]+)pt", "equation height (EQMEASURE)", (0.0,)
    )
    (eq_depth,) = _find(
        r"EQMEASURE: height=[0-9.]+pt, depth=([0-9.]+)pt", "equation depth (EQMEASURE)", (0.0,)
    )
    (content_left_pt,) = _find(
        r"BOUNDLEFT: x=([0-9.-]+)pt", "container left edge", (0.0,)
    )
    (content_right_pt,) = _find(
        r"BOUNDRIGHT: x=([0-9.-]+)pt", "container right edge", (page_width_pt,)
    )

    bounding_boxes = {}
    node_positions = {}
    node_shifts = {}
    for i in range(1, num_annotations + 1):
        bounding_boxes[i] = LabelBox(*_find(
            f"ANNOTATION{i}: width=([0-9.]+)pt, height=([0-9.]+)pt, depth=([0-9.]+)pt",
            f"annotation {i}",
            (50.0, 12.0, 3.0),  # a plausible label size, so placement can continue
        ))

        match = re.search(f"NODEPOS{i}: x=([0-9.-]+)pt, y=([0-9.-]+)pt", log_content)
        if match:
            node_positions[i] = float(match.group(1))
            # Page y grows downwards, so subtract the other way round to keep
            # the convention the placement search reads: positive means the
            # marked symbol sits *above* the baseline (a superscript).
            node_shifts[i] = baseline_y - float(match.group(2))

    return Measurements(
        bounding_boxes=bounding_boxes,
        node_positions=node_positions,
        node_shifts=node_shifts,
        eq_height=eq_height,
        eq_depth=eq_depth,
        content_left_pt=content_left_pt,
        content_right_pt=content_right_pt,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        baseline_y=baseline_y,
    )


def _annotation_option_obstacles(
    i: int,
    position: str,
    level: float,
    anchor: str,
    measurements: "Measurements",
    config=None,
):
    """Build (label_rect, leader_rect) for one candidate (position, level, anchor)
    placement of annotation i, checked in isolation (forced side, container edge,
    equation ink). Returns None if this option is invalid regardless of what else
    is placed. Returns (None, None) if there's nothing to check (no measured
    geometry for this annotation) - such an option never conflicts with anything."""
    config = config or default_theme().annotations
    bounding_boxes = measurements.bounding_boxes
    node_positions = measurements.node_positions
    node_shifts = measurements.node_shifts
    baseline_y = measurements.baseline_y

    if node_shifts[i] < 0 and position == "above":
        return None
    if node_shifts[i] > 0 and position == "below":
        return None
    if i not in bounding_boxes or i not in node_positions:
        return (None, None)

    # The container's real edges, measured in the same coordinate system as the
    # nodes - so this check means the same thing on a slide, in a -|- column and
    # in an A0 poster box.
    left_limit = measurements.content_left_pt + config.container_padding_pt
    right_limit = measurements.content_right_pt - config.container_padding_pt

    box = bounding_boxes[i]
    node_x = node_positions[i]
    padded_width = box.width + config.horizontal_padding_pt

    # Only the label's growing edge (away from the node) is a placement choice
    # and gets checked; the anchor-side edge is just the symbol's own fixed
    # position, which annotation placement has no control over.
    if anchor == "base west":  # Left-aligned text extends right from node
        left_bound = node_x
        right_bound = node_x + padded_width
        if right_bound > right_limit:
            return None
    else:  # "base east" - Right-aligned text extends left from node
        left_bound = node_x - padded_width
        right_bound = node_x
        if left_bound < left_limit:
            return None

    # Everything here is in page coordinates with y growing downwards (the same
    # frame ink.pt_to_px indexes the raster in), so "above" is a smaller y.
    node_y = baseline_y - node_shifts[i]
    _distance, baseline_offset = label_geometry(position, level, config)
    label_baseline_y = node_y + baseline_offset
    top = label_baseline_y - box.height
    bottom = label_baseline_y + box.depth

    label_rect = (left_bound, right_bound, top, bottom)

    if measurements.ink is not None and ink.equation_ink_overlaps_rect(
        measurements.ink, left_bound, right_bound, bottom, top
    ):
        return None

    # The leader line runs from the symbol to the near edge of the label.
    near_y = top if position == "above" else bottom
    leader_rect = (
        node_x - config.leader_half_width_pt,
        node_x + config.leader_half_width_pt,
        min(node_y, near_y),
        max(node_y, near_y),
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
    measurements: "Measurements",
    node_names: Dict[int, str],
    theme: Optional[Theme] = None,
    config=None,
) -> Tuple[Dict[int, Tuple[float, str]], Dict[int, Tuple[float, str]]]:
    """Find optimal placement using a pruned backtracking search over a fixed,
    regularly-spaced grid of levels.

    Annotations are free to end up above or below the equation (whichever a given
    node's position allows). Options are tried cheapest-level-first and a
    branch-and-bound cutoff on total vertical space keeps the search from ever
    materializing the full cartesian product of placement choices - which, with
    8+ annotations and a handful of levels, is far too large to enumerate.
    """
    config = config or (theme or default_theme()).annotations
    num_annotations = len(annotation_specs)
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
                            i, position, level, anchor, measurements, config
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
    config=None,
) -> List[AnnotationDraw]:
    """Turn chosen placements into the concrete lengths the template draws with.

    Above and below labels are mirror images of each other: the leader line, the
    highlight tint and the label offset all flip sign, which is why this is one
    function over a signed axis rather than two near-identical blocks.

    ``config`` must be the same (type-size-scaled) one the placement search used
    - the distances here are what makes the drawing match what was checked.
    """
    config = config or (theme or default_theme()).annotations
    draws = []

    for index, (_exact, label) in enumerate(annotation_specs, 1):
        node = node_names.get(index)
        if node is None:
            continue
        if index in above_placements:
            side, (level, anchor) = "above", above_placements[index]
            stem_pt = config.stem_above_pt
            leader_pt = level
            label_offset_pt, _offset = label_geometry(side, level, config)
            xshift = config.label_xshift_above
            yshift = f"{_number(config.label_nudge_pt)}pt"
            corner = "north"
        elif index in below_placements:
            side, (level, anchor) = "below", below_placements[index]
            stem_pt = -config.stem_below_pt
            leader_pt = -level
            label_offset_pt, _offset = label_geometry(side, level, config)
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
