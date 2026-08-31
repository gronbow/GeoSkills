"""Shared physical-size and raster resource contract for every diagram."""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Mapping


MIN_FIGURE_MM = 30.0
MAX_FIGURE_MM = 500.0
MIN_DPI = 72
MAX_DPI = 1200
# About 300 MiB for one 8-bit RGBA render buffer.  This still permits a
# 183 x 170 mm submission figure at 1200 dpi while blocking pathological
# multi-gigabyte requests before Matplotlib allocates them.
MAX_RASTER_PIXELS = 75_000_000

BUILTIN_STYLE_DEFAULTS: Mapping[str, Mapping[str, int | float | bool]] = (
    MappingProxyType(
        {
            "publication-double-column": MappingProxyType(
                {
                    "width_mm": 183.0,
                    "height_mm": 120.0,
                    "dpi": 600,
                    "show_reference_note": True,
                }
            ),
            "publication-single-column": MappingProxyType(
                {
                    "width_mm": 89.0,
                    "height_mm": 75.0,
                    "dpi": 600,
                    # Full provenance remains in the machine-readable report
                    # and QA summary.  Omitting the long canvas footnote keeps
                    # text legible at the actual 89 mm publication width.
                    "show_reference_note": False,
                }
            ),
            "review-preview": MappingProxyType(
                {
                    "width_mm": 150.0,
                    "height_mm": 100.0,
                    "dpi": 300,
                    "show_reference_note": True,
                }
            ),
        }
    )
)


def raster_dimensions(width_mm: float, height_mm: float, dpi: int) -> tuple[int, int]:
    """Return the conservative integer raster dimensions used for budgeting."""

    return (
        int(math.ceil(float(width_mm) / 25.4 * int(dpi))),
        int(math.ceil(float(height_mm) / 25.4 * int(dpi))),
    )


def raster_pixel_count(width_mm: float, height_mm: float, dpi: int) -> int:
    width_px, height_px = raster_dimensions(width_mm, height_mm, dpi)
    return width_px * height_px


def validate_style_contract(width_mm: float, height_mm: float, dpi: int) -> None:
    """Raise ``ValueError`` when dimensions or the render budget are unsafe."""

    if not (
        math.isfinite(float(width_mm))
        and math.isfinite(float(height_mm))
        and MIN_FIGURE_MM <= float(width_mm) <= MAX_FIGURE_MM
        and MIN_FIGURE_MM <= float(height_mm) <= MAX_FIGURE_MM
    ):
        raise ValueError("figure dimensions are outside the supported range")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError("raster resolution is outside the supported range")
    if raster_pixel_count(width_mm, height_mm, dpi) > MAX_RASTER_PIXELS:
        raise ValueError("raster render exceeds the fixed pixel budget")


__all__ = [
    "BUILTIN_STYLE_DEFAULTS",
    "MAX_DPI",
    "MAX_FIGURE_MM",
    "MAX_RASTER_PIXELS",
    "MIN_DPI",
    "MIN_FIGURE_MM",
    "raster_dimensions",
    "raster_pixel_count",
    "validate_style_contract",
]
