"""
Raster-based ink extraction for equation annotation placement.

Rather than reasoning about a single global (height, depth) bounding box for an
equation, we rasterize the actual compiled page and read off which pixels are
truly ink. Big operators, lowered subscripts, and other irregular protrusions
then collide with annotation labels exactly where they visually would, instead
of only when they exceed a single declared box dimension.
"""

import math
import os
import subprocess
from typing import NamedTuple, Tuple

import numpy as np
from PIL import Image

PT_PER_INCH = 72.0


class EquationInk(NamedTuple):
    """Dilated ink mask for one equation plus the coordinate metadata needed to
    map pt-space rectangles (as used elsewhere in the placement code) onto it."""

    mask: np.ndarray
    dpi: float
    baseline_y: float


def rasterize_pdf_page(pdf_path: str, dpi: int, page: int = 1) -> np.ndarray:
    """Rasterize one page of a PDF to a grayscale numpy array (0=black, 255=white)."""
    out_dir = os.path.dirname(pdf_path)
    out_prefix = os.path.join(out_dir, "ink_raster")
    subprocess.run(
        [
            "pdftoppm",
            "-png",
            "-r", str(dpi),
            "-f", str(page),
            "-l", str(page),
            pdf_path,
            out_prefix,
        ],
        check=True,
        capture_output=True,
    )
    # pdftoppm appends a page-number suffix (e.g. -1.png or -01.png depending on page count)
    prefix_name = os.path.basename(out_prefix)
    candidates = [
        f for f in os.listdir(out_dir)
        if f.startswith(prefix_name) and f.endswith(".png")
    ]
    if not candidates:
        raise RuntimeError(f"pdftoppm did not produce output for {pdf_path}")
    image_path = os.path.join(out_dir, sorted(candidates)[0])
    with Image.open(image_path) as img:
        gray = np.array(img.convert("L"))
    return gray


def binary_ink_mask(gray: np.ndarray, threshold: int = 250) -> np.ndarray:
    """True where a pixel is ink (darker than threshold)."""
    return gray < threshold


def _disk_footprint(radius_px: int) -> np.ndarray:
    if radius_px <= 0:
        return np.array([[True]])
    y, x = np.ogrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    return (x * x + y * y) <= radius_px * radius_px


def dilate_mask(mask: np.ndarray, radius_px: int) -> np.ndarray:
    """Expand ink by radius_px in every direction (disk-shaped, i.e. Minkowski buffer)."""
    if radius_px <= 0:
        return mask
    from scipy.ndimage import binary_dilation

    return binary_dilation(mask, structure=_disk_footprint(radius_px))


def pt_to_px(x_pt: float, y_pt: float, dpi: float) -> Tuple[int, int]:
    """Convert a page coordinate to (row, col) pixel indices in a rasterized page.

    Coordinates are offsets from the top-left corner of the paper with y growing
    downwards - which is what the measurement document reports, by subtracting
    ``(current page.north west)`` from every position it measures. Reading a
    node's coordinate directly instead would give a position relative to the
    enclosing tikzpicture and land these lookups on the wrong part of the page.
    """
    scale = dpi / PT_PER_INCH
    col = int(round(x_pt * scale))
    row = int(round(y_pt * scale))
    return row, col


def fit_dpi(page_size_pt: Tuple[float, float], dpi: int, max_megapixels: float) -> int:
    """Lower ``dpi`` until the rasterised page fits in ``max_megapixels``.

    An A0 poster page is ~35x the area of a 16:9 slide, so rasterising it at
    slide resolution would cost hundreds of megapixels (and a dilation pass
    over all of them). Poster type is proportionally larger, so the coarser
    raster resolves the same features.
    """
    width_pt, height_pt = page_size_pt
    area_sq_in = (width_pt / PT_PER_INCH) * (height_pt / PT_PER_INCH)
    if area_sq_in <= 0 or max_megapixels <= 0:
        return int(dpi)
    # An integer dpi keeps pt_to_px in step with how pdftoppm rounds the raster.
    return max(24, min(int(dpi), int(math.sqrt(max_megapixels * 1e6 / area_sq_in))))


def build_equation_ink(
    pdf_path: str,
    baseline_y: float,
    dpi: int,
    clearance_pt: float,
    page_size_pt: Tuple[float, float] = None,
    max_megapixels: float = 0.0,
) -> EquationInk:
    """Rasterize the compiled equation page and return a pre-dilated ink mask."""
    if page_size_pt:
        dpi = fit_dpi(page_size_pt, dpi, max_megapixels)
    gray = rasterize_pdf_page(pdf_path, dpi=dpi)
    mask = binary_ink_mask(gray)
    radius_px = int(round(clearance_pt * dpi / PT_PER_INCH))
    dilated = dilate_mask(mask, radius_px)
    return EquationInk(mask=dilated, dpi=dpi, baseline_y=baseline_y)


def region_has_ink(
    mask: np.ndarray,
    dpi: float,
    x0_pt: float,
    x1_pt: float,
    y0_pt: float,
    y1_pt: float,
) -> bool:
    """Check whether any ink pixel falls within the given pt-space rectangle."""
    if x1_pt < x0_pt:
        x0_pt, x1_pt = x1_pt, x0_pt
    if y1_pt < y0_pt:
        y0_pt, y1_pt = y1_pt, y0_pt

    row_bottom, col_left = pt_to_px(x0_pt, y0_pt, dpi)
    row_top, col_right = pt_to_px(x1_pt, y1_pt, dpi)

    row0, row1 = sorted((row_top, row_bottom))
    col0, col1 = sorted((col_left, col_right))

    row0 = max(0, row0)
    col0 = max(0, col0)
    row1 = min(mask.shape[0], row1 + 1)
    col1 = min(mask.shape[1], col1 + 1)

    if row0 >= row1 or col0 >= col1:
        return False

    return bool(mask[row0:row1, col0:col1].any())


def equation_ink_overlaps_rect(
    eq_ink: EquationInk, x0_pt: float, x1_pt: float, y0_pt: float, y1_pt: float
) -> bool:
    """Check whether a page-absolute pt rectangle overlaps the equation's ink.

    x/y here are absolute "current page" coordinates (same system as the node
    positions/shifts already used elsewhere in the placement code), not
    relative to the baseline.
    """
    return region_has_ink(eq_ink.mask, eq_ink.dpi, x0_pt, x1_pt, y0_pt, y1_pt)
