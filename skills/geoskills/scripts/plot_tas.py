#!/usr/bin/env python3
"""Create and classify publication-oriented volcanic TAS diagrams."""

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
from matplotlib.path import Path as MatplotlibPath

from geoskills_core.errors import PlottingError
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
    ensure_outputs_available,
    filter_requested_groups,
    group_style_map,
    output_targets,
    save_figure_bundle,
    shareable_file_record,
    validate_export_parameters,
)
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = (
    SKILL_DIR / "assets" / "classification" / "tas-lemaitre-2002.json"
)
COMPOSITION_BASES = ("unknown", "anhydrous-normalized", "as-reported")
LEGEND_LAYOUTS = ("inside-auto", "outside")
POTENTIALLY_INCOMPATIBLE_GROUP_TERMS = (
    "syenite",
    "granite",
    "gabbro",
    "diorite",
    "carbonatite",
    "plutonic",
)


def load_tas_model(path: Path) -> dict[str, Any]:
    """Load and minimally validate the versioned TAS polygon model."""
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlottingError(f"无法读取 TAS 边界资产：{exc}") from exc
    if model.get("diagram_type") != "total_alkali_silica":
        raise PlottingError("TAS 边界资产类型不正确。")
    fields = model.get("fields")
    if not isinstance(fields, list) or len(fields) != 15:
        raise PlottingError("TAS 边界资产必须包含 15 个火山岩字段。")
    ids = [field.get("id") for field in fields]
    if len(set(ids)) != len(ids):
        raise PlottingError("TAS 边界资产包含重复字段 ID。")
    for field in fields:
        polygon = field.get("polygon")
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise PlottingError(
                f"TAS 字段 {field.get('id')} 缺少有效多边形。"
            )
    return model


def tas_model_summary(path: Path, model: dict[str, Any]) -> dict[str, Any]:
    """Return shareable provenance for the TAS boundary asset."""
    return {
        "id": model["id"],
        "display_name": model["display_name"],
        "classification_doi": model["source"]["classification_doi"],
        "boundary_doi": model["source"]["boundary_doi"],
        "asset": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "crosscheck": model.get("crosscheck"),
        "boundary_policy": model["boundary_policy"],
    }


def point_segment_distance(
    point: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> float:
    """Return Euclidean distance from a point to one line segment."""
    vector = end - start
    length_squared = float(np.dot(vector, vector))
    if length_squared == 0:
        return float(np.linalg.norm(point - start))
    fraction = float(np.dot(point - start, vector) / length_squared)
    fraction = min(1.0, max(0.0, fraction))
    projection = start + fraction * vector
    return float(np.linalg.norm(point - projection))


def point_on_boundary(
    x: float,
    y: float,
    polygon: list[list[float]],
    tolerance: float,
) -> bool:
    """Return whether a point lies on any polygon segment."""
    point = np.asarray([x, y], dtype=float)
    vertices = np.asarray(polygon, dtype=float)
    for index in range(len(vertices)):
        start = vertices[index]
        end = vertices[(index + 1) % len(vertices)]
        if point_segment_distance(point, start, end) <= tolerance:
            return True
    return False


def classify_tas_point(
    x: float,
    y: float,
    model: dict[str, Any],
) -> dict[str, str | None]:
    """Classify one point, preserving boundary and outside states."""
    x_limits = model["axes"]["x"]["limits"]
    y_limits = model["axes"]["y"]["limits"]
    if not np.isfinite(x) or not np.isfinite(y):
        return {
            "status": "missing",
            "field": None,
            "name": None,
        }
    if (
        x < x_limits[0]
        or x > x_limits[1]
        or y < y_limits[0]
        or y > y_limits[1]
    ):
        return {
            "status": "outside_model",
            "field": None,
            "name": None,
        }
    tolerance = float(
        model["boundary_policy"]["tolerance_wt_percent"]
    )
    boundary_fields = [
        field["id"]
        for field in model["fields"]
        if point_on_boundary(x, y, field["polygon"], tolerance)
    ]
    if boundary_fields:
        return {
            "status": "boundary_review",
            "field": "/".join(boundary_fields),
            "name": None,
        }

    matches: list[dict[str, Any]] = []
    for field in model["fields"]:
        vertices = np.asarray(field["polygon"], dtype=float)
        closed = np.vstack([vertices, vertices[0]])
        if MatplotlibPath(closed).contains_point((x, y)):
            matches.append(field)
    if len(matches) == 1:
        return {
            "status": "classified",
            "field": matches[0]["id"],
            "name": matches[0]["name"],
        }
    if len(matches) > 1:
        return {
            "status": "ambiguous_review",
            "field": "/".join(field["id"] for field in matches),
            "name": None,
        }
    return {
        "status": "outside_fields",
        "field": None,
        "name": None,
    }


def classify_tas_frame(
    frame: pd.DataFrame,
    sample_column: str,
    group_column: str | None,
    model: dict[str, Any],
) -> pd.DataFrame:
    """Return TAS coordinates and deterministic classification states."""
    output = frame.loc[:, [sample_column]].copy()
    if group_column is not None:
        output[group_column] = frame[group_column]
    output["SiO2"] = pd.to_numeric(frame["SiO2"], errors="coerce")
    output["Na2O"] = pd.to_numeric(frame["Na2O"], errors="coerce")
    output["K2O"] = pd.to_numeric(frame["K2O"], errors="coerce")
    output["TotalAlkali"] = output["Na2O"] + output["K2O"]
    classifications = [
        classify_tas_point(float(x), float(y), model)
        for x, y in zip(output["SiO2"], output["TotalAlkali"])
    ]
    output["TAS_status"] = [item["status"] for item in classifications]
    output["TAS_field"] = [item["field"] for item in classifications]
    output["TAS_name"] = [item["name"] for item in classifications]
    return output


def legend_overlaps_content(
    ax: Any,
    legend: Any,
    points: np.ndarray,
    field_texts: list[Any],
) -> bool:
    """Return whether a legend overlaps sample points or field labels."""
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


def add_tas_legend(
    figure: Any,
    ax: Any,
    handles: list[Any],
    labels: list[str],
    points: np.ndarray,
    field_texts: list[Any],
    requested_layout: str,
) -> tuple[Any, str, bool]:
    """Place a collision-checked TAS legend or safely move it outside."""
    if requested_layout == "inside-auto":
        candidates = [
            "lower right",
            "upper right",
            "lower left",
            "upper left",
        ]
        for location in candidates:
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
            if not legend_overlaps_content(
                ax, legend, points, field_texts
            ):
                return legend, f"inside_{location.replace(' ', '_')}", False
            legend.remove()
    figure.subplots_adjust(right=0.75)
    legend = ax.legend(
        handles,
        labels,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        fontsize=5.8,
        handletextpad=0.4,
        labelspacing=0.38,
        frameon=False,
    )
    return legend, "outside_right_fallback", requested_layout == "inside-auto"


@publication_styled(
    overrides={
        "font.sans-serif": [
            "DejaVu Sans",
            "Arial",
            "Liberation Sans",
        ]
    },
    preset_parameter="style_preset",
)
def build_tas_figure(
    classified: pd.DataFrame,
    sample_column: str,
    group_column: str | None,
    groups: list[str],
    model: dict[str, Any],
    composition_basis: str,
    title: str | None,
    width_mm: float,
    height_mm: float,
    legend_layout: str,
    style_preset: str = PUBLICATION_DOUBLE_COLUMN,
) -> tuple[Any, dict[str, Any]]:
    """Build one fixed-geometry volcanic TAS figure."""
    figure, ax = plt.subplots(
        figsize=(width_mm / 25.4, height_mm / 25.4)
    )
    figure.subplots_adjust(
        left=0.105,
        right=0.965,
        bottom=0.15,
        top=0.93 if title else 0.965,
    )
    field_texts: list[Any] = []
    fills = ("#FAFAFA", "#F2F2F2")
    for index, field in enumerate(model["fields"]):
        patch = Polygon(
            field["polygon"],
            closed=True,
            facecolor=fills[index % len(fills)],
            edgecolor="#686868",
            linewidth=0.55,
            zorder=1,
        )
        ax.add_patch(patch)
        field_texts.append(
            ax.text(
                field["label_position"][0],
                field["label_position"][1],
                field["plot_label"],
                ha="center",
                va="center",
                fontsize=5.0,
                color="#4D4D4D",
                linespacing=0.9,
                zorder=2,
            )
        )

    styles = group_style_map(groups)
    if group_column is None:
        finite = (
            classified["SiO2"].notna()
            & classified["TotalAlkali"].notna()
        )
        ax.scatter(
            classified.loc[finite, "SiO2"],
            classified.loc[finite, "TotalAlkali"],
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
            subset = classified.loc[
                classified[group_column].astype(str) == group
            ]
            finite = (
                subset["SiO2"].notna()
                & subset["TotalAlkali"].notna()
            )
            style = styles[group]
            ax.scatter(
                subset.loc[finite, "SiO2"],
                subset.loc[finite, "TotalAlkali"],
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
        finite_points = classified.loc[
            classified["SiO2"].notna()
            & classified["TotalAlkali"].notna(),
            ["SiO2", "TotalAlkali"],
        ].to_numpy(dtype=float)
        _, legend_position, legend_fallback = add_tas_legend(
            figure,
            ax,
            handles,
            labels,
            finite_points,
            field_texts,
            legend_layout,
        )

    ax.set_xlim(model["axes"]["x"]["limits"])
    ax.set_ylim(model["axes"]["y"]["limits"])
    ax.set_xlabel("SiO₂ (wt%)")
    ax.set_ylabel("Na₂O + K₂O (wt%)")
    ax.set_xticks(np.arange(35, 91, 5))
    ax.set_yticks(np.arange(0, 21, 2))
    ax.tick_params(
        axis="both", which="major", direction="out", length=3
    )
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("#1A1A1A")
        spine.set_linewidth(0.75)
    if title:
        ax.set_title(title, fontsize=8, pad=6)
    basis_label = (
        "declared anhydrous 100% basis"
        if composition_basis == "anhydrous-normalized"
        else "as-reported values; classification is provisional"
    )
    figure.text(
        0.105,
        0.045,
        "IUGS volcanic TAS (Le Maitre et al., 2002); "
        + basis_label
        + "; boundary points require review.",
        fontsize=5.6,
        color="#4D4D4D",
        ha="left",
    )
    counts = Counter(classified["TAS_status"].tolist())
    return figure, {
        "sample_count": int(len(classified)),
        "group_count": len(groups) if group_column is not None else 0,
        "classification_status_counts": dict(counts),
        "field_counts": {
            str(key): int(value)
            for key, value in classified["TAS_field"]
            .dropna()
            .value_counts()
            .items()
        },
        "legend_layout_requested": legend_layout,
        "legend_position": legend_position,
        "legend_fallback": legend_fallback,
        "axes_frame": "full",
        "x_limits": model["axes"]["x"]["limits"],
        "y_limits": model["axes"]["y"]["limits"],
        "palette_repeated": len(groups) > len(GROUP_COLORS),
        "marker_repeated": len(groups) > len(MARKERS),
        "colour_is_not_the_only_identifier": True,
        "group_encoding": (
            "colour plus marker shape"
            if group_column is not None
            else "not applicable"
        ),
    }


def tas_error(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "tas_plot",
        "source": {"format": path.suffix.lower()},
        "issues": [issue("E700", "error", message)],
    }


def plot_tas_path(
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
    """Validate, classify, and export a volcanic TAS figure bundle."""
    figure = None
    try:
        if composition_basis not in COMPOSITION_BASES:
            raise PlottingError(
                "未知 composition basis；请使用 anhydrous-normalized 或 as-reported。"
            )
        if legend_layout not in LEGEND_LAYOUTS:
            raise PlottingError("未知 TAS 图例布局。")
        validate_export_parameters(width_mm, height_mm, dpi)
        model = load_tas_model(model_path)
        frame, source = read_major_table(input_path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "tas_plot",
                "source": source,
                "model": tas_model_summary(model_path, model),
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
        gate_issues: list[dict[str, Any]] = []
        if not confirm_volcanic:
            gate_issues.append(
                issue(
                    "E711",
                    "review",
                    "TAS 仅用于本版本声明的火山岩分类；请确认样品为火山岩。",
                )
            )
        if composition_basis == "unknown":
            gate_issues.append(
                issue(
                    "E712",
                    "review",
                    "请声明数据是 anhydrous-normalized 还是 as-reported。",
                )
            )
        if inspection["status"] != "ready" or gate_issues:
            return {
                "status": "blocked",
                "operation": "tas_plot",
                "model": tas_model_summary(model_path, model),
                "input_inspection": inspection,
                "issues": [
                    *gate_issues,
                    *(
                        [
                            issue(
                                "E713",
                                "review",
                                "输入数据未通过安全检查，因此没有生成 TAS 图。",
                            )
                        ]
                        if inspection["status"] != "ready"
                        else []
                    ),
                ],
            }

        available = {
            item["analyte"]
            for item in inspection["analytes"]["recognized"]
        }
        required = {"SiO2", "Na2O", "K2O"}
        missing = sorted(required - available)
        if missing:
            raise PlottingError(
                "TAS 缺少必要主量氧化物：" + ", ".join(missing) + "。"
            )
        units = {
            item["analyte"]: item["unit"]
            for item in inspection["analytes"]["recognized"]
        }
        if any(units[analyte] != "wt%" for analyte in required):
            raise PlottingError("TAS 的 SiO2、Na2O 和 K2O 必须全部为 wt%。")

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
        classified = classify_tas_frame(
            canonical,
            sample_column,
            group_column,
            model,
        )
        resolved_stem = stem or "tas_volcanic"
        figure_paths, source_path, report_path = output_targets(
            output_dir, resolved_stem
        )
        ensure_outputs_available(
            [*figure_paths, source_path, report_path], overwrite
        )
        figure, plot_info = build_tas_figure(
            classified,
            sample_column,
            group_column,
            groups,
            model,
            composition_basis,
            title,
            width_mm,
            height_mm,
            legend_layout,
            style_preset=style_preset,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        save_figure_bundle(figure, figure_paths, dpi)
        classified.to_csv(
            source_path,
            index=False,
            encoding="utf-8",
            float_format="%.10g",
        )
        plt.close(figure)
        figure = None

        run_issues = list(inspection["issues"])
        if composition_basis == "as-reported":
            run_issues.append(
                issue(
                    "W711",
                    "warning",
                    "使用 as-reported 数值绘制；分类为临时结果，投稿前应复核无挥发分 100% 归一化基础。",
                )
            )
        for status, code, message in [
            (
                "boundary_review",
                "W712",
                "部分样品落在 TAS 字段边界上，未强制指定岩类。",
            ),
            (
                "outside_model",
                "W713",
                "部分样品超出 TAS 模型固定坐标范围。",
            ),
            (
                "outside_fields",
                "W714",
                "部分样品位于坐标范围内但不属于已定义字段。",
            ),
        ]:
            count = plot_info["classification_status_counts"].get(status, 0)
            if count:
                run_issues.append(
                    issue(code, "warning", message, sample_count=count)
                )
        if group_column is not None:
            suspicious = [
                group
                for group in groups
                if any(
                    term in group.casefold()
                    for term in POTENTIALLY_INCOMPATIBLE_GROUP_TERMS
                )
            ]
            if suspicious:
                run_issues.append(
                    issue(
                        "W715",
                        "warning",
                        "部分分组名称提示其可能不属于火山岩 TAS 适用范围，请人工复核。",
                        groups=suspicious,
                    )
                )
        if plot_info["legend_fallback"]:
            run_issues.append(
                issue(
                    "W716",
                    "warning",
                    "图内图例会遮挡样品点或分类标签，已改为右侧布局。",
                )
            )
        if plot_info["palette_repeated"] or plot_info["marker_repeated"]:
            run_issues.append(
                issue(
                    "W717",
                    "warning",
                    "分组数量超过基础颜色或符号数量；建议筛选分组。",
                    group_count=plot_info["group_count"],
                )
            )

        report = {
            "status": "ready",
            "operation": "tas_plot",
            "source": source,
            "model": tas_model_summary(model_path, model),
            "figure_contract": {
                "core_conclusion": (
                    "Place confirmed volcanic whole-rock analyses in declared "
                    "IUGS total-alkali–silica fields without hiding boundary "
                    "or applicability uncertainty."
                ),
                "archetype": "single-panel quantitative classification figure",
                "backend": "Python/matplotlib",
                "role": "classification evidence",
                "evidence": "SiO2 and Na2O + K2O in wt%",
                "target_output": "publication figure",
                "review_risks": [
                    "non-volcanic samples",
                    "volatile-free normalization not confirmed",
                    "alteration and alkali mobility",
                    "boundary-point ambiguity",
                    "unresolved normative subtypes",
                ],
            },
            "configuration": {
                "sample_column": sample_column,
                "group_column": group_column,
                "groups": groups,
                "confirm_volcanic": confirm_volcanic,
                "composition_basis": composition_basis,
                "x": "SiO2",
                "y": "Na2O + K2O",
                "unit": "wt%",
                "fixed_model_limits": True,
                "legend_layout": legend_layout,
                "legend_position": plot_info["legend_position"],
                "width_mm": width_mm,
                "height_mm": height_mm,
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
                "final_size_mm": [width_mm, height_mm],
                "svg_text_editable": True,
                "pdf_font_type": 42,
                "raster_dpi": dpi,
                "tiff_compression": "LZW",
                "white_background": True,
                "classification_boundaries_versioned": True,
                "colourblind_support": "group colour plus marker shape",
                "source_data_exported": True,
            },
            "report_file": report_path.name,
            "issues": run_issues,
            "interpretation_guidance": [
                "Report the declared composition basis and the TAS reference in the caption or methods.",
                "Treat boundary and outside-model analyses as requiring manual review.",
                "Do not use TAS alone to establish petrogenesis, magma series, or tectonic setting.",
                "Review alteration and alkali mobility before accepting a volcanic rock name.",
                "Resolve Trachyte/Trachydacite and Tephrite/Basanite only with the additional normative criteria.",
            ],
            "scientific_caveat": (
                "TAS is a chemical nomenclature tool for its declared volcanic "
                "domain; it is not a stand-alone genetic or tectonic classifier."
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
        return tas_error(input_path, str(exc))
    finally:
        if figure is not None:
            plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成带 IUGS 火山岩分类字段的投稿级 TAS 图。"
    )
    parser.add_argument("input", type=Path, help="CSV、TXT 或 Excel 输入表格")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stem", help="不含扩展名的输出文件名")
    parser.add_argument("--sheet", help="Excel 工作表名称或编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选分组列")
    parser.add_argument("--groups", help="逗号分隔的待绘制分组")
    parser.add_argument(
        "--confirm-volcanic",
        action="store_true",
        help="明确确认样品属于火山岩 TAS 适用范围",
    )
    parser.add_argument(
        "--composition-basis",
        choices=COMPOSITION_BASES[1:],
        help="声明输入为 anhydrous-normalized 或 as-reported",
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
    report = plot_tas_path(
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
    print(f"TAS 绘图完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
