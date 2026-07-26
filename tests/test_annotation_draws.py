"""Annotation geometry: above and below must stay exact mirror images."""

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
