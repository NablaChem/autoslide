import pytest
from autoslide.parser import MarkdownBeamerParser
from autoslide.generator import BeamerGenerator


@pytest.fixture
def generate(monkeypatch, tmp_path):
    monkeypatch.setattr("autoslide.figures.generate_figure_file", lambda *a, **kw: None)

    def _generate(text, tracing=False):
        slides = MarkdownBeamerParser().parse(text)
        return BeamerGenerator(output_dir=str(tmp_path), tracing=tracing).generate_beamer(slides)

    return _generate


def test_tracing_adds_tcolorbox(generate):
    latex = generate("### Slide ###\nHello world", tracing=True)
    assert r"\begin{tcolorbox}" in latex


def test_no_tracing_omits_tcolorbox(generate):
    latex = generate("### Slide ###\nHello world", tracing=False)
    assert r"\begin{tcolorbox}" not in latex


def test_tracing_wraps_list_block(generate):
    latex = generate("### Slide ###\n- item one\n- item two", tracing=True)
    assert r"\begin{tcolorbox}" in latex


def test_tracing_does_not_wrap_code_block(generate):
    latex = generate("### Slide ###\n```python\nprint('hi')\n```", tracing=True)
    assert r"\begin{tcolorbox}" not in latex


def test_tracing_includes_tcolorbox_package(generate):
    latex = generate("### Slide ###\nHello world", tracing=True)
    assert r"\usepackage{tcolorbox}" in latex


def test_no_tracing_omits_tcolorbox_package(generate):
    latex = generate("### Slide ###\nHello world", tracing=False)
    assert r"\usepackage{tcolorbox}" not in latex
