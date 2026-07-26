"""Jinja2 environment for the LaTeX templates.

Every piece of LaTeX autoslide emits comes from a template in
``autoslide/templates/``. Delimiters are chosen not to collide with LaTeX:

======================  ==================
``<% ... %>``           statements (if/for/block)
``<< ... >>``           expressions
``<# ... #>``           comments
======================  ==================

Overriding templates
--------------------
Any template can be replaced by dropping a file with the same relative name
into a user template directory (searched first, in this order):

1. ``$AUTOSLIDE_TEMPLATES`` (``:``-separated list of directories)
2. ``<directory of the markdown file>/autoslide-templates``
3. ``~/.config/autoslide/templates``

The built-in versions stay reachable under the ``autoslide/`` prefix, so an
override normally only replaces one named block::

    <# my-talk/autoslide-templates/slides/frame.tex.j2 #>
    <% extends "autoslide/slides/frame.tex.j2" %>
    <% block footnotes %>
    \\parbox[t]{\\textwidth}{\\tiny << footnotes_latex >>}
    <% endblock %>

Templates are also fingerprinted into the output cache key, so editing one
invalidates cached LaTeX instead of silently serving the old layout.
"""

import os
import hashlib
from typing import Dict, Iterable, List, Optional

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PrefixLoader, StrictUndefined

from . import inline as inline_mod
from .theme import Theme, default_theme

BUILTIN_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

#: Prefix under which the built-in templates stay reachable from an override.
BUILTIN_PREFIX = "autoslide"


def user_template_dirs(source_dir: Optional[str] = None) -> List[str]:
    """Directories searched for user template overrides, highest priority first."""
    dirs = []
    env_dirs = os.environ.get("AUTOSLIDE_TEMPLATES", "")
    dirs.extend(d for d in env_dirs.split(os.pathsep) if d)
    if source_dir:
        dirs.append(os.path.join(source_dir, "autoslide-templates"))
    dirs.append(os.path.expanduser("~/.config/autoslide/templates"))
    return [d for d in dirs if os.path.isdir(d)]


class TemplateEngine:
    """Renders named templates with the theme always in scope."""

    def __init__(
        self,
        theme: Optional[Theme] = None,
        source_dir: Optional[str] = None,
        output_dir: str = ".",
    ):
        self.theme = theme or default_theme()
        self.output_dir = output_dir
        self.user_dirs = user_template_dirs(source_dir)
        builtin = FileSystemLoader(BUILTIN_TEMPLATE_DIR)
        self.env = Environment(
            loader=ChoiceLoader(
                [
                    FileSystemLoader(self.user_dirs),
                    builtin,
                    PrefixLoader({BUILTIN_PREFIX: builtin}, delimiter="/"),
                ]
            ),
            block_start_string="<%",
            block_end_string="%>",
            variable_start_string="<<",
            variable_end_string=">>",
            comment_start_string="<#",
            comment_end_string="#>",
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            undefined=StrictUndefined,
            autoescape=False,
        )
        self.env.globals["theme"] = self.theme
        self.env.filters["inline"] = inline_mod.format_inline
        self.env.filters["icons"] = self._render_icons
        self.env.filters["num"] = _format_number

    def render(self, template_name: str, **context) -> str:
        return self.env.get_template(template_name).render(**context)

    def render_block(self, template_name: str, **context) -> str:
        """Render a block template.

        Trailing newlines are dropped: whether a block ends a LaTeX paragraph is
        the block's decision, not an artefact of how the template file ends.
        """
        return self.render(template_name, **context).rstrip("\n")

    def _render_icons(self, text: str) -> str:
        from . import icons  # deferred: icons renders through this engine

        return icons.process_icons(text, self.output_dir, self.theme, self)

    def fingerprint(self) -> str:
        """Hash of the theme plus every template file that could be loaded."""
        digest = hashlib.sha256()
        digest.update(self.theme.fingerprint().encode())
        for directory in [*self.user_dirs, BUILTIN_TEMPLATE_DIR]:
            for path in sorted(_walk_templates(directory)):
                digest.update(os.path.relpath(path, directory).encode())
                with open(path, "rb") as handle:
                    digest.update(handle.read())
        return digest.hexdigest()


def _walk_templates(directory: str) -> Iterable[str]:
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name.endswith(".j2"):
                yield os.path.join(root, name)


def _format_number(value: float) -> str:
    """Render floats without a trailing ``.0`` so lengths stay readable."""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


_ENGINES: Dict[tuple, TemplateEngine] = {}


def engine(
    theme: Optional[Theme] = None,
    source_dir: Optional[str] = None,
    output_dir: str = ".",
) -> TemplateEngine:
    """Cached engine for a (theme, source_dir, output_dir) triple."""
    key = ((theme or default_theme()).fingerprint(), source_dir or "", output_dir)
    if key not in _ENGINES:
        _ENGINES[key] = TemplateEngine(theme, source_dir, output_dir)
    return _ENGINES[key]


def reset() -> None:
    """Drop cached engines - call after editing templates in a long-lived process."""
    _ENGINES.clear()
