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
from matplotlib.ticker import LogFormatterMathtext, LogLocator

from inspect_data import InspectionError, inspect_frame, issue, read_table
from normalize_ree import (
    DEFAULT_REFERENCE_PATH,
    NormalizationError,
    load_reference,
    normalize_frame,
    reference_summary,
)


# Keep text editable in vector exports and use portable sans-serif fallbacks.
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Liberation Sans"]
plt.rcParams["svg.fonttype"] = "none"
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["font.size"] = 7
plt.rcParams["axes.labelsize"] = 7.5
plt.rcParams["axes.linewidth"] = 0.7
plt.rcParams["xtick.labelsize"] = 7
plt.rcParams["ytick.labelsize"] = 7
plt.rcParams["xtick.major.width"] = 0.65
plt.rcParams["ytick.major.width"] = 0.65
plt.rcParams["xtick.minor.width"] = 0.5
plt.rcParams["ytick.minor.width"] = 0.5
plt.rcParams["axes.spines.right"] = False
plt.rcParams["axes.spines.top"] = False
plt.rcParams["legend.frameon"] = False


GROUP_COLORS = [
    "#3569A8",
    "#D06B27",
    "#159A80",
    "#A84F7A",
    "#7655A5",
    "#8B6B4A",
    "#4D4D4D",
    "#4F9BC1",
]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "h", "p", "*"]
LINE_STYLES = ["-", "--", "-.", ":"]
FORMATS = ("svg", "pdf", "tiff", "png")
DEFAULT_LOG_Y_MARGIN = 0.08


class PlottingError(Exception):
    """An expected problem that makes figure creation unsafe."""


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
) -> tuple[plt.Figure, dict[str, Any]]:
    """Build one figure; export callers must reuse this same figure object."""
    if not 50 <= width_mm <= 400 or not 50 <= height_mm <= 400:
        raise PlottingError("图像宽度和高度必须在 50–400 mm 之间。")

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
    group_counts = Counter(groups)
    skipped_samples: list[str] = []

    fig, ax = plt.subplots(
        figsize=(width_mm / 25.4, height_mm / 25.4),
        facecolor="white",
    )
    x = np.arange(len(elements))
    value_columns = [f"{element}_N" for element in elements]
    all_values = normalized.loc[:, value_columns].to_numpy(dtype=float)
    (
        y_lower,
        y_upper,
        data_min,
        data_max,
        margin_decades,
    ) = adaptive_log_y_limits(all_values, y_margin)
    unity_line_visible = y_lower <= 1.0 <= y_upper

    ax.set_yscale("log")
    ax.set_ylim(y_lower, y_upper)
    if unity_line_visible:
        ax.axhline(1.0, color="#767676", linewidth=0.8, linestyle="--", zorder=1)

    plotted_sample_count = 0
    for row_index, (sample, group) in enumerate(zip(samples, groups)):
        y = normalized.loc[
            normalized.index[row_index], value_columns
        ].to_numpy(dtype=float)
        y = np.where(np.isfinite(y) & (y > 0), y, np.nan)
        if not np.isfinite(y).any():
            skipped_samples.append(str(sample))
            continue
        ax.plot(
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
        plotted_sample_count += 1

    if plotted_sample_count == 0:
        plt.close(fig)
        raise PlottingError("所有样品在所选元素上都为空，无法绘图。")

    ax.set_xlim(-0.4, len(elements) - 0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(elements)
    # Element symbols already define the categorical x axis; omitting a repeated
    # x-axis title preserves space and improves readability after journal scaling.
    ax.set_xlabel("")
    ax.set_ylabel("Sample / C1 chondrite")
    ax.tick_params(axis="both", which="major", direction="out", length=3)
    ax.tick_params(axis="y", which="minor", direction="out", length=1.8)
    ax.yaxis.set_major_locator(LogLocator(base=10))
    ax.yaxis.set_major_formatter(LogFormatterMathtext(base=10))
    ax.yaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10) * 0.1))
    ax.set_axisbelow(True)
    ax.grid(which="major", axis="y", color="#D7D7D7", linewidth=0.45)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_linewidth(0.7)
    if title:
        ax.set_title(title, fontsize=8.5, fontweight="bold", loc="left", pad=7)

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
        for index, group in enumerate(groups)
    ]
    if group_column is None:
        fig.legend(
            sample_handles,
            [str(sample) for sample in samples],
            loc="upper left",
            bbox_to_anchor=(0.755, 0.91),
            fontsize=6.2,
            title="Sample ID",
            title_fontsize=6.6,
            handlelength=1.6,
            labelspacing=0.45,
            borderaxespad=0,
        )
    else:
        group_handles = [
            Line2D(
                [0],
                [0],
                color=color_by_group[group],
                linewidth=1.6,
                linestyle=style_by_group[group],
            )
            for group in group_order
        ]
        group_labels = [
            textwrap.fill(f"{group} (n={group_counts[group]})", width=26)
            for group in group_order
        ]
        fig.legend(
            group_handles,
            group_labels,
            loc="upper left",
            bbox_to_anchor=(0.755, 0.91),
            fontsize=6.1,
            title="Rock type" if str(group_column).casefold() == "group" else str(group_column),
            title_fontsize=6.6,
            handlelength=1.8,
            labelspacing=0.5,
            borderaxespad=0,
        )
        fig.legend(
            sample_handles,
            [str(sample) for sample in samples],
            loc="upper left",
            bbox_to_anchor=(0.755, 0.57),
            fontsize=6.1,
            title="Sample ID (symbol)",
            title_fontsize=6.6,
            handlelength=1.35,
            labelspacing=0.45,
            columnspacing=0.8,
            ncol=2 if len(samples) >= 6 else 1,
            borderaxespad=0,
        )
    reference_note = "Normalization: Sun & McDonough (1989) C1 chondrite"
    if unity_line_visible:
        reference_note += "; dashed line = unity."
    else:
        reference_note += "; limits adapt to positive normalized data."
    fig.text(
        0.095,
        0.045,
        reference_note,
        fontsize=5.8,
        color="#4D4D4D",
        ha="left",
    )
    fig.subplots_adjust(
        left=0.095,
        right=0.73,
        bottom=0.16,
        top=0.90 if title else 0.95,
    )
    return fig, {
        "normalization_id": reference_id,
        "y_limits": {
            "lower": y_lower,
            "upper": y_upper,
            "data_min": data_min,
            "data_max": data_max,
            "margin_fraction": y_margin,
            "margin_decades": margin_decades,
            "policy": "adaptive_log10",
        },
        "unity_line_visible": unity_line_visible,
        "sample_count": len(samples),
        "group_count": len(group_order),
        "group_column": group_column,
        "skipped_samples": skipped_samples,
        "palette_repeated": len(group_order) > len(GROUP_COLORS),
        "line_style_repeated": len(group_order) > len(LINE_STYLES),
        "legend_strategy": "separate group colour/line-style and sample-symbol keys"
        if group_column is not None
        else "sample key",
        "colour_is_not_the_only_identifier": True,
        "group_encoding": "colour plus line style",
        "sample_encoding": "unique symbol",
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
    overwrite: bool = False,
    reference_path: Path = DEFAULT_REFERENCE_PATH,
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
            y_margin,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        for path in figure_paths:
            save_options: dict[str, Any] = {"facecolor": "white"}
            if path.suffix.lower() in {".png", ".tiff"}:
                save_options["dpi"] = dpi
            if path.suffix.lower() == ".tiff":
                save_options["pil_kwargs"] = {"compression": "tiff_lzw"}
            figure.savefig(path, **save_options)
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
        if plot_info["sample_count"] > 15:
            run_issues.append(
                issue(
                    "W501",
                    "warning",
                    "样品数超过 15，图例和曲线可能拥挤；建议按组分图。",
                    sample_count=plot_info["sample_count"],
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
        if plot_info["skipped_samples"]:
            run_issues.append(
                issue(
                    "W503",
                    "warning",
                    "部分样品在所选元素上全部缺失，未绘制曲线。",
                    samples=plot_info["skipped_samples"],
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
                "width_mm": width_mm,
                "height_mm": height_mm,
                "png_dpi": dpi,
                "tiff_dpi": dpi,
                "formats": list(FORMATS),
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
                "colourblind_support": "group colour plus line style; unique sample symbol",
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
