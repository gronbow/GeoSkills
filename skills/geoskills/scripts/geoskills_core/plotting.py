"""Local, reusable Matplotlib styling for GeoSkills figures.

The helpers in this module deliberately avoid mutating ``matplotlib.rcParams``
at import time.  A plotter opts into a controlled preset for the lifetime of a
``with`` block, and Matplotlib restores the caller's settings afterwards.
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from functools import wraps
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, ParamSpec, Sequence, TypeVar

import matplotlib as mpl


P = ParamSpec("P")
R = TypeVar("R")


class PlotStyleError(ValueError):
    """Raised when a requested shared plotting style is invalid."""


# Preserve the established v0.3 visual vocabulary while moving it out of an
# individual diagram implementation.  Tuples prevent accidental in-place edits.
GROUP_COLORS = (
    "#3569A8",
    "#D06B27",
    "#159A80",
    "#A84F7A",
    "#7655A5",
    "#8B6B4A",
    "#4D4D4D",
    "#4F9BC1",
)
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "<", ">", "h", "p", "*")
LINE_STYLES = ("-", "--", "-.", ":")
FORMATS = ("svg", "pdf", "tiff", "png")
SANS_SERIF_FONT_STACK = (
    "Arial",
    "Helvetica",
    "DejaVu Sans",
    "Liberation Sans",
    "sans-serif",
)

PUBLICATION_DOUBLE_COLUMN = "publication-double-column"
PUBLICATION_SINGLE_COLUMN = "publication-single-column"
REVIEW_PREVIEW = "review-preview"

_PUBLICATION_DOUBLE_COLUMN_RCPARAMS: Mapping[str, Any] = MappingProxyType(
    {
        "font.family": "sans-serif",
        "font.sans-serif": list(SANS_SERIF_FONT_STACK),
        "font.size": 7.0,
        "axes.labelsize": 7.0,
        "axes.linewidth": 0.7,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "xtick.labelsize": 7.0,
        "ytick.labelsize": 7.0,
        "xtick.major.width": 0.65,
        "ytick.major.width": 0.65,
        "xtick.minor.width": 0.5,
        "ytick.minor.width": 0.5,
        "legend.fontsize": 7.0,
        "legend.frameon": False,
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "mathtext.fontset": "custom",
        "mathtext.rm": "Arial",
        "mathtext.it": "Arial:italic",
        "mathtext.bf": "Arial:bold",
    }
)

_REVIEW_PREVIEW_RCPARAMS: Mapping[str, Any] = MappingProxyType(
    {
        **dict(_PUBLICATION_DOUBLE_COLUMN_RCPARAMS),
        "font.size": 9.0,
        "axes.labelsize": 9.0,
        "xtick.labelsize": 8.0,
        "ytick.labelsize": 8.0,
        "legend.fontsize": 8.0,
        "axes.spines.right": True,
        "axes.spines.top": True,
    }
)

_PUBLICATION_SINGLE_COLUMN_RCPARAMS: Mapping[str, Any] = MappingProxyType(
    {
        **dict(_PUBLICATION_DOUBLE_COLUMN_RCPARAMS),
        # Seven-point type remains readable at final size and matches the
        # double-column publication vocabulary.
        "font.size": 7.0,
        "axes.labelsize": 7.0,
        "xtick.labelsize": 7.0,
        "ytick.labelsize": 7.0,
        "legend.fontsize": 6.5,
    }
)

STYLE_PRESETS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        PUBLICATION_DOUBLE_COLUMN: _PUBLICATION_DOUBLE_COLUMN_RCPARAMS,
        PUBLICATION_SINGLE_COLUMN: _PUBLICATION_SINGLE_COLUMN_RCPARAMS,
        REVIEW_PREVIEW: _REVIEW_PREVIEW_RCPARAMS,
    }
)


@contextmanager
def publication_style(
    preset: str = PUBLICATION_DOUBLE_COLUMN,
    overrides: Mapping[str, Any] | None = None,
) -> Iterator[None]:
    """Apply a controlled style locally and restore the caller's rcParams.

    Figure dimensions are intentionally absent from the presets.  Every diagram
    must declare its final width and height explicitly because journal layouts
    and single-/double-column figures have different size contracts.
    """

    if preset not in STYLE_PRESETS:
        choices = ", ".join(STYLE_PRESETS)
        raise PlotStyleError(f"未知绘图预设：{preset}。可用预设：{choices}。")

    settings = dict(STYLE_PRESETS[preset])
    if overrides:
        unknown = sorted(key for key in overrides if key not in mpl.rcParams)
        if unknown:
            raise PlotStyleError(
                "Matplotlib 不识别以下样式参数：" + ", ".join(unknown) + "。"
            )
        settings.update(dict(overrides))

    # rc_context validates values and guarantees restoration even if plotting
    # raises an exception inside the block.
    with mpl.rc_context(rc=settings):
        yield


def publication_styled(
    preset: str = PUBLICATION_DOUBLE_COLUMN,
    overrides: Mapping[str, Any] | None = None,
    *,
    preset_parameter: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a plotter while keeping all rcParams changes local.

    ``preset_parameter`` lets a public plotting function select a registered
    preset through one of its own arguments without mutating global state.
    """

    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        function_signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            selected = preset
            if preset_parameter is not None:
                bound = function_signature.bind_partial(*args, **kwargs)
                selected = str(
                    bound.arguments.get(preset_parameter, preset)
                )
            with publication_style(selected, overrides):
                return function(*args, **kwargs)

        return wrapped

    return decorator


def style_for_index(index: int) -> dict[str, str]:
    """Return a deterministic colour, marker, and line style for one index."""

    if index < 0:
        raise PlotStyleError("样式序号不能为负数。")
    return {
        "color": GROUP_COLORS[index % len(GROUP_COLORS)],
        "marker": MARKERS[index % len(MARKERS)],
        "linestyle": LINE_STYLES[index % len(LINE_STYLES)],
    }


def group_style_map(groups: Sequence[str]) -> dict[str, dict[str, str]]:
    """Map unique, non-empty group names to deterministic combined styles."""

    names = [str(group).strip() for group in groups]
    if any(not name for name in names):
        raise PlotStyleError("分组名称不能为空。")
    if len(set(names)) != len(names):
        raise PlotStyleError("分组名称不能重复。")
    return {name: style_for_index(index) for index, name in enumerate(names)}


def configure_boxed_legend(legend: Any) -> None:
    """Apply the established restrained white box to an in-axes legend."""

    legend.set_zorder(10)
    frame = legend.get_frame()
    frame.set_facecolor("white")
    frame.set_edgecolor("#A8A8A8")
    frame.set_linewidth(0.5)
    frame.set_alpha(0.96)


def mm_to_inches(value_mm: float) -> float:
    """Convert a positive physical dimension from millimetres to inches."""

    if value_mm <= 0:
        raise PlotStyleError("图件尺寸必须大于 0 mm。")
    return float(value_mm) / 25.4
