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
from autoslide.equations import find_optimal_placement

# ── fixture data captured from two-column measurement of the PECD equation ──

ANNOTATION_SPECS = [
    (r"\beta_1", "dichroic parameter"),
    (r"\beta_2", "anisotropy parameter"),
    (r"{\theta}", "Emission angle"),
    (r"{\sigma}", "Cross section"),
]

BOUNDING_BOXES = {
    1: (67.992, 6.024),   # beta_1  "dichroic parameter"
    2: (77.256, 6.024),   # beta_2  "anisotropy parameter"
    3: (53.616, 6.024),   # theta   "Emission angle"
    4: (47.424, 6.024),   # sigma   "Cross section"
}

NODE_POSITIONS = {
    1: 75.65079,    # beta_1
    2: 139.44284,   # beta_2
    3: 110.52939,   # theta
    4: 43.73169,    # sigma
}

NODE_NAMES = {1: "node3", 2: "node4", 3: "node1", 4: "node2"}

NODE_SHIFTS = {1: 0.0, 2: 0.0, 3: 0.0, 4: 6.26}   # sigma is above baseline

PAGE_WIDTH_PT = 217.5
PADDING_PT = 10.0


def _call(has_columns=True):
    return find_optimal_placement(
        ANNOTATION_SPECS,
        BOUNDING_BOXES,
        NODE_POSITIONS,
        NODE_NAMES,
        PAGE_WIDTH_PT,
        PADDING_PT,
        NODE_SHIFTS,
        has_columns=has_columns,
    )


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
    placed = set(above) | set(below)
    assert placed == {1, 2, 3, 4}


def test_no_horizontal_overlap():
    """No two annotations at the same (side, level) should overlap."""
    above, below = _call()

    def padded_bounds(i, anchor):
        x = NODE_POSITIONS[i]
        pw = BOUNDING_BOXES[i][0] + PADDING_PT
        return (x, x + pw) if anchor == "base west" else (x - pw, x)

    by_level: dict = {}
    for i, (lv, anch) in above.items():
        by_level.setdefault(("above", lv), []).append(padded_bounds(i, anch))
    for i, (lv, anch) in below.items():
        by_level.setdefault(("below", lv), []).append(padded_bounds(i, anch))

    for (side, lv), rects in by_level.items():
        rects.sort()
        for (l1, r1), (l2, r2) in zip(rects, rects[1:]):
            assert r1 <= l2, (
                f"overlap at {side} level {lv}: [{l1:.1f},{r1:.1f}] vs [{l2:.1f},{r2:.1f}]"
            )


def test_all_within_page_bounds():
    above, below = _call()
    left_margin = 5.0

    def padded_bounds(i, anchor):
        x = NODE_POSITIONS[i]
        pw = BOUNDING_BOXES[i][0] + PADDING_PT
        return (x, x + pw) if anchor == "base west" else (x - pw, x)

    for i, (_, anch) in {**above, **below}.items():
        lb, rb = padded_bounds(i, anch)
        assert lb >= left_margin, f"ann{i} left bound {lb:.1f} < margin {left_margin}"
        assert rb <= PAGE_WIDTH_PT, f"ann{i} right bound {rb:.1f} > page width {PAGE_WIDTH_PT}"
