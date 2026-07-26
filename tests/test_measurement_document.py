"""The measurement document must reproduce the environment it measures for.

Every number the placement search uses (node positions, container edges, the
ink raster) is only valid in the geometry it was taken in, so these assert that
the geometry is actually built.
"""

import pytest

from autoslide.equations import create_measurement_document

SPECS = [("x", "First label")]
NODES = {1: "node1"}


def _document(**kwargs) -> str:
    latex, _ = create_measurement_document("x + y", SPECS, NODES, 0, **kwargs)
    return latex


def test_shares_the_real_preamble():
    latex = _document()
    # The margins that set \textwidth must match the real document's
    assert "text margin left=0.48cm" in latex
    assert "\\setmainfont{Fira Sans}" in latex


def test_reports_the_container_edges():
    latex = _document()
    assert "BOUNDLEFT" in latex and "BOUNDRIGHT" in latex
    assert "\\makebox[\\linewidth][s]" in latex


def test_slide_full_width_has_no_columns():
    latex = _document()
    assert "\\begin{columns}" not in latex
    assert "\\begin{block}" not in latex


def test_slide_sub_column_is_measured_in_a_column():
    latex = _document(has_columns=True)
    assert "\\begin{column}[t]{0.484\\textwidth}" in latex
    assert "\\begin{block}" not in latex


def test_poster_is_measured_in_a_poster_column():
    latex = _document(mode="poster")
    assert "beamerposter" in latex
    assert "size=a0" in latex
    assert "\\begin{column}[t]{0.484\\textwidth}" in latex


def test_poster_box_is_measured_inside_a_block():
    latex = _document(mode="poster", in_block=True)
    assert "\\begin{block}{}" in latex
    # The title bar sits outside the body, so it must not add ink
    assert "\\setbeamertemplate{block title}{}" in latex


def test_poster_sub_column_nests_inside_the_block():
    latex = _document(mode="poster", in_block=True, has_columns=True)
    body = latex[latex.index("\\begin{block}") :]
    assert "0.484\\textwidth" in body, "the -|- column must be measured inside the box"


def test_slide_measurement_is_not_a_poster():
    assert "beamerposter" not in _document()


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"has_columns": True},
        {"mode": "poster"},
        {"mode": "poster", "in_block": True},
        {"mode": "poster", "in_block": True, "has_columns": True},
    ],
)
def test_environments_are_balanced(kwargs):
    latex = _document(**kwargs)
    for environment in ("columns", "column", "block", "frame"):
        assert latex.count(f"\\begin{{{environment}}}") == latex.count(
            f"\\end{{{environment}}}"
        ), f"unbalanced {environment} for {kwargs}"
