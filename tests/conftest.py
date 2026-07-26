import pytest

from autoslide.parser import MarkdownBeamerParser


@pytest.fixture
def parse(monkeypatch):
    """Return a parse(text, **kwargs) factory. Figure generation is mocked out."""
    monkeypatch.setattr("autoslide.figures.generate_figure_file", lambda *a, **kw: None)

    def _parse(text, **kwargs):
        return MarkdownBeamerParser(**kwargs).parse(text)

    return _parse


@pytest.fixture
def render(parse, tmp_path):
    """Return a render(text, **renderer_kwargs) factory producing LaTeX."""
    from autoslide.renderer import PosterRenderer, SlideRenderer

    def _render(text, poster=False, **kwargs):
        slides = parse(text)
        renderer_class = PosterRenderer if poster else SlideRenderer
        renderer = renderer_class(output_dir=str(tmp_path), no_cache=True, **kwargs)
        return renderer.render_document(slides, "test")

    return _render
