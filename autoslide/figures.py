import os
import tempfile
import subprocess
from .models import BlockType


def generate_figure_file(
    code: str,
    block_type: BlockType,
    filename: str,
    has_columns: bool = False,
    output_dir: str = ".",
):
    """Generate a single figure file with the specified parameters."""
    # Create Python script for subplot execution (filename relative to output_dir)
    python_script = create_matplotlib_script(code, block_type, filename, has_columns)

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

    finally:
        # Clean up temporary script
        try:
            os.unlink(temp_script_path)
        except OSError:
            pass


# Centralized plot styling configuration
PLOT_STYLE = {
    # Figure sizes
    "figsize_single_column": (10, 5.625),  # 16:9 aspect ratio
    "figsize_two_column": (8, 8),  # 4:3 aspect ratio
    # Font sizes (doubled for better readability)
    "font_size": 20,  # General font size
    "label_size": 25,  # Axis labels
    "tick_size": 25,  # Tick labels
    "legend_size": 25,  # Legend font size
    # Line and marker sizes
    "line_width": 2,
    "marker_size": 12,
    "spine_width": 3,
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
) -> str:
    """Create complete Python script for matplotlib figure generation."""

    # Determine figure parameters based on layout
    if has_columns:
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
ncblue = '{ncblue}'
ax = plt.gca()
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
ncblue = '{ncblue}'
ax = plt.gca()
ax.spines['left'].set_linewidth({spine_width})
ax.spines['left'].set_color(ncblue)
ax.spines['bottom'].set_linewidth({spine_width})
ax.spines['bottom'].set_color(ncblue)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

# Set axis label colors to navy blue
ax.xaxis.label.set_color(ncblue)
ax.yaxis.label.set_color(ncblue)

# Keep tick marks for plots with navy blue color
plt.tick_params(axis='both', which='major', width=2, length=6, colors=ncblue)
"""

    script = f"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend

# Configure matplotlib with layout-specific parameters
plt.figure(figsize={figsize})

# Set font to match beamer (Fira Sans if available, fallback to sans-serif)
try:
    plt.rcParams['font.family'] = ['Fira Sans', 'DejaVu Sans', 'sans-serif']
except:
    plt.rcParams['font.family'] = 'sans-serif'

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

# User code
{user_code}

{style_config}

# Save figure
plt.tight_layout()
plt.savefig('{output_filename}', format='pdf', bbox_inches='tight', dpi=300)
plt.close()
"""
    return script
