import os
import tempfile
import subprocess
from .models import BlockType


def generate_figure_file(
    code: str, block_type: BlockType, filename: str, has_columns: bool = False
):
    """Generate a single figure file with the specified parameters."""
    # Create Python script for subplot execution
    python_script = create_matplotlib_script(
        code, block_type, filename, has_columns
    )

    # Write script to temporary file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as temp_file:
        temp_file.write(python_script)
        temp_script_path = temp_file.name

    try:
        # Execute Python script using subprocess
        result = subprocess.run(
            ["python", temp_script_path],
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
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


def create_matplotlib_script(
    user_code: str,
    block_type: BlockType,
    output_filename: str,
    has_columns: bool = False,
) -> str:
    """Create complete Python script for matplotlib figure generation."""

    # Determine figure parameters based on layout FIRST
    if has_columns:
        # Two-column layout: 4:3 aspect ratio with standard sizes
        figsize = "(8, 6)"
    else:
        # Single-column layout: 16:9 aspect ratio
        figsize = "(10, 5.625)"  # 16:9 aspect ratio

    font_size = "16"
    label_size = "25"
    tick_size = "18"
    line_width = "2"
    marker_size = "12"
    spine_width = "3"
    # Configure schematic vs plot styling
    if block_type == BlockType.SCHEMATIC:
        style_config = f"""
# Configure for schematic (no tick marks, thick axes in navy blue)
ncblue = '#0A2D64'  # Navy blue color from beamer theme
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
ncblue = '#0A2D64'  # Navy blue color from beamer theme
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
plt.rcParams['lines.linewidth'] = {line_width}
plt.rcParams['lines.markersize'] = {marker_size}

# Set default label positions to axis ends
plt.rcParams['xaxis.labellocation'] = 'right'
plt.rcParams['yaxis.labellocation'] = 'top'

# User code
{user_code}

{style_config}

# Save figure
plt.tight_layout()
plt.savefig('{output_filename}', format='pdf', bbox_inches='tight', dpi=300)
plt.close()
"""
    return script