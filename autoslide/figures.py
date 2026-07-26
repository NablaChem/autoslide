import os
import sys
import hashlib
import json
import tempfile
import subprocess
from .models import BlockType


def compute_figure_hash(code: str, block_type: BlockType, has_columns: bool, is_poster: bool = False) -> str:
    """Hash all inputs that determine the figure's visual output."""
    data = json.dumps(
        {
            "code": code,
            "block_type": block_type.value,
            "has_columns": has_columns,
            "is_poster": is_poster,
            "style": {k: list(v) if isinstance(v, tuple) else v for k, v in PLOT_STYLE.items()},
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()


def generate_figure_file(
    code: str,
    block_type: BlockType,
    filename: str,
    has_columns: bool = False,
    output_dir: str = ".",
    is_poster: bool = False,
):
    """Generate a single figure file with the specified parameters."""
    if "figsize" in code:
        print(
            f"{filename}: Warning: plot code passes its own figsize, overriding the "
            "canvas size autoslide otherwise keeps consistent across figures - this "
            "may lead to inconsistent layout.",
            file=sys.stderr,
        )

    # Create Python script for subplot execution (filename relative to output_dir)
    python_script = create_matplotlib_script(code, block_type, filename, has_columns, is_poster)

    # Write script to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
        temp_file.write(python_script)
        temp_script_path = temp_file.name

    try:
        # Execute Python script using subprocess
        result = subprocess.run(
            ["python", temp_script_path],
            capture_output=True,
            text=True,
            cwd=output_dir,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Error generating figure {filename} ({block_type.value}):\n"
                f"Code:\n{code}\n\n"
                f"Error output:\n{result.stderr}"
            )
        elif result.stderr:
            print(f"{filename}: {result.stderr.strip()}", file=sys.stderr)

    finally:
        # Clean up temporary script
        try:
            os.unlink(temp_script_path)
        except OSError:
            pass


# Centralized plot styling configuration
PLOT_STYLE = {
    # Figure sizes
    "figsize_single_column": (11, 5.625),  # widened from 16:9 to fill more of the slide width
    "figsize_two_column": (5.8, 5.625),  # same height as figsize_single_column, so tick/label/legend
    # sizes (set as absolute point sizes below) come out at the same size relative to the plot on
    # both single- and two-column slides - the two are scaled to the same final on-slide height
    # (both bound by the same height_limit fraction in theme.ImageScaling), so equal source heights
    # give equal effective font sizes. Width is chosen to fill the column width without becoming the
    # binding constraint itself (which would break that equality).
    "figsize_poster_single": (14, 10),  # A0 half-column, no sub-columns
    "figsize_poster_columns": (8, 8),  # A0 half-column with -|- sub-columns
    # Font sizes (doubled for better readability)
    "font_size": 20,  # General font size
    "label_size": 25,  # Axis labels
    "tick_size": 25,  # Tick labels
    "legend_size": 25,  # Legend font size
    # Line and marker sizes
    "line_width": 2,
    "marker_size": 12,
    "spine_width": 1,
    # Colors
    "ncblue": "#0A2D64",  # Navy blue color from beamer theme
    # Legend styling
    "legend_frame": False,  # No frame around legend
    "legend_framealpha": 0.0,  # Transparent background
}


def create_matplotlib_script(
    user_code: str,
    block_type: BlockType,
    output_filename: str,
    has_columns: bool = False,
    is_poster: bool = False,
) -> str:
    """Create complete Python script for matplotlib figure generation."""

    # Determine figure parameters based on layout
    if is_poster:
        figsize = str(PLOT_STYLE["figsize_poster_columns" if has_columns else "figsize_poster_single"])
    elif has_columns:
        figsize = str(PLOT_STYLE["figsize_two_column"])
    else:
        figsize = str(PLOT_STYLE["figsize_single_column"])

    # Extract style parameters
    font_size = str(PLOT_STYLE["font_size"])
    label_size = str(PLOT_STYLE["label_size"])
    tick_size = str(PLOT_STYLE["tick_size"])
    legend_size = str(PLOT_STYLE["legend_size"])
    line_width = str(PLOT_STYLE["line_width"])
    marker_size = str(PLOT_STYLE["marker_size"])
    spine_width = str(PLOT_STYLE["spine_width"])
    ncblue = PLOT_STYLE["ncblue"]
    # Configure schematic vs plot styling
    if block_type == BlockType.SCHEMATIC:
        style_config = f"""
# Configure for schematic (no tick marks, thick axes in navy blue)
# Applied to every panel, so multi-panel figures (e.g. from plt.subplots) stay consistent
ncblue = '{ncblue}'
for ax in plt.gcf().get_axes():
    ax.spines['left'].set_linewidth({spine_width})
    ax.spines['left'].set_color(ncblue)
    ax.spines['bottom'].set_linewidth({spine_width})
    ax.spines['bottom'].set_color(ncblue)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Set axis label colors to navy blue
    ax.xaxis.label.set_color(ncblue)
    ax.yaxis.label.set_color(ncblue)

    # Remove all ticks
    ax.set_xticks([])
    ax.set_yticks([])
"""
    else:  # PLOT
        style_config = f"""
# Configure for plot (with tick marks, thick axes in navy blue)
# Applied to every panel, so multi-panel figures (e.g. from plt.subplots) stay consistent
ncblue = '{ncblue}'
for ax in plt.gcf().get_axes():
    ax.spines['left'].set_linewidth({spine_width})
    ax.spines['left'].set_color(ncblue)
    ax.spines['bottom'].set_linewidth({spine_width})
    ax.spines['bottom'].set_color(ncblue)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Set axis label colors to navy blue
    ax.xaxis.label.set_color(ncblue)
    ax.yaxis.label.set_color(ncblue)

    # Keep tick marks for plots with navy blue color, as thick as the axis lines
    ax.tick_params(axis='both', which='major', direction='out', width={spine_width}, length=6, colors=ncblue)
"""

    script = f"""
import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend

# Configure matplotlib with layout-specific parameters.
# Set as the default figure size (rather than calling plt.figure() here) so
# that the canvas stays consistent no matter how the user creates the figure -
# plt.plot(...), or plt.subplots(rows, cols) for a multi-panel figure - as
# long as they don't pass their own figsize.
plt.rcParams['figure.figsize'] = {figsize}

# Note: deliberately not using constrained_layout - it reserves per-axes
# padding for in-axes legends, which can shrink the plotted area a lot more
# on a multi-panel figure (one reservation per panel) than on a single-panel
# one. plt.tight_layout() below plus a savefig() with no bbox_inches='tight'
# keeps this predictable: the saved canvas always comes out at the declared
# figsize, so a plot with one panel and a plot with several panels (e.g. via
# plt.subplots(1, 3)) end up with the same aspect ratio and the same fraction
# of the canvas actually used for plotting.

# Set font to match beamer (Fira Sans Extra Condensed if available, fallback to sans-serif)
try:
    plt.rcParams['font.family'] = ['Fira Sans Extra Condensed', 'DejaVu Sans', 'sans-serif']
except:
    plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['mathtext.fontset'] = 'custom'
plt.rcParams['mathtext.it'] = 'Fira Sans Extra Condensed:italic'
plt.rcParams['mathtext.default'] = 'regular'

plt.rcParams['font.size'] = {font_size}
plt.rcParams['axes.labelsize'] = {label_size}
plt.rcParams['xtick.labelsize'] = {tick_size}
plt.rcParams['ytick.labelsize'] = {tick_size}
plt.rcParams['legend.fontsize'] = {legend_size}
plt.rcParams['lines.linewidth'] = {line_width}
plt.rcParams['lines.markersize'] = {marker_size}

# Set default label positions to axis ends
plt.rcParams['xaxis.labellocation'] = 'right'
plt.rcParams['yaxis.labellocation'] = 'top'

# Configure legend styling (no frame by default)
plt.rcParams['legend.frameon'] = False
plt.rcParams['legend.framealpha'] = 0.0
plt.rcParams['legend.handletextpad'] = 0.1
plt.rcParams['legend.handlelength'] = 1.0

# Tick direction and size, matching plotstyle.py
plt.rcParams['xtick.direction'] = 'out'
plt.rcParams['ytick.direction'] = 'out'
plt.rcParams['xtick.major.size'] = 4
plt.rcParams['ytick.major.size'] = 4
plt.rcParams['xtick.minor.size'] = 2
plt.rcParams['ytick.minor.size'] = 2

# User code
{user_code}

{style_config}

# A figure/subplots call in the user code above starts a fresh figure; only
# the last one created gets saved below, so anything drawn on an earlier one
# is silently dropped. Warn (but don't fail) so the user notices.
if len(plt.get_fignums()) > 1:
    print(
        "Warning: plot code created more than one matplotlib figure; "
        "only the last one is saved, which may lead to inconsistent layout.",
        file=sys.stderr,
    )

# Save figure at the exact configured figsize (see note above - no bbox_inches='tight')
plt.tight_layout()
plt.savefig('{output_filename}', format='pdf', dpi=300)
plt.close()
"""
    return script
