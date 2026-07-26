"""Template overriding and the cache invalidation that depends on it."""

import os

import pytest

from autoslide import templating
from autoslide.cache import OutputCache
from autoslide.models import Block, BlockType
from autoslide.renderer import SlideRenderer
from autoslide.theme import Colors, default_theme


@pytest.fixture(autouse=True)
def _fresh_engines():
    templating.reset()
    yield
    templating.reset()


def _write_override(root, relative_path, content):
    path = os.path.join(root, "autoslide-templates", relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(content)


def test_user_template_replaces_builtin(tmp_path, parse):
    _write_override(
        str(tmp_path),
        "slides/section_slide.tex.j2",
        "MY SECTION: << title >>\n",
    )
    slides = parse("## Methods")
    latex = SlideRenderer(
        output_dir=str(tmp_path), no_cache=True, source_dir=str(tmp_path)
    ).render_document(slides)
    assert "MY SECTION: Methods" in latex
    assert "background canvas" not in latex


def test_override_can_extend_the_builtin_and_replace_one_block(tmp_path, parse):
    _write_override(
        str(tmp_path),
        "blocks/table.tex.j2",
        '<% extends "autoslide/blocks/table.tex.j2" %>\n'
        "<% block rows %>ROWS REDACTED\n<% endblock %>\n",
    )
    slides = parse("### Slide ###\n| A | B |\n| - | - |\n| x | y |")
    latex = SlideRenderer(
        output_dir=str(tmp_path), no_cache=True, source_dir=str(tmp_path)
    ).render_document(slides)
    assert "ROWS REDACTED" in latex
    assert "\\begin{tabular}" in latex  # header block still from the builtin
    assert "x & y" not in latex


def test_env_var_template_dir(tmp_path, parse, monkeypatch):
    override_dir = tmp_path / "shared"
    (override_dir / "slides").mkdir(parents=True)
    (override_dir / "slides" / "section_slide.tex.j2").write_text("ENV << title >>\n")
    monkeypatch.setenv("AUTOSLIDE_TEMPLATES", str(override_dir))
    latex = SlideRenderer(output_dir=str(tmp_path), no_cache=True).render_document(
        parse("## Methods")
    )
    assert "ENV Methods" in latex


def test_fingerprint_changes_with_user_template(tmp_path):
    before = templating.TemplateEngine(source_dir=str(tmp_path)).fingerprint()
    _write_override(str(tmp_path), "blocks/table.tex.j2", "nothing\n")
    after = templating.TemplateEngine(source_dir=str(tmp_path)).fingerprint()
    assert before != after


def test_fingerprint_changes_with_theme():
    other = default_theme().replace(colors=Colors(primary="myblue"))
    assert (
        templating.TemplateEngine().fingerprint()
        != templating.TemplateEngine(theme=other).fingerprint()
    )


def test_cache_key_depends_on_fingerprint():
    blocks = [Block(BlockType.TEXT, "hello")]
    assert OutputCache(fingerprint="a").key(blocks) != OutputCache(
        fingerprint="b"
    ).key(blocks)


def test_cache_roundtrip(tmp_path):
    cache = OutputCache(output_dir=str(tmp_path), fingerprint="x")
    key = cache.key([Block(BlockType.TEXT, "hello")])
    assert cache.get(key) is None
    cache.put(key, "LATEX")
    reopened = OutputCache(output_dir=str(tmp_path), fingerprint="x")
    assert reopened.get(key) == "LATEX"


def test_theme_colour_reaches_the_output(tmp_path, parse):
    theme = default_theme().replace(
        colors=Colors(definitions={"hotpink": (255, 0, 255)}, primary="hotpink")
    )
    latex = SlideRenderer(
        output_dir=str(tmp_path), no_cache=True, theme=theme
    ).render_document(parse("### Slide ###\nHeading\n- a\n- b"))
    assert "\\definecolor{hotpink}{RGB}{255,0,255}" in latex
    assert "\\textcolor{hotpink}" in latex
    assert "ncblue" not in latex
