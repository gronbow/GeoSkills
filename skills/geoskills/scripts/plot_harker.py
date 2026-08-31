#!/usr/bin/env python3
"""Create publication-oriented Harker variation-diagram grids."""

from __future__ import annotations

import argparse
import json
import math
import string
import sys
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator

from geoskills_core.errors import PlottingError
from geoskills_core.export import save_figure_files
from geoskills_core.plotting import (
    GROUP_COLORS,
    MARKERS,
    PUBLICATION_DOUBLE_COLUMN,
    publication_styled,
)
from inspect_data import InspectionError, issue
from inspect_major_data import (
    inspect_major_frame,
    prepare_geochem_frame,
    read_major_table,
)
from plot_geochem_common import (
    analyte_label,
    clean_linear_limits,
    ensure_outputs_available,
    filter_requested_groups,
    group_style_map,
    output_targets,
    resolve_analyte_list,
    resolve_analyte_selection,
    shareable_file_record,
    validate_export_parameters,
)
DEFAULT_X = "SiO2"
DEFAULT_Y_CANDIDATES = [
    "TiO2",
    "Al2O3",
    "Fe2O3T",
    "FeOT",
    "MgO",
    "CaO",
    "Na2O",
    "K2O",
    "P2O5",
]
MAX_PANELS = 9
AXIS_LABEL_SIZE = 6.2
TICK_LABEL_SIZE = 5.6
PANEL_LABEL_SIZE = 7.0
HARKER_LITHOLOGY_ALERT_TERMS = (
    "carbonatite",
    "kimberlite",
    "lamproite",
)


def default_harker_y(available: list[str], x_analyte: str) -> list[str]:
    """Choose a conventional compact major-oxide grid."""
    selected: list[str] = []
    total_iron_selected = False
    for analyte in DEFAULT_Y_CANDIDATES:
        if analyte not in available or analyte == x_analyte:
            continue
        if analyte in {"Fe2O3T", "FeOT"}:
            if total_iron_selected:
                continue
            total_iron_selected = True
        selected.append(analyte)
    return selected[:MAX_PANELS]


def automatic_height(panel_count: int, columns: int) -> float:
    """Return a journal-compatible height for the panel grid."""
    rows = math.ceil(panel_count / columns)
    return {1: 86.0, 2: 120.0, 3: 155.0}.get(rows, 170.0)


def automatic_columns(panel_count: int) -> int:
    """Choose a compact grid without avoidable empty panels."""
    if panel_count == 9:
        return 3
    if panel_count >= 7:
        return 4
    if panel_count >= 5:
        return 3
    if panel_count == 4:
        return 2
    return panel_count


def potentially_mixed_harker_groups(groups: list[str]) -> list[str]:
    """Flag specialist lithologies mixed with other Harker groups."""
    flagged = [
        group
        for group in groups
        if any(
            term in group.casefold()
            for term in HARKER_LITHOLOGY_ALERT_TERMS
        )
    ]
    if flagged and len(flagged) < len(groups):
        return flagged
    return []


def add_shared_group_legend(
    figure: Any,
    handles: list[Any],
    labels: list[str],
    has_title: bool,
) -> dict[str, Any]:
    """Fit a shared legend inside the figure canvas without clipping."""
    display_labels = [
        textwrap.fill(
            label,
            width=38,
            break_long_words=False,
            break_on_hyphens=False,
        )
        for label in labels
    ]
    anchor_y = 0.945 if has_title else 0.985
    legend = None
    legend_box = None
    selected_columns = 1
    average_label_length = sum(len(label) for label in labels) / len(labels)
    max_columns = min(4, len(labels))
    if len(labels) >= 4 and average_label_length > 24:
        max_columns = min(2, len(labels))
    elif len(labels) == 3 and average_label_length > 30:
        max_columns = 2
    for candidate_columns in range(max_columns, 0, -1):
        legend = figure.legend(
            handles,
            display_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, anchor_y),
            ncol=candidate_columns,
            frameon=False,
            fontsize=5.8,
            handletextpad=0.35,
            columnspacing=0.9,
        )
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        legend_box = legend.get_window_extent(renderer).transformed(
            figure.transFigure.inverted()
        )
        if legend_box.x0 >= 0.02 and legend_box.x1 <= 0.98:
            selected_columns = candidate_columns
            break
        legend.remove()
        legend = None

    if legend is None or legend_box is None:
        raise PlottingError("共享图例无法安全放入图幅。")
    axes_top = max(0.58, min(0.94, float(legend_box.y0) - 0.025))
    return {
        "position": "shared_figure_top",
        "columns": selected_columns,
        "rows": math.ceil(len(labels) / selected_columns),
        "axes_top": axes_top,
        "within_figure": bool(
            legend_box.x0 >= 0.0
            and legend_box.x1 <= 1.0
            and legend_box.y0 >= 0.0
            and legend_box.y1 <= 1.0
        ),
    }


@publication_styled(preset_parameter="style_preset")
def build_harker_figure(
    frame: pd.DataFrame,
    sample_column: str,
    group_column: str | None,
    groups: list[str],
    x_analyte: str,
    y_analytes: list[str],
    units: dict[str, str],
    title: str | None,
    width_mm: float,
    height_mm: float,
    columns: int,
    axes_frame: str,
    margin_fraction: float,
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> tuple[Any, dict[str, Any]]:
    """Build one Harker grid from validated canonical data."""
    x_numeric = pd.to_numeric(frame[x_analyte], errors="coerce")
    y_numeric = {
        analyte: pd.to_numeric(frame[analyte], errors="coerce")
        for analyte in y_analytes
    }
    pair_masks = {
        analyte: (
            x_numeric.notna()
            & y_values.notna()
            & np.isfinite(x_numeric)
            & np.isfinite(y_values)
        )
        for analyte, y_values in y_numeric.items()
    }
    x_used = pd.Series(False, index=frame.index)
    for pair_mask in pair_masks.values():
        x_used |= pair_mask
    x_limits = clean_linear_limits(
        x_numeric[x_used], margin_fraction=margin_fraction
    )
    rows = math.ceil(len(y_analytes) / columns)
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(width_mm / 25.4, height_mm / 25.4),
        sharex=True,
        squeeze=False,
    )
    styles = group_style_map(groups)
    panel_reports: list[dict[str, Any]] = []
    missing_pairs: dict[str, int] = {}

    for index, analyte in enumerate(y_analytes):
        ax = axes.flat[index]
        pair_mask = pair_masks[analyte]
        valid_pair_count = int(pair_mask.sum())
        if valid_pair_count < 2:
            raise PlottingError(
                f"{x_analyte}–{analyte} 只有 {valid_pair_count} 个完整数据点；"
                "至少需要 2 个。"
            )
        y_limits = clean_linear_limits(
            y_numeric[analyte][pair_mask],
            margin_fraction=margin_fraction,
        )
        missing_pairs[analyte] = int(len(frame) - valid_pair_count)

        if group_column is None:
            ax.scatter(
                x_numeric[pair_mask],
                y_numeric[analyte][pair_mask],
                s=22,
                c="#3569A8",
                marker="o",
                edgecolors="white",
                linewidths=0.45,
                alpha=0.92,
                zorder=3,
            )
        else:
            for group in groups:
                subset = frame.loc[
                    frame[group_column].astype(str) == group
                ]
                x_values = pd.to_numeric(
                    subset[x_analyte], errors="coerce"
                )
                y_values = pd.to_numeric(
                    subset[analyte], errors="coerce"
                )
                finite = (
                    x_values.notna()
                    & y_values.notna()
                    & np.isfinite(x_values)
                    & np.isfinite(y_values)
                )
                style = styles[group]
                ax.scatter(
                    x_values[finite],
                    y_values[finite],
                    s=22,
                    c=style["color"],
                    marker=style["marker"],
                    edgecolors="white",
                    linewidths=0.45,
                    alpha=0.92,
                    zorder=3,
                )

        ax.set_xlim(
            float(x_limits["lower"]), float(x_limits["upper"])
        )
        ax.set_ylim(
            float(y_limits["lower"]), float(y_limits["upper"])
        )
        ax.xaxis.set_major_locator(
            MultipleLocator(float(x_limits["step"]))
        )
        ax.yaxis.set_major_locator(
            MultipleLocator(float(y_limits["step"]))
        )
        ax.set_ylabel(
            analyte_label(analyte, units[analyte]),
            fontsize=AXIS_LABEL_SIZE,
            labelpad=2.2,
        )
        if index // columns != rows - 1:
            ax.tick_params(axis="x", labelbottom=False)
        ax.tick_params(
            axis="both",
            which="major",
            direction="out",
            length=2.8,
            labelsize=TICK_LABEL_SIZE,
            pad=1.8,
        )
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_linewidth(0.7)
            spine.set_color("#1A1A1A")
        show_full = axes_frame == "full"
        ax.spines["top"].set_visible(show_full)
        ax.spines["right"].set_visible(show_full)
        ax.text(
            0.025,
            0.975,
            string.ascii_lowercase[index],
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=PANEL_LABEL_SIZE,
            fontweight="bold",
        )
        panel_reports.append(
            {
                "panel": string.ascii_lowercase[index],
                "x": x_analyte,
                "y": analyte,
                "complete_pairs": valid_pair_count,
                "x_limits": x_limits,
                "y_limits": y_limits,
            }
        )

    for index in range(len(y_analytes), rows * columns):
        axes.flat[index].set_axis_off()

    legend_info = {
        "position": "none",
        "columns": 0,
        "rows": 0,
        "axes_top": 0.90 if title else 0.94,
        "within_figure": True,
    }
    if group_column is not None:
        handles = [
            Line2D(
                [],
                [],
                linestyle="none",
                marker=styles[group]["marker"],
                markerfacecolor=styles[group]["color"],
                markeredgecolor="white",
                markeredgewidth=0.45,
                markersize=5.2,
            )
            for group in groups
        ]
        labels = [
            f"{group} (n={int((frame[group_column].astype(str) == group).sum())})"
            for group in groups
        ]
        legend_info = add_shared_group_legend(
            figure,
            handles,
            labels,
            has_title=bool(title),
        )

    figure.subplots_adjust(
        left=0.075,
        right=0.985,
        bottom=0.11,
        top=legend_info["axes_top"],
        hspace=0.34,
        wspace=0.46 if columns == 4 else 0.34,
    )
    figure.supxlabel(
        analyte_label(x_analyte, units[x_analyte]),
        x=0.53,
        y=0.025,
        fontsize=AXIS_LABEL_SIZE,
    )
    if title:
        figure.suptitle(title, y=0.995, fontsize=8)
    return figure, {
        "panel_count": len(y_analytes),
        "rows": rows,
        "columns": columns,
        "sample_count": int(len(frame)),
        "group_count": len(groups) if group_column is not None else 0,
        "legend_position": legend_info["position"],
        "legend_columns": legend_info["columns"],
        "legend_rows": legend_info["rows"],
        "legend_within_figure": legend_info["within_figure"],
        "shared_x_label": True,
        "axes_frame": axes_frame,
        "x_limits": x_limits,
        "panels": panel_reports,
        "missing_pairs": missing_pairs,
        "palette_repeated": len(groups) > len(GROUP_COLORS),
        "marker_repeated": len(groups) > len(MARKERS),
        "colour_is_not_the_only_identifier": True,
        "group_encoding": (
            "colour plus marker shape"
            if group_column is not None
            else "not applicable"
        ),
    }


def harker_error(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "harker_plot",
        "source": {"format": path.suffix.lower()},
        "issues": [issue("E650", "error", message)],
    }


def plot_harker_path(
    input_path: Path,
    output_dir: Path,
    stem: str | None = None,
    requested_sheet: str | None = None,
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
    requested_x: str = DEFAULT_X,
    requested_y: str | None = None,
    requested_groups: str | None = None,
    title: str | None = None,
    width_mm: float = 183.0,
    height_mm: float | None = None,
    columns: int | None = None,
    dpi: int = 600,
    axes_frame: str = "full",
    margin_fraction: float = 0.06,
    overwrite: bool = False,
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> dict[str, Any]:
    """Validate input and export a Harker figure bundle."""
    figure = None
    try:
        if columns is not None and not 1 <= columns <= 4:
            raise PlottingError("--columns 必须在 1–4 之间。")
        frame, source = read_major_table(input_path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "harker_plot",
                "source": source,
                "issues": [
                    issue(
                        "E111",
                        "review",
                        "Excel 文件包含多个工作表，请使用 --sheet 指定一个工作表。",
                        sheet_names=source["sheet_names"],
                    )
                ],
            }
        inspection = inspect_major_frame(
            frame,
            source,
            requested_sample_column,
            requested_group_column,
        )
        if inspection["status"] != "ready":
            return {
                "status": "blocked",
                "operation": "harker_plot",
                "input_inspection": inspection,
                "issues": [
                    issue(
                        "E651",
                        "review",
                        "输入数据未通过安全检查，因此没有生成图像。",
                    )
                ],
            }

        available = [
            item["analyte"]
            for item in inspection["analytes"]["recognized"]
        ]
        units = {
            item["analyte"]: item["unit"]
            for item in inspection["analytes"]["recognized"]
        }
        x_analyte = resolve_analyte_selection(
            requested_x, available, "--x"
        )
        y_analytes = resolve_analyte_list(
            requested_y, available, "--y"
        )
        if not y_analytes:
            y_analytes = default_harker_y(available, x_analyte)
        if not y_analytes:
            raise PlottingError(
                "没有可自动选择的 Harker 纵轴变量，请使用 --y 明确指定。"
            )
        if x_analyte in y_analytes:
            raise PlottingError("Harker 图的 X 和 Y 变量不能相同。")
        if len(y_analytes) > MAX_PANELS:
            raise PlottingError(
                f"单张 Harker 图最多支持 {MAX_PANELS} 个纵轴面板。"
            )
        resolved_columns = (
            columns
            if columns is not None
            else automatic_columns(len(y_analytes))
        )

        canonical = prepare_geochem_frame(frame, inspection)
        sample_column = inspection["sample_id_candidates"][0]
        group_column = (
            inspection["group_candidates"][0]
            if len(inspection["group_candidates"]) == 1
            else None
        )
        canonical, groups = filter_requested_groups(
            canonical, group_column, requested_groups
        )
        resolved_height = (
            height_mm
            if height_mm is not None
            else automatic_height(len(y_analytes), resolved_columns)
        )
        validate_export_parameters(width_mm, resolved_height, dpi)
        resolved_stem = stem or f"harker_{x_analyte.lower()}"
        figure_paths, source_path, report_path = output_targets(
            output_dir, resolved_stem
        )
        ensure_outputs_available(
            [*figure_paths, source_path, report_path], overwrite
        )

        figure, plot_info = build_harker_figure(
            canonical,
            sample_column,
            group_column,
            groups,
            x_analyte,
            y_analytes,
            units,
            title,
            width_mm,
            resolved_height,
            resolved_columns,
            axes_frame,
            margin_fraction,
            style_preset=style_preset,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        save_figure_files(figure, figure_paths, dpi=dpi)
        source_columns = [sample_column]
        if group_column is not None:
            source_columns.append(group_column)
        source_columns.extend([x_analyte, *y_analytes])
        canonical.loc[:, source_columns].to_csv(
            source_path,
            index=False,
            encoding="utf-8",
            float_format="%.10g",
        )
        plt.close(figure)
        figure = None

        run_issues = list(inspection["issues"])
        incomplete = {
            analyte: count
            for analyte, count in plot_info["missing_pairs"].items()
            if count
        }
        if incomplete:
            run_issues.append(
                issue(
                    "W651",
                    "warning",
                    "部分 Harker 面板存在缺失配对，已跳过相应散点。",
                    missing_pairs=incomplete,
                )
            )
        if plot_info["palette_repeated"] or plot_info["marker_repeated"]:
            run_issues.append(
                issue(
                    "W652",
                    "warning",
                    "分组数量超过基础颜色或符号数量；建议筛选分组或分图。",
                    group_count=plot_info["group_count"],
                )
            )
        mixed_groups = potentially_mixed_harker_groups(groups)
        if mixed_groups:
            run_issues.append(
                issue(
                    "W653",
                    "warning",
                    "分组名称提示图中混合了差异很大的岩石类型；"
                    "解释成岩浆演化趋势前应筛选成分与成因上可比较的样品组。",
                    flagged_groups=mixed_groups,
                )
            )

        report = {
            "status": "ready",
            "operation": "harker_plot",
            "source": source,
            "figure_contract": {
                "core_conclusion": (
                    "Show how selected whole-rock analytes covary with one "
                    "declared differentiation index across samples and groups."
                ),
                "archetype": "quantitative grid",
                "backend": "Python/matplotlib",
                "role": "comparative and discovery evidence",
                "evidence": "paired whole-rock concentrations",
                "target_output": "double-column publication figure",
                "review_risks": [
                    "unit ambiguity",
                    "missing paired values",
                    "mixed lithologies or unrelated magma series",
                    "correlation interpreted as process",
                    "overplotting and group confusion",
                ],
            },
            "configuration": {
                "sample_column": sample_column,
                "group_column": group_column,
                "groups": groups,
                "x": x_analyte,
                "y": y_analytes,
                "units": {key: units[key] for key in [x_analyte, *y_analytes]},
                "trend_lines": "none",
                "axes_frame": axes_frame,
                "linear_limit_policy": (
                    "adaptive_linear_clean_outward_bounds"
                ),
                "margin_fraction": margin_fraction,
                "columns": resolved_columns,
                "columns_mode": (
                    "explicit" if columns is not None else "automatic"
                ),
                "width_mm": width_mm,
                "height_mm": resolved_height,
                "png_dpi": dpi,
                "tiff_dpi": dpi,
                "style_preset": style_preset,
            },
            "plot": plot_info,
            "outputs": [
                shareable_file_record(path) for path in figure_paths
            ],
            "source_data": shareable_file_record(source_path),
            "submission_qa": {
                "final_size_mm": [width_mm, resolved_height],
                "svg_text_editable": True,
                "pdf_font_type": 42,
                "raster_dpi": dpi,
                "tiff_compression": "LZW",
                "white_background": True,
                "shared_legend": group_column is not None,
                "colourblind_support": "group colour plus marker shape",
                "source_data_exported": True,
            },
            "report_file": report_path.name,
            "issues": run_issues,
            "interpretation_guidance": [
                "Describe direction, curvature, scatter, clusters, and outliers before proposing a process.",
                "Check whether compared samples belong to a coherent suite before interpreting a differentiation trend.",
                "Consider alteration, analytical uncertainty, mixing, assimilation, and source variation as alternatives.",
                "Do not treat an apparent linear relation as proof of fractional crystallization.",
            ],
            "scientific_caveat": (
                "Harker covariance alone does not identify a unique "
                "petrogenetic process or establish genetic relationships."
            ),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    except (
        InspectionError,
        PlottingError,
        OSError,
        ValueError,
    ) as exc:
        return harker_error(input_path, str(exc))
    finally:
        if figure is not None:
            plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成可自定义 X/Y 变量的投稿级 Harker 图解。"
    )
    parser.add_argument("input", type=Path, help="CSV、TXT 或 Excel 输入表格")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stem", help="不含扩展名的输出文件名")
    parser.add_argument("--sheet", help="Excel 工作表名称或编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选分组列")
    parser.add_argument("--x", default=DEFAULT_X, help="横轴变量，默认 SiO2")
    parser.add_argument(
        "--y", help="逗号分隔的纵轴变量；不指定时自动选择常用主量氧化物"
    )
    parser.add_argument("--groups", help="逗号分隔的待绘制分组")
    parser.add_argument("--title", help="可选图题")
    parser.add_argument("--width-mm", type=float, default=183.0)
    parser.add_argument(
        "--height-mm",
        type=float,
        help="图高；不指定时按面板数自动选择投稿尺寸",
    )
    parser.add_argument(
        "--columns",
        type=int,
        help="每行面板数（1–4）；不指定时自动选择紧凑布局",
    )
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument(
        "--axes-frame",
        choices=("open", "full"),
        default="full",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=0.06,
        help="线性坐标数据边距比例，默认 0.06",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    report = plot_harker_path(
        args.input,
        args.output_dir,
        stem=args.stem,
        requested_sheet=args.sheet,
        requested_sample_column=args.sample_column,
        requested_group_column=args.group_column,
        requested_x=args.x,
        requested_y=args.y,
        requested_groups=args.groups,
        title=args.title,
        width_mm=args.width_mm,
        height_mm=args.height_mm,
        columns=args.columns,
        dpi=args.dpi,
        axes_frame=args.axes_frame,
        margin_fraction=args.margin,
        overwrite=args.overwrite,
    )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"Harker 绘图完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
