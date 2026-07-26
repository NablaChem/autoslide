"""
Regression tests for find_optimal_placement.

These tests use real bounding-box / node-position measurements captured from the
two-column rendering of the PECD equation in bug.md (four annotated symbols:
beta_1, beta_2, theta, sigma).  In that geometry the algorithm previously could
not find a valid placement because levels_above was fixed at [20.0] even when
num_levels grew, forcing sigma and beta_2 to compete for the single above level
they could not share without overlapping.
"""

import pytest

from autoslide.equations import LabelBox, Measurements, find_optimal_placement
from autoslide.theme import default_theme

# ── fixture data captured from two-column measurement of the PECD equation ──

ANNOTATION_SPECS = [
    (r"\beta_1", "dichroic parameter"),
    (r"\beta_2", "anisotropy parameter"),
    (r"{\theta}", "Emission angle"),
    (r"{\sigma}", "Cross section"),
]

BOUNDING_BOXES = {
    1: LabelBox(67.992, 6.024, 1.6),   # beta_1  "dichroic parameter"
    2: LabelBox(77.256, 6.024, 1.6),   # beta_2  "anisotropy parameter"
    3: LabelBox(53.616, 6.024, 0.0),   # theta   "Emission angle"
    4: LabelBox(47.424, 6.024, 0.0),   # sigma   "Cross section"
}

NODE_POSITIONS = {
    1: 75.65079,    # beta_1
    2: 139.44284,   # beta_2
    3: 110.52939,   # theta
    4: 43.73169,    # sigma
}

NODE_NAMES = {1: "node3", 2: "node4", 3: "node1", 4: "node2"}

NODE_SHIFTS = {1: 0.0, 2: 0.0, 3: 0.0, 4: 6.26}   # sigma is above baseline

# The column the equation was measured in, in the same absolute page
# coordinates as the node positions above.
CONTENT_LEFT = 13.6
CONTENT_RIGHT = 220.5

PADDING_PT = default_theme().annotations.horizontal_padding_pt
CONTAINER_PADDING_PT = default_theme().annotations.container_padding_pt


def _measurements(**overrides) -> Measurements:
    values = dict(
        bounding_boxes=BOUNDING_BOXES,
        node_positions=NODE_POSITIONS,
        node_shifts=NODE_SHIFTS,
        eq_height=12.0,
        eq_depth=4.0,
        content_left_pt=CONTENT_LEFT,
        content_right_pt=CONTENT_RIGHT,
        page_width_pt=455.0,
        page_height_pt=256.0,
        baseline_y=100.0,
    )
    values.update(overrides)
    return Measurements(**values)


def _call(**overrides):
    return find_optimal_placement(
        ANNOTATION_SPECS, _measurements(**overrides), NODE_NAMES
    )


def _padded_bounds(i, anchor):
    x = NODE_POSITIONS[i]
    width = BOUNDING_BOXES[i].width + PADDING_PT
    return (x, x + width) if anchor == "base west" else (x - width, x)


# ── the placement must succeed (no fallback) ──────────────────────────────────

def test_two_column_placement_finds_solution():
    above, below = _call()
    # A successful placement has annotations on both sides; the fallback only
    # returns below placements with no above entries at all.
    assert above, "placement fell back to all-below (levels_above never grew)"


def test_sigma_placed_above():
    # sigma (spec 4) has node_shift > 0, so it must go above
    above, below = _call()
    assert 4 in above, "sigma must be placed above the equation"
    assert 4 not in below


def test_all_four_annotations_placed():
    above, below = _call()
    assert set(above) | set(below) == {1, 2, 3, 4}


def test_no_horizontal_overlap():
    """No two annotations at the same (side, level) should overlap."""
    above, below = _call()

    by_level: dict = {}
    for side, placements in (("above", above), ("below", below)):
        for i, (level, anchor) in placements.items():
            by_level.setdefault((side, level), []).append(_padded_bounds(i, anchor))

    for (side, level), rects in by_level.items():
        rects.sort()
        for (l1, r1), (l2, r2) in zip(rects, rects[1:]):
            assert r1 <= l2, (
                f"overlap at {side} level {level}: [{l1:.1f},{r1:.1f}] vs [{l2:.1f},{r2:.1f}]"
            )


def test_all_within_the_measured_container():
    above, below = _call()
    for i, (_, anchor) in {**above, **below}.items():
        left, right = _padded_bounds(i, anchor)
        assert left >= CONTENT_LEFT + CONTAINER_PADDING_PT, f"ann{i} overflows left"
        assert right <= CONTENT_RIGHT - CONTAINER_PADDING_PT, f"ann{i} overflows right"


def test_a_wider_container_allows_left_aligned_labels():
    """The fit check follows the measured container, not a fixed page width."""
    narrow = _call()
    wide = _call(content_left_pt=13.6, content_right_pt=441.4)

    def anchors(result):
        above, below = result
        return {i: anchor for i, (_, anchor) in {**above, **below}.items()}

    assert anchors(narrow) != anchors(wide), (
        "widening the container changed nothing - bounds are being ignored"
    )


def test_labels_that_cannot_fit_anywhere_fall_back():
    above, below = _call(content_left_pt=0.0, content_right_pt=20.0)
    # Nothing fits; the fallback places everything below rather than crashing.
    assert not above
    assert set(below) == {1, 2, 3, 4}
