#!/usr/bin/env python3
"""Create the reviewed, non-extrapolated K2O-SiO2 magma-series diagram."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

from geoskills_core.classification import (
    ClassificationModel,
    ClassificationModelError,
    add_classification_background,
    classify_coordinates,
    load_classification_model,
)
from geoskills_core.errors import PlottingError
from geoskills_core.export import save_figure_files
from geoskills_core.plotting import (
    GROUP_COLORS,
    MARKERS,
    PUBLICATION_DOUBLE_COLUMN,
    configure_boxed_legend,
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
    ensure_outputs_available,
    filter_requested_groups,
    group_style_map,
    output_targets,
    shareable_file_record,
    validate_export_parameters,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = (
    SKILL_DIR
    / "assets"
    / "classification"
    / "k2o-sio2-pt76-r89-original.json"
)
MODEL_ID = "k2o-sio2-pt76-r89-original"
COMPOSITION_BASES = ("unknown", "anhydrous-normalized")
LEGEND_LAYOUTS = ("inside-auto", "outside")


def model_summary(path: Path, model: ClassificationModel) -> dict[str, Any]:
    """Return share-safe provenance for the pinned scientific model."""

    domain_x = [
        min(point[0] for field in model.fields for point in field.vertices),
        max(point[0] for field in model.fields for point in field.vertices),
    ]
    return {
        "id": model.id,
        "display_name": model.display_name,
        "version": model.version,
        "citation": model.source["citation"],
        "doi": model.source.get("doi"),
        "geometry_doi": model.source.get("geometry_doi"),
        "geometry_reference": model.source["geometry_reference"],
        "scientific_review": dict(model.scientific_review),
        "asset": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "complete_classification_domain_x": domain_x,
        "boundary_policy": {
            "on_boundary": "review",
            "outside_complete_domain": "unclassified",
            "extrapolated": False,
        },
    }


def classify_frame(
    frame: pd.DataFrame,
    sample_column: str,
    group_column: str | None,
    model: ClassificationModel,
) -> pd.DataFrame:
    """Return coordinates and conservative classification states."""

    output = frame.loc[:, [sample_column]].copy()
    if group_column is not None:
        output[group_column] = frame[group_column]
    silica = pd.to_numeric(frame["SiO2"], errors="coerce").astype("float64")
    potassium = pd.to_numeric(frame["K2O"], errors="coerce").astype("float64")
    valid = (
        silica.notna()
        & potassium.notna()
        & np.isfinite(silica)
        & np.isfinite(potassium)
        & silica.ge(0)
        & potassium.ge(0)
    )
    output["SiO2"] = silica.where(valid)
    output["K2O"] = potassium.where(valid)
    records = classify_coordinates(output["SiO2"], output["K2O"], model)
    labels = {field.id: field.label.replace("\n", " ") for field in model.fields}
    output["K2O_SiO2_status"] = [str(item["status"]) for item in records]
    output["K2O_SiO2_field"] = [item["field_id"] for item in records]
    output["K2O_SiO2_name"] = [
        None if item["field_id"] is None else labels[str(item["field_id"])]
        for item in records
    ]
    return output


def _legend_overlaps(
    ax: Any,
    legend: Any,
    points: np.ndarray,
    field_texts: list[Any],
) -> bool:
    ax.figure.canvas.draw()
    renderer = ax.figure.canvas.get_renderer()
    box = legend.get_window_extent(renderer).expanded(1.04, 1.08)
    if points.size:
        display = ax.transData.transform(points)
        inside = (
            (display[:, 0] >= box.x0)
            & (display[:, 0] <= box.x1)
            & (display[:, 1] >= box.y0)
            & (display[:, 1] <= box.y1)
        )
        if inside.any():
            return True
    return any(
        box.overlaps(text.get_window_extent(renderer).expanded(1.02, 1.06))
        for text in field_texts
    )


def _add_legend(
    figure: Any,
    ax: Any,
    handles: list[Any],
    labels: list[str],
    points: np.ndarray,
    field_texts: list[Any],
    requested_layout: str,
) -> tuple[str, bool]:
    if requested_layout == "inside-auto":
        for location in ("lower right", "upper right", "lower left", "upper left"):
            legend = ax.legend(
                handles,
                labels,
                loc=location,
                fontsize=5.7,
                handletextpad=0.35,
                labelspacing=0.35,
                borderpad=0.45,
                frameon=True,
                fancybox=False,
            )
            configure_boxed_legend(legend)
            if not _legend_overlaps(ax, legend, points, field_texts):
                return f"inside_{location.replace(' ', '_')}", False
            legend.remove()
    figure.subplots_adjust(right=0.75)
    ax.legend(
        handles,
        labels,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        fontsize=5.8,
        handletextpad=0.4,
        labelspacing=0.38,
        frameon=False,
    )
    return "outside_right_fallback", requested_layout == "inside-auto"


@publication_styled(preset_parameter="style_preset")
def build_figure(
    classified: pd.DataFrame,
    sample_column: str,
    group_column: str | None,
    groups: list[str],
    model: ClassificationModel,
    title: str | None,
    width_mm: float,
    height_mm: float,
    legend_layout: str,
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> tuple[Any, dict[str, Any]]:
    """Build one fixed-geometry, non-extrapolated classification figure."""

    figure, ax = plt.subplots(figsize=(width_mm / 25.4, height_mm / 25.4))
    figure.subplots_adjust(
        left=0.105,
        right=0.965,
        bottom=0.20,
        top=0.93 if title else 0.965,
    )

    fills = ("#FAFAFA", "#F3F3F3")
    plot_labels = {
        "tholeiitic-series": "Tholeiitic\nseries",
        "calc-alkaline-series": "Calc-alkaline\nseries",
        "high-k-calc-alkaline-series": "High-K calc-alkaline\nseries",
        "shoshonitic-series": "Shoshonitic\nseries",
    }
    field_texts: list[Any] = []
    for index, field in enumerate(model.fields):
        ax.add_patch(
            Polygon(
                field.vertices,
                closed=True,
                facecolor=fills[index % len(fills)],
                edgecolor="none",
                zorder=0,
            )
        )
        if field.label_position is not None:
            field_texts.append(
                ax.text(
                    field.label_position[0],
                    field.label_position[1],
                    plot_labels.get(field.id, field.label),
                    ha="center",
                    va="center",
                    fontsize=5.2,
                    color="#555555",
                    linespacing=0.9,
                    zorder=2,
                )
            )

    add_classification_background(ax, model, add_labels=False)
    # Keep the scientific asset immutable while rendering chemical formulae
    # through Matplotlib's font-safe math text instead of Unicode subscripts.
    ax.set_xlabel(analyte_label("SiO2", "wt%"))
    ax.set_ylabel(analyte_label("K2O", "wt%"))
    domain_x = [
        min(point[0] for field in model.fields for point in field.vertices),
        max(point[0] for field in model.fields for point in field.vertices),
    ]
    for value in domain_x:
        ax.axvline(
            value,
            color="#8A8A8A",
            linewidth=0.55,
            linestyle=(0, (2.2, 2.2)),
            zorder=1,
        )

    styles = group_style_map(groups)
    finite = classified["SiO2"].notna() & classified["K2O"].notna()
    if group_column is None:
        ax.scatter(
            classified.loc[finite, "SiO2"],
            classified.loc[finite, "K2O"],
            s=28,
            c="#3569A8",
            marker="o",
            edgecolors="white",
            linewidths=0.55,
            alpha=0.94,
            zorder=4,
        )
        legend_position = "none"
        legend_fallback = False
    else:
        for group in groups:
            subset = classified.loc[classified[group_column].astype(str) == group]
            subset_finite = subset["SiO2"].notna() & subset["K2O"].notna()
            style = styles[group]
            ax.scatter(
                subset.loc[subset_finite, "SiO2"],
                subset.loc[subset_finite, "K2O"],
                s=28,
                c=style["color"],
                marker=style["marker"],
                edgecolors="white",
                linewidths=0.55,
                alpha=0.94,
                zorder=4,
            )
        handles = [
            Line2D(
                [],
                [],
                linestyle="none",
                marker=styles[group]["marker"],
                markerfacecolor=styles[group]["color"],
                markeredgecolor="white",
                markeredgewidth=0.5,
                markersize=5.5,
            )
            for group in groups
        ]
        labels = [
            f"{group} (n={int((classified[group_column].astype(str) == group).sum())})"
            for group in groups
        ]
        points = classified.loc[finite, ["SiO2", "K2O"]].to_numpy(dtype=float)
        legend_position, legend_fallback = _add_legend(
            figure,
            ax,
            handles,
            labels,
            points,
            field_texts,
            legend_layout,
        )

    ax.set_xticks(np.arange(45, 79, 5))
    ax.set_yticks(np.arange(0, 8, 1))
    ax.tick_params(axis="both", which="major", direction="out", length=3)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("#1A1A1A")
        spine.set_linewidth(0.75)
    if title:
        ax.set_title(title, fontsize=8, pad=6)
    figure.text(
        0.105,
        0.035,
        "Peccerillo & Taylor (1976); coordinates corrected by Rickwood (1989).\n"
        "Anhydrous 100% basis; no extrapolation; complete four-field domain: SiO2 48–63 wt%.",
        fontsize=5.3,
        color="#4D4D4D",
        ha="left",
        linespacing=1.15,
    )

    x_limits = model.x_axis.limits
    y_limits = model.y_axis.limits
    within_axes = (
        finite
        & classified["SiO2"].between(*x_limits)
        & classified["K2O"].between(*y_limits)
    )
    counts = Counter(classified["K2O_SiO2_status"].tolist())
    return figure, {
        "sample_count": int(len(classified)),
        "group_count": len(groups) if group_column is not None else 0,
        "visible_coordinate_count": int(within_axes.sum()),
        "outside_axes_count": int((finite & (~within_axes)).sum()),
        "classification_status_counts": dict(sorted(counts.items())),
        "field_counts": {
            str(key): int(value)
            for key, value in classified["K2O_SiO2_field"]
            .dropna()
            .value_counts()
            .items()
        },
        "x_limits": list(x_limits),
        "y_limits": list(y_limits),
        "complete_domain_x": domain_x,
        "legend_position": legend_position,
        "legend_fallback": legend_fallback,
        "axes_frame": "full",
        "palette_repeated": len(groups) > len(GROUP_COLORS),
        "marker_repeated": len(groups) > len(MARKERS),
        "colour_is_not_the_only_identifier": True,
    }


def _error(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "k2o_sio2_series_plot",
        "source": {"format": path.suffix.lower()},
        "issues": [issue("E800", "error", message)],
    }


def plot_k2o_sio2_path(
    input_path: Path,
    output_dir: Path,
    stem: str | None = None,
    requested_sheet: str | None = None,
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
    requested_groups: str | None = None,
    confirm_volcanic: bool = False,
    composition_basis: str = "unknown",
    title: str | None = None,
    width_mm: float = 150.0,
    height_mm: float = 120.0,
    dpi: int = 600,
    legend_layout: str = "inside-auto",
    overwrite: bool = False,
    model_path: Path = DEFAULT_MODEL_PATH,
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> dict[str, Any]:
    """Validate, classify, and export the reviewed K2O-SiO2 figure bundle."""

    figure = None
    try:
        if composition_basis not in COMPOSITION_BASES:
            raise PlottingError("未知 composition basis。")
        if legend_layout not in LEGEND_LAYOUTS:
            raise PlottingError("未知 K2O-SiO2 图例布局。")
        validate_export_parameters(width_mm, height_mm, dpi)
        model = load_classification_model(model_path)
        if model.id != MODEL_ID:
            raise PlottingError("K2O-SiO2 模型 ID 不匹配。")

        frame, source = read_major_table(input_path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "k2o_sio2_series_plot",
                "source": source,
                "model": model_summary(model_path, model),
                "issues": [
                    issue("E111", "review", "Excel 文件包含多个工作表，请明确指定一个工作表。")
                ],
            }
        inspection = inspect_major_frame(
            frame,
            source,
            requested_sample_column,
            requested_group_column,
        )
        gate_issues: list[dict[str, Any]] = []
        if not confirm_volcanic:
            gate_issues.append(
                issue("E811", "review", "请确认样品属于该火山岩岩浆系列图的适用范围。")
            )
        if composition_basis != "anhydrous-normalized":
            gate_issues.append(
                issue("E812", "review", "K2O-SiO2 图要求明确的无水100%组成基准。")
            )
        if inspection["status"] != "ready" or gate_issues:
            return {
                "status": "blocked",
                "operation": "k2o_sio2_series_plot",
                "model": model_summary(model_path, model),
                "input_inspection": inspection,
                "issues": gate_issues,
            }

        available = {
            item["analyte"] for item in inspection["analytes"]["recognized"]
        }
        missing = sorted({"SiO2", "K2O"} - available)
        if missing:
            raise PlottingError(
                "K2O-SiO2 图缺少必要主量氧化物：" + ", ".join(missing) + "。"
            )
        units = {
            item["analyte"]: item["unit"]
            for item in inspection["analytes"]["recognized"]
        }
        if any(units[analyte] != "wt%" for analyte in ("SiO2", "K2O")):
            raise PlottingError("SiO2 和 K2O 必须全部使用 wt%。")

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
        classified = classify_frame(canonical, sample_column, group_column, model)
        if not bool(classified[["SiO2", "K2O"]].notna().all(axis=1).any()):
            raise PlottingError("没有可用于 K2O-SiO2 图的完整非负坐标。")

        resolved_stem = stem or "k2o_sio2_series"
        figure_paths, source_path, report_path = output_targets(
            output_dir, resolved_stem
        )
        ensure_outputs_available(
            [*figure_paths, source_path, report_path], overwrite
        )
        figure, plot_info = build_figure(
            classified,
            sample_column,
            group_column,
            groups,
            model,
            title,
            width_mm,
            height_mm,
            legend_layout,
            style_preset=style_preset,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        save_figure_files(figure, figure_paths, dpi=dpi)
        classified.to_csv(
            source_path,
            index=False,
            encoding="utf-8",
            float_format="%.10g",
        )
        plt.close(figure)
        figure = None

        run_issues = list(inspection["issues"])
        messages = {
            "review_boundary": (
                "W811",
                "部分样品落在文献边界上，未强制指定岩浆系列。",
            ),
            "outside": (
                "W812",
                "部分样品超出48–63 wt% SiO2的完整四分区范围，已保留绘点但不分类。",
            ),
            "invalid": (
                "W813",
                "部分样品缺少可用的 SiO2-K2O 坐标，未参与分类。",
            ),
            "review_overlap": (
                "W814",
                "部分样品同时落入多个字段，需要人工复核。",
            ),
        }
        for status, (code, message) in messages.items():
            count = plot_info["classification_status_counts"].get(status, 0)
            if count:
                run_issues.append(issue(code, "warning", message, sample_count=count))
        if plot_info["outside_axes_count"]:
            run_issues.append(
                issue(
                    "W815",
                    "部分有效坐标超出固定显示范围，未显示在图框内。",
                    sample_count=plot_info["outside_axes_count"],
                )
            )
        if plot_info["legend_fallback"]:
            run_issues.append(
                issue("W816", "warning", "图内图例可能遮挡内容，已移至图框右侧。")
            )
        if plot_info["palette_repeated"] or plot_info["marker_repeated"]:
            run_issues.append(
                issue("W817", "warning", "分组数量超过基础颜色或符号数量，建议筛选分组。")
            )

        report = {
            "status": "ready",
            "operation": "k2o_sio2_series_plot",
            "source": source,
            "model": model_summary(model_path, model),
            "figure_contract": {
                "core_conclusion": (
                    "Place confirmed volcanic whole-rock analyses relative to the "
                    "non-extrapolated Peccerillo-Taylor K2O-SiO2 series boundaries."
                ),
                "archetype": "single-panel quantitative classification figure",
                "backend": "Python/matplotlib",
                "role": "magma-series comparison",
                "evidence": "anhydrous-normalized SiO2 and K2O in wt%",
                "target_output": "publication figure",
                "review_risks": [
                    "non-volcanic samples",
                    "composition basis not verified",
                    "alkali mobility and alteration",
                    "boundary-point ambiguity",
                    "incomplete four-field domain outside SiO2 48-63 wt%",
                ],
            },
            "configuration": {
                "sample_column": sample_column,
                "group_column": group_column,
                "groups": groups,
                "confirm_volcanic": confirm_volcanic,
                "composition_basis": composition_basis,
                "x": "SiO2",
                "y": "K2O",
                "unit": "wt%",
                "fixed_model_limits": True,
                "boundary_extrapolated": False,
                "legend_layout": legend_layout,
                "legend_position": plot_info["legend_position"],
                "width_mm": width_mm,
                "height_mm": height_mm,
                "png_dpi": dpi,
                "tiff_dpi": dpi,
                "style_preset": style_preset,
            },
            "plot": plot_info,
            "outputs": [shareable_file_record(path) for path in figure_paths],
            "source_data": shareable_file_record(source_path),
            "submission_qa": {
                "final_size_mm": [width_mm, height_mm],
                "svg_text_editable": True,
                "pdf_font_type": 42,
                "raster_dpi": dpi,
                "tiff_compression": "LZW",
                "white_background": True,
                "classification_boundaries_versioned": True,
                "source_data_exported": True,
            },
            "report_file": report_path.name,
            "issues": run_issues,
            "interpretation_guidance": [
                "Report the anhydrous normalization analytes and the two literature sources.",
                "Treat boundary and outside-domain analyses as unclassified pending review.",
                "Assess alteration and K mobility before interpreting the plotted series.",
                "Do not use this diagram alone to infer petrogenesis or tectonic setting.",
            ],
            "scientific_caveat": (
                "This diagram is a reviewed descriptive magma-series aid within its "
                "declared volcanic and composition-basis domain, not a stand-alone "
                "genetic or tectonic classifier."
            ),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    except (
        ClassificationModelError,
        InspectionError,
        PlottingError,
        OSError,
        ValueError,
    ) as exc:
        return _error(input_path, str(exc))
    finally:
        if figure is not None:
            plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成经复核、未外推的 K2O-SiO2 岩浆系列图。"
    )
    parser.add_argument("input", type=Path, help="CSV、TXT 或 Excel 输入表格")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stem", help="不含扩展名的输出文件名")
    parser.add_argument("--sheet", help="Excel 工作表名称或编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选分组列")
    parser.add_argument("--groups", help="逗号分隔的待绘制分组")
    parser.add_argument("--confirm-volcanic", action="store_true")
    parser.add_argument(
        "--composition-basis",
        choices=("anhydrous-normalized",),
        help="明确声明输入为无水100%基准",
    )
    parser.add_argument("--title", help="可选图题")
    parser.add_argument("--width-mm", type=float, default=150.0)
    parser.add_argument("--height-mm", type=float, default=120.0)
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument(
        "--legend-layout",
        choices=LEGEND_LAYOUTS,
        default="inside-auto",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    report = plot_k2o_sio2_path(
        args.input,
        args.output_dir,
        stem=args.stem,
        requested_sheet=args.sheet,
        requested_sample_column=args.sample_column,
        requested_group_column=args.group_column,
        requested_groups=args.groups,
        confirm_volcanic=args.confirm_volcanic,
        composition_basis=args.composition_basis or "unknown",
        title=args.title,
        width_mm=args.width_mm,
        height_mm=args.height_mm,
        dpi=args.dpi,
        legend_layout=args.legend_layout,
        overwrite=args.overwrite,
    )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"K2O-SiO2 绘图完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
