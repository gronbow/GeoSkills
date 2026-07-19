#!/usr/bin/env python3
"""Create a publication-oriented chondrite-normalized REE pattern figure."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
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
plt.rcParams["axes.spines.right"] = False
plt.rcParams["axes.spines.top"] = False
plt.rcParams["legend.frameon"] = False


GROUP_COLORS = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#6A3D9A",
    "#8C564B",
    "#4D4D4D",
    "#56B4E9",
]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "h"]
LINE_STYLES = ["-", "--", "-.", ":"]
FORMATS = ("png", "svg", "pdf")


class PlottingError(Exception):
    """An expected problem that makes figure creation unsafe."""


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
    occurrence_by_group: dict[str, int] = {}
    skipped_samples: list[str] = []

    fig, ax = plt.subplots(
        figsize=(width_mm / 25.4, height_mm / 25.4),
        facecolor="white",
    )
    x = np.arange(len(elements))
    ax.axhline(1.0, color="#767676", linewidth=0.8, linestyle="--", zorder=1)

    for row_index, (sample, group) in enumerate(zip(samples, groups)):
        y = normalized.loc[
            normalized.index[row_index], [f"{element}_N" for element in elements]
        ].to_numpy(dtype=float)
        if not np.isfinite(y).any():
            skipped_samples.append(str(sample))
            continue
        within_group = (
            row_index if group_column is None else occurrence_by_group.get(group, 0)
        )
        occurrence_by_group[group] = within_group + 1
        label = str(sample) if group_column is None else f"{sample} [{group}]"
        ax.plot(
            x,
            y,
            color=color_by_group[group],
            linestyle=LINE_STYLES[(within_group // len(MARKERS)) % len(LINE_STYLES)],
            linewidth=1.2,
            marker=MARKERS[within_group % len(MARKERS)],
            markersize=3.8,
            markeredgecolor="white",
            markeredgewidth=0.45,
            label=label,
            zorder=2,
        )

    if not ax.lines[1:]:
        plt.close(fig)
        raise PlottingError("所有样品在所选元素上都为空，无法绘图。")

    ax.set_yscale("log")
    ax.set_xlim(-0.4, len(elements) - 0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(elements)
    ax.set_xlabel("Rare-earth element", fontsize=8)
    ax.set_ylabel(f"Sample / C1 chondrite\n({reference_id})", fontsize=8)
    ax.tick_params(axis="both", labelsize=7, width=0.7, length=3)
    ax.yaxis.set_major_locator(LogLocator(base=10))
    ax.yaxis.set_major_formatter(LogFormatterMathtext(base=10))
    ax.yaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10) * 0.1))
    ax.grid(which="major", axis="y", color="#D9D9D9", linewidth=0.55)
    ax.grid(which="minor", axis="y", color="#EEEEEE", linewidth=0.35)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_linewidth(0.8)
    if title:
        ax.set_title(title, fontsize=9, pad=7)

    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="center right",
        bbox_to_anchor=(0.985, 0.54),
        fontsize=6.5,
        title="Samples" if group_column is None else f"Samples [{group_column}]",
        title_fontsize=7,
        handlelength=2.2,
        labelspacing=0.55,
    )
    fig.text(
        0.11,
        0.035,
        "Normalization: Sun & McDonough (1989), Table 1; dashed line = unity.",
        fontsize=6,
        color="#4D4D4D",
        ha="left",
    )
    fig.subplots_adjust(
        left=0.11,
        right=0.72,
        bottom=0.17,
        top=0.90 if title else 0.95,
    )
    return fig, {
        "sample_count": len(samples),
        "group_count": len(group_order),
        "group_column": group_column,
        "skipped_samples": skipped_samples,
        "palette_repeated": len(group_order) > len(GROUP_COLORS),
    }


def file_record(path: Path) -> dict[str, Any]:
    return {
        "format": path.suffix.lower().lstrip("."),
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def output_targets(output_dir: Path, stem: str) -> tuple[list[Path], Path]:
    if not stem or Path(stem).name != stem or Path(stem).suffix:
        raise PlottingError("输出名称必须是不含路径和扩展名的文件名。")
    figures = [output_dir / f"{stem}.{extension}" for extension in FORMATS]
    return figures, output_dir / f"{stem}.report.json"


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
    dpi: int = 300,
    overwrite: bool = False,
    reference_path: Path = DEFAULT_REFERENCE_PATH,
) -> dict[str, Any]:
    """Validate raw input and export PNG, SVG, and PDF from one figure."""
    figure = None
    try:
        if not 72 <= dpi <= 1200:
            raise PlottingError("PNG 分辨率必须在 72–1200 dpi 之间。")
        resolved_stem = stem or f"{input_path.stem}_ree_pattern"
        figure_paths, report_path = output_targets(output_dir, resolved_stem)
        existing = [path for path in [*figure_paths, report_path] if path.exists()]
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
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        for path in figure_paths:
            save_options: dict[str, Any] = {"facecolor": "white"}
            if path.suffix.lower() == ".png":
                save_options["dpi"] = dpi
            figure.savefig(path, **save_options)
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
                "core_conclusion": "Display relative REE enrichment, depletion, slopes, and visible anomalies without assigning a unique petrogenetic cause.",
                "archetype": "single-panel quantitative pattern plot",
                "backend": "Python/matplotlib",
                "evidence": "Sample-to-Chondrite_SM89 ratios across ordered La-Lu elements",
                "review_risks": [
                    "log-axis invalid values",
                    "missing-value connections",
                    "overplotting and legend crowding",
                    "editable vector text",
                ],
            },
            "configuration": {
                "sample_column": sample_column,
                "group_column": group_column,
                "elements": elements,
                "y_scale": "log10",
                "unity_line": True,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "png_dpi": dpi,
                "formats": list(FORMATS),
            },
            "plot": plot_info,
            "outputs": [file_record(path) for path in figure_paths],
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
    parser.add_argument("--dpi", type=int, default=300, help="PNG 分辨率，默认 300 dpi")
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
        args.stem,
        args.sheet,
        args.sample_column,
        args.group_column,
        args.elements,
        args.title,
        args.width_mm,
        args.height_mm,
        args.dpi,
        args.overwrite,
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
