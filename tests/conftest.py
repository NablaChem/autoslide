import pytest
from autoslide.parser import MarkdownBeamerParser


@pytest.fixture
def parse(monkeypatch):
    """Return a parse(text, **kwargs) factory. Figure generation is mocked out."""
    monkeypatch.setattr("autoslide.figures.generate_figure_file", lambda *a, **kw: None)

    def _parse(text, **kwargs):
        return MarkdownBeamerParser(**kwargs).parse(text)

    return _parse
