"""Annotation geometry: above and below must stay exact mirror images."""

import pytest

from autoslide.equations import build_annotation_draws
from autoslide.theme import default_theme

SPECS = [("x", "First"), ("y", "Second")]
NODES = {1: "node1", 2: "node2"}


def _draw(above=None, below=None):
    return build_annotation_draws(SPECS, NODES, above or {}, below or {})


def test_above_and_below_mirror_each_other():
    config = default_theme().annotations
    above = _draw(above={1: (20.0, "base west")})[0]
    below = _draw(below={1: (20.0, "base west")})[0]

    assert above.stem_pt == config.stem_above_pt
    assert below.stem_pt == -config.stem_below_pt
    assert above.leader_pt == 20.0
    assert below.leader_pt == -20.0
    assert (above.corner, below.corner) == ("north", "south")
    assert above.yshift == "3pt" and below.yshift == "-3pt"


def test_above_label_sits_closer_than_its_leader_ends():
    draw = _draw(above={1: (20.0, "base west")})[0]
    assert draw.label_offset_pt < draw.leader_pt


def test_below_label_offset_matches_the_level():
    draw = _draw(below={2: (15.0, "base east")})[0]
    assert draw.label_offset_pt == 15.0


def test_east_anchor_shifts_the_other_way():
    west = _draw(below={1: (15.0, "base west")})[0]
    east = _draw(below={1: (15.0, "base east")})[0]
    assert east.xshift == f"-{west.xshift}"


def test_unplaced_annotations_are_dropped():
    assert len(_draw(above={1: (20.0, "base west")})) == 1


def test_order_follows_the_source_order():
    draws = _draw(above={2: (20.0, "base west")}, below={1: (15.0, "base west")})
    assert [d.text for d in draws] == ["First", "Second"]


# ── the drawn geometry must be the geometry that was checked ────────────────

def test_drawn_distance_matches_the_checked_geometry():
    """build_annotation_draws and the placement search read one helper."""
    from autoslide.equations import label_geometry

    config = default_theme().annotations
    for side, placements in (
        ("above", {1: (20.0, "base west")}),
        ("below", {1: (15.0, "base west")}),
    ):
        draw = build_annotation_draws(
            SPECS, NODES, placements if side == "above" else {},
            placements if side == "below" else {},
        )[0]
        distance, _offset = label_geometry(side, placements[1][0], config)
        assert draw.label_offset_pt == distance


def test_below_labels_grow_back_towards_the_equation():
    """TikZ anchors a label by its baseline, so 'below' text extends upward."""
    from autoslide.equations import label_geometry

    config = default_theme().annotations
    _distance, offset = label_geometry("below", 15.0, config)
    # The label's baseline is below the node; its text occupies the space
    # *above* that baseline, i.e. between the node and the offset.
    assert 0 < offset
    assert offset - config.label_nudge_pt == 15.0


def test_label_scale_leaves_slide_sized_labels_alone():
    from autoslide.equations import LabelBox, Measurements, scale_for_label_size

    config = default_theme().annotations
    slide = Measurements(
        bounding_boxes={1: LabelBox(50.0, config.reference_label_height_pt, 1.0)},
        node_positions={1: 100.0}, node_shifts={1: 0.0},
        eq_height=10.0, eq_depth=3.0,
        content_left_pt=0.0, content_right_pt=400.0,
        page_width_pt=455.0, page_height_pt=256.0, baseline_y=100.0,
    )
    assert scale_for_label_size(slide, config) is config


def test_label_scale_grows_the_grid_for_poster_sized_labels():
    from autoslide.equations import LabelBox, Measurements, scale_for_label_size

    config = default_theme().annotations
    poster = Measurements(
        bounding_boxes={1: LabelBox(150.0, 15.0, 3.0)},  # 2.5x a slide label
        node_positions={1: 1000.0}, node_shifts={1: 0.0},
        eq_height=60.0, eq_depth=45.0,
        content_left_pt=600.0, content_right_pt=1750.0,
        page_width_pt=2393.0, page_height_pt=3383.0, baseline_y=227.0,
    )
    scaled = scale_for_label_size(poster, config)
    assert scaled.first_level_below_pt == pytest.approx(config.first_level_below_pt * 2.5)
    assert scaled.stem_above_pt == pytest.approx(config.stem_above_pt * 2.5)
    assert scaled.clearance_pt == pytest.approx(config.clearance_pt * 2.5)
