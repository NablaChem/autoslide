"""Renderers: turn parsed blocks into LaTeX by feeding templates.

The split is deliberate and worth preserving:

* ``layout.py`` decides *what goes where* (sections, columns, poster bands),
* the block modules (``tables``, ``lists``, ``images``, ``equations``) decide
  *what a block means*,
* ``templates/`` decides *what it looks like*,
* this module only wires the three together and caches the result.

Nothing here should contain a LaTeX string.
"""

import sys
from dataclasses import dataclass
from typing import List, Optional

from . import code, equations, footnotes as footnotes_mod, icons, inline, templating
from .cache import OutputCache
from .images import image_spec
from .layout import (
    LayoutItem,
    PosterBox,
    build_poster_layout,
    build_slide_layout,
)
from .lists import parse_list
from .models import Block, BlockType
from .tables import parse_table
from .theme import Theme, default_theme


@dataclass
class Cover:
    title: str = ""
    author: str = ""
    affiliation: str = ""
    email: str = ""
    web: str = ""

    def __bool__(self) -> bool:
        return bool(
            self.title or self.author or self.affiliation or self.email or self.web
        )


#: ``:field:`` lines on a cover slide, and where they land on the Cover.
_COVER_FIELDS = {
    ":author:": "author",
    ":affiliation:": "affiliation",
    ":email:": "email",
    ":web:": "web",
}
#: These fields keep their ``:name:`` prefix on the value because it doubles
#: as ``:name:`` icon syntax (see ``icons.py``) once ``_contacts`` runs it
#: through the icon renderer.
_ICON_FIELDS = {"email", "web"}


def cover_metadata(blocks: List[Block]) -> Cover:
    """Read the title and ``:author:``/``:affiliation:``/``:email:``/``:web:``
    lines off a cover slide.

    The ``:email:``/``:web:`` prefixes are kept: they double as icon syntax.
    """
    cover = Cover()
    for block in blocks:
        if block.type == BlockType.TITLE_PAGE:
            cover.title = block.content
        elif block.type == BlockType.TEXT:
            for line in block.content.split("\n"):
                line = line.strip()
                for prefix, field in _COVER_FIELDS.items():
                    if line.startswith(prefix):
                        value = line[len(prefix) :].strip()
                        if field in _ICON_FIELDS:
                            setattr(cover, field, f"{prefix} {value}")
                        else:
                            setattr(cover, field, value)
    return cover


class SlideRenderer:
    """Renders a 16:9 beamer presentation."""

    mode = "slide"
    #: Image scaling tier to use outside / inside a two-column section.
    full_width_context = "slide"
    column_context = "column"
    #: Whether content sits inside a poster block (which insets its body).
    equations_in_block = False

    def __init__(
        self,
        output_dir: str = ".",
        no_cache: bool = False,
        tracing: bool = False,
        theme: Optional[Theme] = None,
        source_dir: Optional[str] = None,
    ):
        self.output_dir = output_dir
        self.tracing = tracing
        self.theme = theme or default_theme()
        self.engine = templating.engine(self.theme, source_dir, output_dir)
        self.node_counter = 0
        self.cache = OutputCache(
            output_dir=output_dir,
            fingerprint=self.engine.fingerprint(),
            # Tracing output is never cached: it exists to show the current run.
            read_enabled=not no_cache and not tracing,
            write_enabled=not tracing,
        )

    # -- documents ----------------------------------------------------

    def render_document(self, slides: List[List[Block]], title: str = "Presentation") -> str:
        frames = [self.render_slide(blocks) for blocks in slides]
        return self.engine.render(
            "slides/document.tex.j2",
            slides=[frame for frame in frames if frame],
            **self._preamble_context(slides),
        )

    def _preamble_context(self, slides: List[List[Block]]) -> dict:
        return {
            "mode": self.mode,
            "tracing": self.tracing,
            "pygments_styles": code.style_defs(),
        }

    # -- slides -------------------------------------------------------

    def render_slide(self, blocks: List[Block]) -> str:
        key = self.cache.key(blocks, mode=self.mode, tracing=self.tracing)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        latex = self._render_slide(blocks)
        self.cache.put(key, latex)
        return latex

    def _render_slide(self, blocks: List[Block]) -> str:
        types = {block.type for block in blocks}

        if BlockType.TITLE_PAGE in types:
            return self.render_title_page(blocks)
        if BlockType.SECTION in types:
            section = next(b for b in blocks if b.type == BlockType.SECTION)
            return self.engine.render("slides/section_slide.tex.j2", title=section.content)

        title_block = next((b for b in blocks if b.type == BlockType.SLIDE_TITLE), None)
        metadata = title_block.metadata if title_block else {}
        if metadata.get("hide_slide", False):
            return ""

        footline = next(
            (b.content for b in blocks if b.type == BlockType.FOOTLINE), ""
        )
        return self.engine.render(
            "slides/frame.tex.j2",
            title=title_block.content if title_block else "",
            frame_options=self._frame_options(types, footline),
            summary=bool(metadata.get("section_summary", False)),
            layout=build_slide_layout(blocks),
            render_block=self.render_block,
            footnotes=self._footnotes(blocks),
            width=self.theme.layout.footnote_width,
        )

    def _frame_options(self, types, footline: str) -> str:
        options = ["t"]
        if BlockType.CODE in types:
            options.append("fragile")  # Verbatim needs it
        if footline:
            options.append(footline)
        return f"[{','.join(options)}]"

    def render_title_page(self, blocks: List[Block]) -> str:
        cover = cover_metadata(blocks)
        return self.engine.render(
            "slides/title_page.tex.j2",
            title=cover.title,
            author=cover.author,
            contacts=self._contacts(cover),
        )

    #: Cover fields shown as contact icons under the title. Posters drop the
    #: email address - overridden in ``PosterRenderer``.
    _contact_fields = ("email", "web")

    def _contacts(self, cover: Cover) -> List[str]:
        return [
            icons.process_icons(value, self.output_dir, self.theme, self.engine)
            for value in (getattr(cover, field) for field in self._contact_fields)
            if value
        ]

    def _footnotes(self, blocks: List[Block]) -> footnotes_mod.FootnoteList:
        return footnotes_mod.collect_footnotes(
            [b for b in blocks if b.type == BlockType.FOOTNOTE]
        )

    # -- blocks -------------------------------------------------------

    def render_block(self, item: LayoutItem, has_columns: bool = False) -> str:
        """Render one block. Called from the layout template."""
        block = item.block
        renderer = self._BLOCK_RENDERERS.get(block.type)
        latex = renderer(self, item, has_columns) if renderer else block.content
        # Blocks never carry trailing whitespace: vertical spacing between
        # blocks is the layout template's business, not a block's.
        latex = latex.rstrip()

        if self.tracing and block.type != BlockType.CODE:
            # Verbatim can't live inside tcolorbox, so code blocks stay bare.
            latex = self.engine.render_block("blocks/tracing.tex.j2", content=latex)
        return latex

    def _render_text(self, item: LayoutItem, has_columns: bool) -> str:
        return inline.format_inline(item.block.content)

    def _render_list(self, item: LayoutItem, has_columns: bool) -> str:
        layout = self.theme.layout
        return self.engine.render_block(
            "blocks/list.tex.j2",
            list=parse_list(item.block.content),
            trailing_break=(
                layout.compact_list_break_before_list
                if item.followed_by_list
                else layout.compact_list_break
            ),
        )

    def _render_table(self, item: LayoutItem, has_columns: bool) -> str:
        table = parse_table(item.block.content, self.theme)
        if table is None:
            return item.block.content
        return self.engine.render_block("blocks/table.tex.j2", table=table)

    def _render_image(self, item: LayoutItem, has_columns: bool) -> str:
        context = self.column_context if has_columns else self.full_width_context
        return self.engine.render_block(
            "blocks/image.tex.j2",
            image=image_spec(item.block, context, self.theme),
        )

    def _render_code(self, item: LayoutItem, has_columns: bool) -> str:
        return code.format_code(
            item.block.content, item.block.metadata.get("language", "text")
        )

    def _render_equation(self, item: LayoutItem, has_columns: bool) -> str:
        latex, self.node_counter = equations.render_annotated_equation(
            item.block,
            self.engine,
            has_columns,
            self.node_counter,
            self.output_dir,
            mode=self.mode,
            in_block=self.equations_in_block,
        )
        return latex

    _BLOCK_RENDERERS = {
        BlockType.TEXT: _render_text,
        BlockType.LIST: _render_list,
        BlockType.TABLE: _render_table,
        BlockType.IMAGE: _render_image,
        BlockType.CODE: _render_code,
        BlockType.ANNOTATED_EQUATION: _render_equation,
    }


class PosterRenderer(SlideRenderer):
    """Renders an A0 portrait poster.

    ``###`` boxes become ``block`` environments, ``=|=``/``===`` control the
    two-column bands, and ``-|-``/``---`` keep working inside a box exactly as
    they do on a slide.
    """

    mode = "poster"
    full_width_context = "poster"
    column_context = "poster"
    equations_in_block = True
    #: The poster header shows the affiliation instead of an email address.
    _contact_fields = ("web",)

    def render_document(self, slides: List[List[Block]], title: str = "") -> str:
        cover = next(
            (
                cover_metadata(slide)
                for slide in slides
                if any(b.type == BlockType.TITLE_PAGE for b in slide)
            ),
            Cover(),
        )
        groups, warnings = build_poster_layout(slides)
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)

        has_code = any(
            block.type == BlockType.CODE for slide in slides for block in slide
        )
        return self.engine.render(
            "poster/document.tex.j2",
            title=cover.title,
            author=cover.author,
            affiliation=cover.affiliation,
            contacts=self._contacts(cover),
            frame_options="[t,fragile]" if has_code else "[t]",
            groups=groups,
            render_box=self.render_box,
            **self._preamble_context(slides),
        )

    def render_box(self, box: PosterBox) -> str:
        key = self.cache.key(
            [item.block for section in box.layout.sections
             for column in section.columns for item in column.items],
            mode=self.mode,
            tracing=self.tracing,
            title=box.title,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        latex = self.engine.render(
            "poster/box.tex.j2",
            box=box,
            layout=box.layout,
            render_block=self.render_block,
            footnotes=footnotes_mod.collect_footnotes(box.footnotes),
            width="\\linewidth",
        )
        self.cache.put(key, latex)
        return latex

