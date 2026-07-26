"""Theme: the single source of truth for every colour, font and dimension.

Nothing in the codebase should contain a hardcoded colour name, length or
scaling factor - templates and layout code read them from here instead. That
makes a restyle a one-file change and keeps the *measurement* document used for
annotation placement dimensionally identical to the document it measures for.

A user can override any of it by dropping an ``autoslide_theme.py`` next to
their markdown that defines ``theme = default_theme().replace(...)``; see
``templating.user_template_dirs`` for where that file is looked up.
"""

import json
import hashlib
from dataclasses import dataclass, field, replace, asdict
from typing import Dict, Tuple


@dataclass(frozen=True)
class Colors:
    """LaTeX colour names plus the RGB values they are defined with.

    ``definitions`` is what ends up in ``\\definecolor``; the other fields name
    the *role* a colour plays so templates never hardcode ``ncblue``.
    """

    definitions: Dict[str, Tuple[int, int, int]] = field(
        default_factory=lambda: {
            "ncblue": (10, 45, 100),
            "ncorange": (221, 150, 51),
            "navyblue": (221, 150, 51),
        }
    )
    primary: str = "ncblue"
    accent: str = "ncorange"
    section_title: str = "navyblue"
    muted: str = "gray"
    on_primary: str = "white"

    # Tints derived from ``primary``. Kept as explicit strings so a theme can
    # point them at an entirely different colour if it wants to.
    node_fill: str = "ncblue!15"
    table_header_bg: str = "ncblue!20"
    table_row_bg: str = "ncblue!10"
    icon_bg: str = "ncblue!20"


@dataclass(frozen=True)
class Fonts:
    main: str = "Fira Sans"
    main_options: str = (
        "UprightFont = *-Light,\n"
        "  BoldFont = *,\n"
        "  ItalicFont = *-Light Italic,\n"
        "  BoldItalicFont = * Italic"
    )
    mono: str = "Fira Mono"
    code_size: str = "\\small"
    annotation_size: str = "\\scriptsize"
    poster_title_size: str = "\\fontsize{72}{80}\\selectfont"
    title_size: str = "\\huge"
    section_title_size: str = "\\Huge"


@dataclass(frozen=True)
class Layout:
    """Lengths shared by the real documents and the measurement document."""

    aspect_ratio: str = "169"
    text_margin: str = "0.48cm"
    #: Width of one half of a two-column section, as a fraction of \textwidth.
    column_width: float = 0.484
    #: Height of the content minipage, as a fraction of \textheight.
    content_height: float = 0.88
    #: Pulls content up under the frame title bar.
    content_raise: str = "-1.5em"
    summary_content_shift: str = "-0.3em"
    title_content_raise: str = "-2.5em"
    title_content_indent: str = "2em"
    section_gap: str = "1em"
    contact_gap: str = "2em"
    parskip: str = "1.5em"
    itemize_margins: Tuple[str, str, str] = ("1em", "2em", "3em")
    itemize_raise: str = "-0.3em"
    #: Line break after a single-item list; widened when another list follows.
    compact_list_break: str = "0pt"
    compact_list_break_before_list: str = "0.5em"
    footnote_width: str = "0.95\\paperwidth"
    table_rule_width: str = "1.33pt"
    table_column_spec: str = "l"
    #: Number of data rows per shading cycle, and how many of them are shaded.
    table_shade_cycle: int = 4
    table_shade_from: int = 2
    frame_title_height: str = "2.5ex"
    frame_title_depth: str = "1ex"
    frame_title_padding: str = "1em"


@dataclass(frozen=True)
class PosterLayout:
    paper_size: str = "a0"
    orientation: str = "portrait"
    scale: str = "1.4"
    margin: str = "1cm"
    block_title_padding: str = "1em"
    block_title_depth: str = "0.5em"
    block_title_strut: str = "1.5em"
    box_gap: str = "0.5em"
    footnote_gap: str = "0.3em"
    title_rule_gap: str = "0.5em"
    #: LaTeX's default \hrule height (0.4pt) is barely visible at A0 size.
    title_rule_width: str = "1mm"
    #: Section headings measured ~1.2x smaller than desired relative to page
    #: width when compared against a reference underline+icon poster style;
    #: this scales the block title font up to match.
    heading_scale: str = "0.56"
    heading_rule_width: str = "1pt"
    heading_rule_gap: str = "0.3em"
    #: beamerposter's "scale" grows \normalsize faster than \scriptsize (LaTeX's
    #: size table isn't linear), so annotation labels end up smaller relative to
    #: body text than on slides. This restores the slide's label:body ratio.
    annotation_scale: str = "1.4"


@dataclass(frozen=True)
class ImageScaling:
    """(width x \\linewidth, height x \\textheight, vertical shift in em)."""

    slide: Tuple[float, float, float] = (1.5, 0.76, 0.0)
    column: Tuple[float, float, float] = (1.0, 0.76, -0.5)
    poster: Tuple[float, float, float] = (0.95, 0.55, 0.0)


@dataclass(frozen=True)
class Icons:
    circle_radius: str = "0.72em"
    glyph_size: str = "1.08em"
    #: Shifts the icon left by half the circle diameter.
    lead_shift: str = "-0.36em"
    color: str = "#0A2D64"
    aliases: Dict[str, str] = field(
        default_factory=lambda: {"email": "envelope", "web": "globe"}
    )


@dataclass(frozen=True)
class Annotations:
    """Geometry of the equation-annotation placement search and its output."""

    ink_dpi: int = 300
    #: Caps the ink raster so an A0 poster page doesn't blow up memory; the
    #: effective dpi is lowered to fit (poster text is proportionally larger).
    ink_max_megapixels: float = 12.0
    #: Minimum vertical gap kept above/below an equation regardless of
    #: annotations, so a plain equation and an annotated one leave the same
    #: outer margin to the surrounding text. Annotation geometry only ever
    #: widens this floor, never shrinks it.
    base_above_vspace_pt: float = 2.0
    base_below_vspace_pt: float = 6.0
    clearance_pt: float = 2.0
    leader_half_width_pt: float = 2.0
    leader_clearance_pt: float = 1.5
    first_level_below_pt: float = 13.0
    first_level_above_pt: float = 12.0
    level_step_pt: float = 5.0
    max_level_tiers: int = 8
    #: Safety valve against pathological inputs in the placement search.
    max_backtrack_visits: int = 500_000

    # How much of the container a label may occupy. The container's own edges
    # are measured, not assumed - see templates/measure/document.tex.j2.
    #: Breathing room between a label and the edge of its container.
    container_padding_pt: float = 3.0
    #: Slack added to a label's own width before the fit check.
    horizontal_padding_pt: float = 10.0

    #: Label height these pt values were chosen against. The whole vertical
    #: grid is scaled by (measured label height / this), so an A0 poster - where
    #: the same \scriptsize label is 2.5x taller - gets proportional spacing.
    reference_label_height_pt: float = 6.0

    #: Gap between the marked symbol and where the leader line starts.
    stem_above_pt: float = 12.0
    stem_below_pt: float = 5.0
    #: The label sits this much closer to the equation than its leader line ends.
    above_label_offset_pt: float = -5.0
    label_nudge_pt: float = 3.0
    label_xshift_above: str = "0.2em"
    label_xshift_below: str = "2pt"
    line_width: str = "0.4mm"
    node_inner_sep: str = "1pt"


@dataclass(frozen=True)
class Theme:
    colors: Colors = field(default_factory=Colors)
    fonts: Fonts = field(default_factory=Fonts)
    layout: Layout = field(default_factory=Layout)
    poster: PosterLayout = field(default_factory=PosterLayout)
    images: ImageScaling = field(default_factory=ImageScaling)
    icons: Icons = field(default_factory=Icons)
    annotations: Annotations = field(default_factory=Annotations)

    def replace(self, **groups) -> "Theme":
        """Return a copy with whole groups swapped, e.g. ``replace(colors=...)``."""
        return replace(self, **groups)

    def fingerprint(self) -> str:
        """Stable hash of every theme value - feeds the output cache key."""
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, default=str).encode()
        ).hexdigest()


_DEFAULT = Theme()


def default_theme() -> Theme:
    return _DEFAULT
