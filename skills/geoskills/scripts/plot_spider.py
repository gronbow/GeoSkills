#!/usr/bin/env python3
"""Create a publication-oriented normalized trace-element spider diagram."""

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

from inspect_data import InspectionError, issue
from inspect_spider_data import inspect_spider_frame, read_spider_table
from normalize_ree import NormalizationError
from normalize_spider import (
    DEFAULT_REFERENCE_KEY,
    REFERENCE_PATHS,
    load_spider_reference,
    normalize_spider_frame,
    resolve_reference,
    spider_reference_summary,
)
from geoskills_core.export import save_figure_files
from geoskills_core.plotting import (
    PUBLICATION_DOUBLE_COLUMN,
    publication_styled,
)
from plot_ree import (
    AXES_FRAMES,
    DEFAULT_LOG_Y_MARGIN,
    FORMATS,
    GRID_STYLES,
    LEGEND_LAYOUTS,
    MARKERS,
    PlottingError,
    build_figure,
    output_targets,
)


def parse_spider_elements(
    selection: str | None,
    available: list[str],
    reference_order: list[str],
    default_order: list[str],
) -> list[str]:
    """Resolve a user selection while preserving the cited incompatibility order."""
    available_set = set(available)
    if selection is None:
        selected = [element for element in default_order if element in available_set]
        if len(selected) < 5:
            selected = [
                element for element in reference_order if element in available_set
            ]
    else:
        canonical = {element.casefold(): element for element in reference_order}
        requested: list[str] = []
        for item in selection.split(","):
            cleaned = item.strip()
            if not cleaned:
                continue
            element = canonical.get(cleaned.casefold())
            if element is None:
                raise PlottingError(f"未知蛛网图元素：{cleaned}。")
            requested.append(element)
        if len(set(requested)) != len(requested):
            raise PlottingError("--elements 中不能重复同一个元素。")
        missing = [element for element in requested if element not in available_set]
        if missing:
            raise PlottingError(
                "所选元素未在已验证输入中出现：" + ", ".join(missing) + "。"
            )
        requested_set = set(requested)
        selected = [
            element for element in reference_order if element in requested_set
        ]
    if len(selected) < 5:
        raise PlottingError("微量元素蛛网图至少需要 5 个已验证元素。")
    return selected


def shareable_file_record(path: Path) -> dict[str, Any]:
    """Describe an output without leaking a private local directory."""
    return {
        "format": path.suffix.lower().lstrip("."),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def plotting_error(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "trace_element_spider_plot",
        "source": {"format": path.suffix.lower()},
        "issues": [issue("E550", "error", message)],
    }


@publication_styled(preset_parameter="style_preset")
def plot_spider_path(
    input_path: Path,
    output_dir: Path,
    stem: str | None = None,
    reference_key: str = DEFAULT_REFERENCE_KEY,
    requested_sheet: str | None = None,
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
    requested_elements: str | None = None,
    title: str | None = None,
    width_mm: float = 183.0,
    height_mm: float = 120.0,
    dpi: int = 600,
    y_margin: float = DEFAULT_LOG_Y_MARGIN,
    axes_frame: str = "full",
    legend_layout: str = "inside-auto",
    grid_style: str = "none",
    show_sample_ids: bool = True,
    group_legend_title: str = "Group",
    show_reference_note: bool = True,
    overwrite: bool = False,
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> dict[str, Any]:
    """Validate input and export a submission-oriented spider-plot bundle."""
    figure = None
    try:
        if not 72 <= dpi <= 1200:
            raise PlottingError("PNG/TIFF 分辨率必须在 72–1200 dpi 之间。")
        reference_path = resolve_reference(reference_key)
        reference, reference_values = load_spider_reference(reference_path)
        resolved_stem = stem or f"spider_{reference_key}"
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

        frame, source = read_spider_table(input_path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "trace_element_spider_plot",
                "source": source,
                "reference": spider_reference_summary(
                    reference_path, reference
                ),
                "issues": [
                    issue(
                        "E111",
                        "review",
                        "Excel 文件包含多个工作表，请使用 --sheet 指定一个工作表。",
                        sheet_names=source["sheet_names"],
                    )
                ],
            }

        inspection = inspect_spider_frame(
            frame,
            source,
            requested_sample_column,
            requested_group_column,
        )
        if inspection["status"] != "ready":
            return {
                "status": "blocked",
                "operation": "trace_element_spider_plot",
                "reference": spider_reference_summary(
                    reference_path, reference
                ),
                "input_inspection": inspection,
                "issues": [
                    issue(
                        "E551",
                        "review",
                        "输入数据未通过安全检查，因此没有生成图像。",
                    )
                ],
            }

        recognized_elements = {
            item["element"]
            for item in inspection["trace_elements"]["recognized"]
        }
        available = [
            element
            for element in reference["element_order"]
            if element in recognized_elements
        ]
        elements = parse_spider_elements(
            requested_elements,
            available,
            reference["element_order"],
            reference["default_plot_order"],
        )
        normalized, conversions = normalize_spider_frame(
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
        is_printed_primitive_mantle = (
            reference["id"] == "PrimitiveMantle_SM89"
        )
        if reference["id"] == "PrimitiveMantleModified_SM89":
            axis_reference = "modified primitive mantle"
        elif is_printed_primitive_mantle:
            axis_reference = "primitive mantle"
        else:
            axis_reference = "N-MORB"
        table_label = (
            "Table 1 footnote b"
            if reference["id"] == "PrimitiveMantleModified_SM89"
            else "Table 1"
        )
        note_reference = (
            "Normalization: Sun & McDonough (1989) "
            + axis_reference
            + f" ({table_label})"
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
            y_label=f"Sample / {axis_reference}",
            reference_note=note_reference,
            x_tick_labelsize=6.2,
            x_tick_stagger=True,
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
                    "W551",
                    "warning",
                    "样品数超过 15，图例和曲线可能拥挤；建议按组分图。",
                    sample_count=plot_info["plotted_sample_count"],
                )
            )
        if plot_info["palette_repeated"]:
            run_issues.append(
                issue(
                    "W552",
                    "warning",
                    "分组数量超过基础色板，部分颜色被重复使用。",
                    group_count=plot_info["group_count"],
                )
            )
        if plot_info["line_style_repeated"]:
            run_issues.append(
                issue(
                    "W553",
                    "warning",
                    "分组数量超过基础线型数量；建议按组分图。",
                    group_count=plot_info["group_count"],
                )
            )
        if plot_info["marker_repeated"]:
            run_issues.append(
                issue(
                    "W554",
                    "warning",
                    "样品数超过可用符号数量，部分符号重复；建议按组分图。",
                    sample_count=plot_info["plotted_sample_count"],
                    unique_marker_count=len(MARKERS),
                )
            )
        if plot_info["skipped_samples"]:
            run_issues.append(
                issue(
                    "W555",
                    "warning",
                    "部分样品在所选元素上全部缺失，未绘制曲线。",
                    samples=plot_info["skipped_samples"],
                )
            )
        if plot_info["legend_fallback"]:
            run_issues.append(
                issue(
                    "W556",
                    "warning",
                    "图内图例会遮挡数据，已自动改为右侧布局。",
                )
            )
        if is_printed_primitive_mantle and {"Cs", "Pb"} & set(elements):
            run_issues.append(
                issue(
                    "W557",
                    "warning",
                    "当前使用 Table 1 原始地幔列；原文脚注另给出用于"
                    " modified mantle-normalized diagrams 的 Cs 和 Pb 值。"
                    "本程序没有静默替换，请在研究方法中明确所选版本。",
                    selected_affected_elements=sorted(
                        {"Cs", "Pb"} & set(elements)
                    ),
                )
            )

        report = {
            "status": "ready",
            "operation": "trace_element_spider_plot",
            "source": source,
            "reference": spider_reference_summary(reference_path, reference),
            "figure_contract": {
                "core_conclusion": (
                    "Compare relative multi-element enrichment, depletion, "
                    "and visible anomalies among samples and groups against "
                    "one declared reference composition."
                ),
                "archetype": "single-panel quantitative figure",
                "backend": "Python/matplotlib",
                "role": "comparative and discovery evidence",
                "evidence": (
                    "Sample-to-reference ratios across a cited "
                    "incompatibility-ordered element sequence"
                ),
                "target_output": "double-column publication figure",
                "review_risks": [
                    "reference-composition ambiguity",
                    "ppm versus oxide wt% unit conversion",
                    "log-axis invalid values",
                    "missing-value connections",
                    "overplotting and legend crowding",
                    "overinterpretation of individual anomalies",
                ],
            },
            "configuration": {
                "sample_column": sample_column,
                "group_column": group_column,
                "elements": elements,
                "element_order_policy": (
                    "Sun and McDonough (1989) incompatibility order"
                ),
                "reference_key": reference_key,
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
            "oxide_conversions": conversions,
            "plot": plot_info,
            "outputs": [
                shareable_file_record(path) for path in figure_paths
            ],
            "source_data": shareable_file_record(source_data_path),
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
                    else (
                        "group colour plus line style; sample symbols repeat "
                        "with warning"
                    )
                ),
                "source_data_exported": True,
            },
            "report_file": report_path.name,
            "issues": run_issues,
            "interpretation_guidance": [
                "Describe relative enrichment, depletion, slopes, and visible anomalies before proposing causes.",
                "Check whether mobile elements such as Rb, Ba, K, Sr, and Pb may reflect alteration or fluid effects.",
                "Evaluate Nb-Ta, Sr, P, and Ti anomalies with petrography, mineral chemistry, and major-element evidence.",
                "Treat gaps as missing measurements rather than zero concentrations.",
                "Do not assign a tectonic setting from a spider diagram alone.",
            ],
            "scientific_caveat": (
                "A normalized trace-element pattern does not uniquely identify "
                "mantle source, melting degree, fractionating minerals, "
                "alteration history, or tectonic setting."
            ),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    except (
        InspectionError,
        NormalizationError,
        PlottingError,
        OSError,
        ValueError,
    ) as exc:
        return plotting_error(input_path, str(exc))
    finally:
        if figure is not None:
            plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "生成 Sun & McDonough (1989) 原始地幔或 N-MORB 标准化"
            "微量元素蛛网图。"
        )
    )
    parser.add_argument("input", type=Path, help="CSV、TXT 或 Excel 输入表格")
    parser.add_argument("--output-dir", type=Path, required=True, help="输出文件夹")
    parser.add_argument("--stem", help="不含扩展名的输出文件名")
    parser.add_argument(
        "--reference",
        choices=tuple(REFERENCE_PATHS),
        default=DEFAULT_REFERENCE_KEY,
        help=(
            "标准化方案：pm-sm89-modified（默认）、pm-sm89 "
            "或 nmorb-sm89"
        ),
    )
    parser.add_argument("--sheet", help="Excel 工作表名称，或从 0 开始的编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选分组列")
    parser.add_argument(
        "--elements",
        help="逗号分隔的元素；程序仍按文献不相容性顺序排列",
    )
    parser.add_argument("--title", help="可选图题；论文图通常留空")
    parser.add_argument("--width-mm", type=float, default=183.0, help="图宽")
    parser.add_argument("--height-mm", type=float, default=120.0, help="图高")
    parser.add_argument("--dpi", type=int, default=600, help="PNG/TIFF 分辨率")
    parser.add_argument(
        "--y-margin",
        type=float,
        default=DEFAULT_LOG_Y_MARGIN,
        help="对数纵坐标边距比例，默认 0.08",
    )
    parser.add_argument(
        "--axes-frame",
        choices=AXES_FRAMES,
        default="full",
        help="坐标轴边框：open（左下）或 full（四边框，默认）",
    )
    parser.add_argument(
        "--legend-layout",
        choices=LEGEND_LAYOUTS,
        default="inside-auto",
        help="图例：outside 或 inside-auto（默认，必要时自动移到右侧）",
    )
    parser.add_argument(
        "--grid-style",
        choices=GRID_STYLES,
        default="none",
        help="横向网格：none（默认）或 major",
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
    report = plot_spider_path(
        args.input,
        args.output_dir,
        stem=args.stem,
        reference_key=args.reference,
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
    print(f"蛛网图绘制完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
