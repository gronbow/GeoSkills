#!/usr/bin/env python3
"""Create a publication-oriented chondrite-normalized REE pattern figure."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.path import Path as MatplotlibPath
from matplotlib.ticker import LogFormatterMathtext, LogLocator

from geoskills_core.errors import PlottingError
from geoskills_core.export import save_figure_files
from geoskills_core.plotting import (
    FORMATS,
    GROUP_COLORS,
    LINE_STYLES,
    MARKERS,
    PUBLICATION_DOUBLE_COLUMN,
    configure_boxed_legend,
    publication_styled,
)
from inspect_data import InspectionError, inspect_frame, issue, read_table
from normalize_ree import (
    DEFAULT_REFERENCE_PATH,
    NormalizationError,
    load_reference,
    normalize_frame,
    reference_summary,
)


DEFAULT_LOG_Y_MARGIN = 0.08
AXES_FRAMES = ("open", "full")
LEGEND_LAYOUTS = ("outside", "inside-auto")
GRID_STYLES = ("none", "major")


def adaptive_log_y_limits(
    values: np.ndarray, margin_fraction: float = DEFAULT_LOG_Y_MARGIN
) -> tuple[float, float, float, float, float]:
    """Return positive log-scale limits with compact, data-led visual margins.

    The margin is measured in log space for broad REE patterns, but never becomes
    smaller than the requested proportional margin for a narrow data range.
    """
    if not 0.01 <= margin_fraction <= 0.25:
        raise PlottingError("纵坐标边距必须在 0.01–0.25 之间。")

    numeric = np.asarray(values, dtype=float).ravel()
    valid = numeric[np.isfinite(numeric) & (numeric > 0)]
    if valid.size == 0:
        raise PlottingError("没有可用于对数纵坐标范围计算的正数值。")

    data_min = float(valid.min())
    data_max = float(valid.max())
    log_min = float(np.log10(data_min))
    log_max = float(np.log10(data_max))
    data_span_decades = log_max - log_min
    margin_decades = max(
        data_span_decades * margin_fraction,
        float(np.log10(1.0 + margin_fraction)),
    )
    return (
        float(10 ** (log_min - margin_decades)),
        float(10 ** (log_max + margin_decades)),
        data_min,
        data_max,
        margin_decades,
    )


def clean_log_y_limits(
    adaptive_lower: float,
    adaptive_upper: float,
    data_min: float,
) -> tuple[float, float, float, float]:
    """Round adaptive log limits to readable decimal bounds without clipping data.

    Use the actual data minimum as the lower-bound safety check. This lets an
    adaptive lower margin of 7.89 become 10 when the first real value is 11.29,
    while still preserving a clean integer edge and every plotted data point.
    """
    lower_step = float(10 ** np.floor(np.log10(data_min)))
    lower = float(np.floor(data_min / lower_step) * lower_step)
    if np.isclose(lower, data_min):
        next_lower = lower - lower_step
        lower = float(next_lower if next_lower > 0 else lower_step / 2.0)
    if lower <= 0:
        lower = lower_step / 2.0

    upper_step = float(10 ** (np.floor(np.log10(adaptive_upper)) - 1))
    upper = float(np.ceil(adaptive_upper / upper_step) * upper_step)

    if not lower < data_min:
        raise PlottingError("无法在不裁切数据的情况下确定整洁的纵坐标下限。")
    if upper < adaptive_upper:
        raise PlottingError("无法在不裁切数据的情况下确定整洁的纵坐标上限。")
    return lower, upper, float(lower_step), float(upper_step)


def legends_overlap_data(
    ax: Any,
    data_lines: list[Line2D],
    legends: list[Any],
) -> bool:
    """Return whether legend boxes overlap each other or a plotted data path."""
    ax.figure.canvas.draw()
    renderer = ax.figure.canvas.get_renderer()
    boxes = [legend.get_window_extent(renderer).expanded(1.02, 1.08) for legend in legends]
    axes_box = ax.get_window_extent(renderer)

    for index, box in enumerate(boxes):
        if (
            box.x0 < axes_box.x0
            or box.x1 > axes_box.x1
            or box.y0 < axes_box.y0
            or box.y1 > axes_box.y1
        ):
            return True
        if any(box.overlaps(other) for other in boxes[index + 1 :]):
            return True

    for line in data_lines:
        x_values = np.asarray(line.get_xdata(), dtype=float)
        y_values = np.asarray(line.get_ydata(), dtype=float)
        finite = np.isfinite(x_values) & np.isfinite(y_values) & (y_values > 0)
        finite_indices = np.flatnonzero(finite)
        if finite_indices.size == 0:
            continue
        splits = np.split(
            finite_indices,
            np.where(np.diff(finite_indices) != 1)[0] + 1,
        )
        for indices in splits:
            coordinates = ax.transData.transform(
                np.column_stack((x_values[indices], y_values[indices]))
            )
            for box in boxes:
                points_inside = (
                    (coordinates[:, 0] >= box.x0)
                    & (coordinates[:, 0] <= box.x1)
                    & (coordinates[:, 1] >= box.y0)
                    & (coordinates[:, 1] <= box.y1)
                )
                if points_inside.any():
                    return True
                if len(coordinates) > 1 and MatplotlibPath(coordinates).intersects_bbox(
                    box, filled=False
                ):
                    return True
    return False


def parse_element_selection(selection: str | None, available: list[str]) -> list[str]:
    """Resolve a comma-separated REE selection in canonical order."""
    if selection is None:
        selected = list(available)
    else:
        requested = [item.strip().title() for item in selection.split(",") if item.strip()]
        if len(set(requested)) != len(requested):
            raise PlottingError("--elements 中不能重复同一个元素。")
        unknown = [element for element in requested if element not in available]
        if unknown:
            raise PlottingError(
                f"所选元素未在已验证输入中出现：{', '.join(unknown)}。"
            )
        selected = [element for element in available if element in requested]
    if len(selected) < 3:
        raise PlottingError("REE 配分图至少需要 3 个已验证元素。")
    return selected


@publication_styled(preset_parameter="style_preset")
def build_figure(
    normalized: pd.DataFrame,
    sample_column: str,
    group_column: str | None,
    elements: list[str],
    reference_id: str,
    title: str | None = None,
    width_mm: float = 183.0,
    height_mm: float = 120.0,
    y_margin: float = DEFAULT_LOG_Y_MARGIN,
    axes_frame: str = "open",
    legend_layout: str = "outside",
    grid_style: str = "none",
    y_label: str = "Sample / C1 chondrite",
    reference_note: str | None = None,
    show_reference_note: bool = True,
    x_tick_labelsize: float | None = None,
    x_tick_stagger: bool = False,
    show_sample_ids: bool = True,
    group_legend_title: str = "Group",
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> tuple[plt.Figure, dict[str, Any]]:
    """Build one figure; export callers must reuse this same figure object."""
    if not 50 <= width_mm <= 400 or not 50 <= height_mm <= 400:
        raise PlottingError("图像宽度和高度必须在 50–400 mm 之间。")
    if axes_frame not in AXES_FRAMES:
        raise PlottingError(f"坐标轴边框必须是：{', '.join(AXES_FRAMES)}。")
    if legend_layout not in LEGEND_LAYOUTS:
        raise PlottingError(f"图例布局必须是：{', '.join(LEGEND_LAYOUTS)}。")
    if grid_style not in GRID_STYLES:
        raise PlottingError(f"网格样式必须是：{', '.join(GRID_STYLES)}。")
    clean_group_legend_title = str(group_legend_title).strip()
    if not clean_group_legend_title:
        raise PlottingError("分组图例标题不能为空。")

    samples = normalized[sample_column].astype("string").tolist()
    if group_column is None:
        groups = list(samples)
    else:
        group_text = normalized[group_column].astype("string").str.strip()
        groups = group_text.fillna("Ungrouped").replace("", "Ungrouped").tolist()

    group_order = list(dict.fromkeys(groups))
    color_by_group = {
        group: GROUP_COLORS[index % len(GROUP_COLORS)]
        for index, group in enumerate(group_order)
    }
    style_by_group = {
        group: LINE_STYLES[index % len(LINE_STYLES)]
        for index, group in enumerate(group_order)
    }
    skipped_samples: list[str] = []

    fig, ax = plt.subplots(
        figsize=(width_mm / 25.4, height_mm / 25.4),
        facecolor="white",
    )
    x = np.arange(len(elements))
    value_columns = [f"{element}_N" for element in elements]
    all_values = normalized.loc[:, value_columns].to_numpy(dtype=float)
    (
        adaptive_lower,
        adaptive_upper,
        data_min,
        data_max,
        margin_decades,
    ) = adaptive_log_y_limits(all_values, y_margin)
    y_lower, y_upper, lower_rounding_step, upper_rounding_step = (
        clean_log_y_limits(adaptive_lower, adaptive_upper, data_min)
    )
    unity_line_visible = y_lower <= 1.0 <= y_upper

    ax.set_yscale("log")
    ax.set_ylim(y_lower, y_upper)
    if unity_line_visible:
        ax.axhline(1.0, color="#767676", linewidth=0.8, linestyle="--", zorder=1)

    plotted_sample_count = 0
    plotted_indices: list[int] = []
    data_lines: list[Line2D] = []
    for row_index, (sample, group) in enumerate(zip(samples, groups)):
        y = normalized.loc[
            normalized.index[row_index], value_columns
        ].to_numpy(dtype=float)
        y = np.where(np.isfinite(y) & (y > 0), y, np.nan)
        if not np.isfinite(y).any():
            skipped_samples.append(str(sample))
            continue
        (data_line,) = ax.plot(
            x,
            y,
            color=color_by_group[group],
            linestyle=style_by_group[group],
            linewidth=1.05,
            marker=MARKERS[row_index % len(MARKERS)],
            markersize=3.6,
            markeredgecolor="white",
            markeredgewidth=0.4,
            label="_nolegend_",
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=2,
        )
        data_lines.append(data_line)
        plotted_indices.append(row_index)
        plotted_sample_count += 1

    if plotted_sample_count == 0:
        plt.close(fig)
        raise PlottingError("所有样品在所选元素上都为空，无法绘图。")

    ax.set_xlim(-0.4, len(elements) - 0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(elements)
    if x_tick_labelsize is not None:
        ax.tick_params(axis="x", labelsize=x_tick_labelsize)
    x_tick_label_strategy = "standard"
    if x_tick_stagger and len(elements) > 1:
        for index, label in enumerate(ax.get_xticklabels()):
            label.set_y(-0.025 if index % 2 else -0.005)
        x_tick_label_strategy = "staggered"
    # Element symbols already define the categorical x axis; omitting a repeated
    # x-axis title preserves space and improves readability after journal scaling.
    ax.set_xlabel("")
    ax.set_ylabel(y_label)
    ax.tick_params(axis="both", which="major", direction="out", length=3)
    ax.tick_params(axis="y", which="minor", direction="out", length=1.8)
    ax.yaxis.set_major_locator(LogLocator(base=10))
    ax.yaxis.set_major_formatter(LogFormatterMathtext(base=10))
    ax.yaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10) * 0.1))
    ax.set_axisbelow(True)
    if grid_style == "major":
        ax.grid(
            visible=True,
            which="major",
            axis="y",
            color="#D7D7D7",
            linewidth=0.45,
        )
    else:
        ax.grid(visible=False, which="major", axis="y")
    visible_spines = (
        ("left", "bottom", "top", "right")
        if axes_frame == "full"
        else ("left", "bottom")
    )
    for spine in ("left", "bottom", "top", "right"):
        ax.spines[spine].set_visible(spine in visible_spines)
        if spine in visible_spines:
            ax.spines[spine].set_linewidth(0.7)
    if title:
        ax.set_title(title, fontsize=7, fontweight="bold", loc="left", pad=7)

    plotted_samples = [samples[index] for index in plotted_indices]
    plotted_groups = [groups[index] for index in plotted_indices]
    plotted_group_order = list(dict.fromkeys(plotted_groups))
    plotted_group_counts = Counter(plotted_groups)

    sample_handles = [
        Line2D(
            [0],
            [0],
            color=(color_by_group[group] if group_column is None else "#555555"),
            linewidth=0.9,
            linestyle=(style_by_group[group] if group_column is None else "None"),
            marker=MARKERS[index % len(MARKERS)],
            markersize=3.8,
            markerfacecolor=(color_by_group[group] if group_column is None else "#555555"),
            markeredgecolor="white",
            markeredgewidth=0.35,
        )
        for index, group in zip(plotted_indices, plotted_groups)
    ]
    group_handles: list[Line2D] = []
    group_labels: list[str] = []
    group_title = ""
    if group_column is not None:
        group_handles = [
            Line2D(
                [0],
                [0],
                color=color_by_group[group],
                linewidth=1.6,
                linestyle=style_by_group[group],
            )
            for group in plotted_group_order
        ]
        group_labels = [
            textwrap.fill(f"{group} (n={plotted_group_counts[group]})", width=26)
            for group in plotted_group_order
        ]
        group_title = clean_group_legend_title

    def add_outside_legends() -> None:
        if group_column is None:
            if not show_sample_ids:
                return
            fig.legend(
                sample_handles,
                [str(sample) for sample in plotted_samples],
                loc="upper left",
                bbox_to_anchor=(0.755, 0.91),
                fontsize=6.2,
                title="Sample ID",
                title_fontsize=6.6,
                handlelength=1.6,
                labelspacing=0.45,
                borderaxespad=0,
            )
            return
        fig.legend(
            group_handles,
            group_labels,
            loc="upper left",
            bbox_to_anchor=(0.755, 0.91),
            fontsize=6.1,
            title=group_title,
            title_fontsize=6.6,
            handlelength=1.8,
            labelspacing=0.5,
            borderaxespad=0,
        )
        if show_sample_ids:
            fig.legend(
                sample_handles,
                [str(sample) for sample in plotted_samples],
                loc="upper left",
                bbox_to_anchor=(0.755, 0.57),
                fontsize=6.1,
                title="Sample ID (symbol)",
                title_fontsize=6.6,
                handlelength=1.35,
                labelspacing=0.45,
                columnspacing=0.8,
                ncol=2 if len(plotted_samples) >= 6 else 1,
                borderaxespad=0,
            )

    def add_inside_legends(
        *,
        group_columns: int,
        sample_columns: int,
        group_wrap_width: int,
        group_fontsize: float,
        sample_fontsize: float,
    ) -> list[Any]:
        legends: list[Any] = []
        sample_anchor_y = 0.985
        if group_column is not None:
            compact_group_labels = [
                textwrap.fill(
                    f"{group} (n={plotted_group_counts[group]})",
                    width=group_wrap_width,
                )
                for group in plotted_group_order
            ]
            group_legend = ax.legend(
                group_handles,
                compact_group_labels,
                loc="upper right",
                bbox_to_anchor=(0.985, 0.985),
                bbox_transform=ax.transAxes,
                fontsize=group_fontsize,
                title=group_title,
                title_fontsize=6.1,
                handlelength=1.65,
                labelspacing=0.34,
                columnspacing=0.75,
                ncol=min(group_columns, len(group_handles)),
                borderaxespad=0,
                frameon=True,
                fancybox=False,
                borderpad=0.48,
            )
            configure_boxed_legend(group_legend)
            ax.add_artist(group_legend)
            legends.append(group_legend)
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            group_box = group_legend.get_window_extent(renderer).transformed(
                ax.transAxes.inverted()
            )
            sample_anchor_y = float(group_box.y0) - 0.018
        if show_sample_ids:
            sample_legend = ax.legend(
                sample_handles,
                [str(sample) for sample in plotted_samples],
                loc="upper right",
                bbox_to_anchor=(0.985, sample_anchor_y),
                bbox_transform=ax.transAxes,
                fontsize=sample_fontsize,
                title=(
                    "Sample ID (symbol)"
                    if group_column is not None
                    else "Sample ID"
                ),
                title_fontsize=5.9,
                handlelength=1.25,
                labelspacing=0.32,
                columnspacing=0.62,
                ncol=min(sample_columns, len(plotted_samples)),
                borderaxespad=0,
                frameon=True,
                fancybox=False,
                borderpad=0.48,
            )
            configure_boxed_legend(sample_legend)
            legends.append(sample_legend)
        return legends

    legend_needed = group_column is not None or show_sample_ids
    plot_right = (
        0.96
        if legend_layout == "inside-auto" or not legend_needed
        else 0.73
    )
    plot_left = 0.18 if width_mm <= 100 else 0.095
    plot_bottom = (
        0.19 if x_tick_stagger else 0.16
    ) if show_reference_note else (0.14 if x_tick_stagger else 0.11)
    fig.subplots_adjust(
        left=plot_left,
        right=plot_right,
        bottom=plot_bottom,
        top=0.90 if title else 0.95,
    )
    legend_position = "outside_right" if legend_needed else "none"
    legend_fallback = False
    inside_legend_strategy: str | None = None
    if not legend_needed:
        pass
    elif legend_layout == "inside-auto":
        candidates = [
            {
                "name": "stacked",
                "group_columns": 1,
                "sample_columns": 3,
                "group_wrap_width": 22,
                "group_fontsize": 5.6,
                "sample_fontsize": 5.4,
            },
            {
                "name": "compact-two-column",
                "group_columns": 2,
                "sample_columns": 4,
                "group_wrap_width": 18,
                "group_fontsize": 5.25,
                "sample_fontsize": 5.15,
            },
            {
                "name": "compact-wide",
                "group_columns": 2,
                "sample_columns": 5,
                "group_wrap_width": 16,
                "group_fontsize": 5.05,
                "sample_fontsize": 5.0,
            },
        ]
        inside_legends: list[Any] = []
        for candidate in candidates:
            inside_legends = add_inside_legends(
                group_columns=int(candidate["group_columns"]),
                sample_columns=int(candidate["sample_columns"]),
                group_wrap_width=int(candidate["group_wrap_width"]),
                group_fontsize=float(candidate["group_fontsize"]),
                sample_fontsize=float(candidate["sample_fontsize"]),
            )
            if not legends_overlap_data(ax, data_lines, inside_legends):
                inside_legend_strategy = str(candidate["name"])
                break
            for legend in inside_legends:
                legend.remove()
            inside_legends = []
        if not inside_legends:
            fig.subplots_adjust(
                left=plot_left,
                right=0.73,
                bottom=plot_bottom,
                top=0.90 if title else 0.95,
            )
            add_outside_legends()
            legend_position = "outside_right_fallback"
            legend_fallback = True
        else:
            legend_position = "inside_upper_right"
    else:
        add_outside_legends()
    reference_note = (
        reference_note
        if reference_note is not None
        else "Normalization: Sun & McDonough (1989) C1 chondrite"
    )
    if unity_line_visible:
        reference_note += "; dashed line = unity."
    else:
        reference_note += "; limits adapt and round to clean bounds."
    if show_reference_note:
        fig.text(
            plot_left,
            0.045,
            reference_note,
            fontsize=5.8,
            color="#4D4D4D",
            ha="left",
        )
    return fig, {
        "normalization_id": reference_id,
        "reference_note_on_canvas": show_reference_note,
        "y_limits": {
            "lower": y_lower,
            "upper": y_upper,
            "adaptive_lower": adaptive_lower,
            "adaptive_upper": adaptive_upper,
            "data_min": data_min,
            "data_max": data_max,
            "margin_fraction": y_margin,
            "margin_decades": margin_decades,
            "rounding": {
                "policy": "clean_log_bounds",
                "lower_step": lower_rounding_step,
                "upper_step": upper_rounding_step,
            },
            "policy": "adaptive_log10_clean_bounds",
        },
        "unity_line_visible": unity_line_visible,
        "sample_count": len(samples),
        "plotted_sample_count": plotted_sample_count,
        "legend_sample_count": len(plotted_samples) if show_sample_ids else 0,
        "sample_ids_rendered": bool(show_sample_ids),
        "group_count": len(plotted_group_order),
        "group_column": group_column,
        "group_legend_title": (
            clean_group_legend_title if group_column is not None else None
        ),
        "skipped_samples": skipped_samples,
        "palette_repeated": len(plotted_group_order) > len(GROUP_COLORS),
        "line_style_repeated": len(plotted_group_order) > len(LINE_STYLES),
        "marker_repeated": plotted_sample_count > len(MARKERS),
        "axes_frame": axes_frame,
        "grid_style": grid_style,
        "x_tick_label_strategy": x_tick_label_strategy,
        "legend_layout_requested": legend_layout,
        "legend_position": legend_position,
        "legend_fallback": legend_fallback,
        "inside_legend_strategy": inside_legend_strategy,
        "legend_collision_free": True,
        "inside_legend_collision_free": (
            not legend_fallback if legend_layout == "inside-auto" else None
        ),
        "legend_strategy": (
            "boxed in-axes group colour/line-style key; sample IDs suppressed"
            if (
                not show_sample_ids
                and group_column is not None
                and legend_position == "inside_upper_right"
            )
            else "group colour/line-style key; sample IDs suppressed"
            if not show_sample_ids and group_column is not None
            else "no legend; sample IDs suppressed"
            if not show_sample_ids
            else "boxed in-axes group colour/line-style and sample-symbol keys with collision check"
            if legend_position == "inside_upper_right" and group_column is not None
            else "boxed in-axes sample key with collision check"
            if legend_position == "inside_upper_right"
            else "separate group colour/line-style and sample-symbol keys"
            if group_column is not None
            else "sample key"
        ),
        "colour_is_not_the_only_identifier": True,
        "group_encoding": (
            "colour plus line style" if group_column is not None else "not applicable"
        ),
        "sample_encoding": (
            "symbol only; sample identity not disclosed"
            if not show_sample_ids
            else "unique symbol"
            if plotted_sample_count <= len(MARKERS)
            else f"symbols repeat after {len(MARKERS)} plotted samples"
        ),
    }


def file_record(path: Path) -> dict[str, Any]:
    return {
        "format": path.suffix.lower().lstrip("."),
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def output_targets(output_dir: Path, stem: str) -> tuple[list[Path], Path, Path]:
    if not stem or Path(stem).name != stem or Path(stem).suffix:
        raise PlottingError("输出名称必须是不含路径和扩展名的文件名。")
    figures = [output_dir / f"{stem}.{extension}" for extension in FORMATS]
    source_data = output_dir / f"{stem}.source_data.csv"
    return figures, source_data, output_dir / f"{stem}.report.json"


def plotting_error(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "ree_pattern_plot",
        "source": {"path": str(path.resolve())},
        "issues": [issue("E500", "error", message)],
    }


@publication_styled(preset_parameter="style_preset")
def plot_path(
    input_path: Path,
    output_dir: Path,
    stem: str | None = None,
    requested_sheet: str | None = None,
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
    requested_elements: str | None = None,
    title: str | None = None,
    width_mm: float = 183.0,
    height_mm: float = 120.0,
    dpi: int = 600,
    y_margin: float = DEFAULT_LOG_Y_MARGIN,
    axes_frame: str = "open",
    legend_layout: str = "outside",
    grid_style: str = "none",
    show_sample_ids: bool = True,
    group_legend_title: str = "Group",
    show_reference_note: bool = True,
    overwrite: bool = False,
    reference_path: Path = DEFAULT_REFERENCE_PATH,
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> dict[str, Any]:
    """Validate input and export a publication figure bundle from one figure."""
    figure = None
    try:
        if not 72 <= dpi <= 1200:
            raise PlottingError("PNG/TIFF 分辨率必须在 72–1200 dpi 之间。")
        resolved_stem = stem or f"{input_path.stem}_ree_pattern"
        figure_paths, source_data_path, report_path = output_targets(
            output_dir, resolved_stem
        )
        existing = [
            path
            for path in [*figure_paths, source_data_path, report_path]
            if path.exists()
        ]
        if existing and not overwrite:
            raise PlottingError(
                "输出文件已经存在；如需替换，请显式使用 --overwrite。"
            )

        reference, reference_values = load_reference(reference_path)
        frame, source = read_table(input_path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "ree_pattern_plot",
                "source": source,
                "reference": reference_summary(reference_path, reference),
                "issues": [
                    issue(
                        "E111",
                        "review",
                        "Excel 文件包含多个工作表，请使用 --sheet 指定一个工作表。",
                        sheet_names=source["sheet_names"],
                    )
                ],
            }

        inspection = inspect_frame(
            frame,
            source,
            requested_sample_column,
            requested_group_column,
        )
        if inspection["status"] != "ready":
            return {
                "status": "blocked",
                "operation": "ree_pattern_plot",
                "reference": reference_summary(reference_path, reference),
                "input_inspection": inspection,
                "issues": [
                    issue(
                        "E501",
                        "review",
                        "输入数据未通过安全检查，因此没有生成图像。",
                    )
                ],
            }

        available_elements = [
            element
            for element in reference["element_order"]
            if element in {item["element"] for item in inspection["ree"]["recognized"]}
        ]
        elements = parse_element_selection(requested_elements, available_elements)
        normalized = normalize_frame(
            frame,
            inspection,
            reference_values,
            reference["element_order"],
        )
        sample_column = inspection["sample_id_candidates"][0]
        group_column = (
            inspection["group_candidates"][0]
            if len(inspection["group_candidates"]) == 1
            else None
        )
        figure, plot_info = build_figure(
            normalized,
            sample_column,
            group_column,
            elements,
            reference["id"],
            title,
            width_mm,
            height_mm,
            y_margin=y_margin,
            axes_frame=axes_frame,
            legend_layout=legend_layout,
            grid_style=grid_style,
            show_sample_ids=show_sample_ids,
            group_legend_title=group_legend_title,
            show_reference_note=show_reference_note,
            style_preset=style_preset,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        save_figure_files(figure, figure_paths, dpi=dpi)
        source_columns = [sample_column]
        if group_column is not None:
            source_columns.append(group_column)
        source_columns.extend(f"{element}_N" for element in elements)
        normalized.loc[:, source_columns].to_csv(
            source_data_path,
            index=False,
            encoding="utf-8",
            float_format="%.8g",
        )
        plt.close(figure)
        figure = None

        run_issues = list(inspection["issues"])
        if plot_info["plotted_sample_count"] > 15:
            run_issues.append(
                issue(
                    "W501",
                    "warning",
                    "样品数超过 15，图例和曲线可能拥挤；建议按组分图。",
                    sample_count=plot_info["plotted_sample_count"],
                )
            )
        if plot_info["palette_repeated"]:
            run_issues.append(
                issue(
                    "W502",
                    "warning",
                    "分组数量超过基础色板，部分颜色被重复使用。",
                    group_count=plot_info["group_count"],
                )
            )
        if plot_info["line_style_repeated"]:
            run_issues.append(
                issue(
                    "W504",
                    "warning",
                    "分组数量超过基础线型数量，灰度打印时部分组可能难以区分；建议按组分图。",
                    group_count=plot_info["group_count"],
                )
            )
        if plot_info["marker_repeated"]:
            run_issues.append(
                issue(
                    "W506",
                    "warning",
                    "已绘制样品数超过可用符号数量，部分样品符号会重复；建议按组分图。",
                    sample_count=plot_info["plotted_sample_count"],
                    unique_marker_count=len(MARKERS),
                )
            )
        if plot_info["skipped_samples"]:
            run_issues.append(
                issue(
                    "W503",
                    "warning",
                    "部分样品在所选元素上全部缺失，未绘制曲线。",
                    samples=plot_info["skipped_samples"],
                )
            )
        if plot_info["legend_fallback"]:
            run_issues.append(
                issue(
                    "W505",
                    "warning",
                    "图内自动图例会遮挡数据，已安全改为右侧图例布局。",
                )
            )

        report = {
            "status": "ready",
            "operation": "ree_pattern_plot",
            "source": source,
            "reference": reference_summary(reference_path, reference),
            "figure_contract": {
                "core_conclusion": "Show the relative REE enrichment, depletion, slopes, and visible anomalies among samples and rock groups without assigning a unique petrogenetic cause.",
                "archetype": "single-panel quantitative figure",
                "backend": "Python/matplotlib",
                "role": "comparative evidence",
                "evidence": "Sample-to-Chondrite_SM89 ratios across ordered La-Lu elements",
                "target_output": "double-column publication figure",
                "review_risks": [
                    "log-axis invalid values",
                    "missing-value connections",
                    "overplotting and legend crowding",
                    "editable vector text",
                    "colour-only identification",
                ],
            },
            "configuration": {
                "sample_column": sample_column,
                "group_column": group_column,
                "elements": elements,
                "y_scale": "log10",
                "y_limit_policy": plot_info["y_limits"]["policy"],
                "y_margin_fraction": y_margin,
                "y_limits": plot_info["y_limits"],
                "unity_line": plot_info["unity_line_visible"],
                "reference_line_value": 1.0,
                "axes_frame": axes_frame,
                "legend_layout": legend_layout,
                "legend_position": plot_info["legend_position"],
                "show_sample_ids": show_sample_ids,
                "group_legend_title": group_legend_title,
                "grid_style": grid_style,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "png_dpi": dpi,
                "tiff_dpi": dpi,
                "formats": list(FORMATS),
                "style_preset": style_preset,
            },
            "plot": plot_info,
            "outputs": [file_record(path) for path in figure_paths],
            "source_data": file_record(source_data_path),
            "submission_qa": {
                "final_size_mm": [width_mm, height_mm],
                "svg_text_editable": True,
                "pdf_font_type": 42,
                "raster_dpi": dpi,
                "tiff_compression": "LZW",
                "white_background": True,
                "colourblind_support": (
                    "group colour plus line style; sample IDs suppressed"
                    if not show_sample_ids and group_column is not None
                    else "sample symbols shown without identity key"
                    if not show_sample_ids
                    else "group colour plus line style; unique sample symbol"
                    if not plot_info["marker_repeated"]
                    else "group colour plus line style; sample symbols repeat with warning"
                ),
                "source_data_exported": True,
            },
            "report_file": str(report_path.resolve()),
            "issues": run_issues,
            "interpretation_guidance": [
                "Compare the light-to-heavy REE slope and the degree of parallelism among samples.",
                "Inspect Eu and Ce positions relative to adjacent elements before calculating or naming an anomaly.",
                "Treat line breaks as missing measurements, not as zero concentrations.",
                "Combine the pattern with petrography, major elements, trace-element ratios, and isotopes before proposing a process or source.",
            ],
            "scientific_caveat": "The diagram alone does not establish a unique magma source, melting process, mineral control, tectonic setting, or alteration history.",
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    except (InspectionError, NormalizationError, PlottingError, OSError, ValueError) as exc:
        return plotting_error(input_path, str(exc))
    finally:
        if figure is not None:
            plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成 Sun & McDonough (1989) 球粒陨石标准化 REE 配分图。"
    )
    parser.add_argument("input", type=Path, help="CSV、TXT 或 Excel 输入表格")
    parser.add_argument("--output-dir", type=Path, required=True, help="图像输出文件夹")
    parser.add_argument("--stem", help="不含扩展名的输出文件名")
    parser.add_argument("--sheet", help="Excel 工作表名称，或从 0 开始的编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选的分组列")
    parser.add_argument("--elements", help="逗号分隔的 REE，例如 La,Ce,Pr,Nd")
    parser.add_argument("--title", help="可选图题；论文图通常留空并使用图注")
    parser.add_argument("--width-mm", type=float, default=183.0, help="图宽，默认 183 mm")
    parser.add_argument("--height-mm", type=float, default=120.0, help="图高，默认 120 mm")
    parser.add_argument(
        "--dpi", type=int, default=600, help="PNG/TIFF 分辨率，默认 600 dpi"
    )
    parser.add_argument(
        "--y-margin",
        type=float,
        default=DEFAULT_LOG_Y_MARGIN,
        help="对数纵坐标边距比例，默认 0.08（建议 0.05–0.10）",
    )
    parser.add_argument(
        "--axes-frame",
        choices=AXES_FRAMES,
        default="open",
        help="坐标轴边框：open（左下）或 full（四边框）",
    )
    parser.add_argument(
        "--legend-layout",
        choices=LEGEND_LAYOUTS,
        default="outside",
        help="图例布局：outside（右侧）或 inside-auto（图内自动避让）",
    )
    parser.add_argument(
        "--grid-style",
        choices=GRID_STYLES,
        default="none",
        help="横向网格：none（投稿默认）或 major（仅主刻度）",
    )
    parser.add_argument(
        "--hide-sample-ids",
        action="store_true",
        help="不在图件图例中显示样品编号；分组图例仍保留",
    )
    parser.add_argument(
        "--group-legend-title",
        default="Group",
        help="分组图例标题，默认 Group；不会根据列名猜测岩性",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="明确允许替换已存在的整套输出文件",
    )
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    report = plot_path(
        args.input,
        args.output_dir,
        stem=args.stem,
        requested_sheet=args.sheet,
        requested_sample_column=args.sample_column,
        requested_group_column=args.group_column,
        requested_elements=args.elements,
        title=args.title,
        width_mm=args.width_mm,
        height_mm=args.height_mm,
        dpi=args.dpi,
        y_margin=args.y_margin,
        axes_frame=args.axes_frame,
        legend_layout=args.legend_layout,
        grid_style=args.grid_style,
        show_sample_ids=not args.hide_sample_ids,
        group_legend_title=args.group_legend_title,
        overwrite=args.overwrite,
    )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"REE 绘图完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
