#!/usr/bin/env python3
"""Create a coordinate-only grouped bivariate figure from mapped data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from geoskills_core.errors import PlottingError
from geoskills_core.variables import (
    AxisVariableReference,
    VariableEvaluationError,
    evaluate_xy_variables,
)
from geoskills_core.xy import build_xy_figure
from plot_geochem_common import (
    ensure_outputs_available,
    output_targets,
    save_figure_bundle,
    shareable_file_record,
    validate_export_parameters,
)


def _reference(raw: Mapping[str, Any]) -> AxisVariableReference:
    return AxisVariableReference(
        kind=str(raw["kind"]),
        id=str(raw["id"]),
        label=(None if raw.get("label") is None else str(raw["label"])),
        scale=str(raw.get("scale", "linear")),
    )


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        raise PlottingError("输入表没有可绘制记录。")
    return frame


def inspect_xy_path(
    input_path: Path,
    *,
    x_reference: Mapping[str, Any],
    y_reference: Mapping[str, Any],
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
    derived_summary: Mapping[str, Any],
    requested_groups: list[str] | str = "all",
    group_column: str | None = "Group",
) -> dict[str, Any]:
    """Return a count-only XY preflight summary."""

    try:
        frame = _read(input_path)
        if requested_groups != "all":
            if group_column is None or group_column not in frame.columns:
                raise PlottingError("输入没有已映射分组列。")
            wanted = {str(item) for item in requested_groups}
            groups = frame[group_column].astype("string").str.strip()
            frame = frame.loc[groups.isin(wanted)].copy()
        result = evaluate_xy_variables(
            frame,
            x_reference=_reference(x_reference),
            y_reference=_reference(y_reference),
            analyte_columns=analyte_columns,
            analyte_units=analyte_units,
            derived_summary=derived_summary,
        )
        status = "ready" if result.counts["valid_coordinate_count"] >= 2 else "blocked"
        issues = []
        if status != "ready":
            issues.append(
                {
                    "code": "E671",
                    "severity": "review",
                    "message": "二维图至少需要两对有效坐标。",
                }
            )
        return {
            "status": status,
            "operation": "generic_bivariate_plot",
            "recognized_analytes": sorted(str(key) for key in analyte_columns),
            "coordinates": {
                "joint_valid_count": result.counts["valid_coordinate_count"],
                "x": result.x.to_summary()["counts"],
                "y": result.y.to_summary()["counts"],
            },
            "issues": issues,
        }
    except (OSError, ValueError, VariableEvaluationError, PlottingError) as exc:
        return {
            "status": "blocked",
            "operation": "generic_bivariate_plot",
            "recognized_analytes": [],
            "coordinates": {"joint_valid_count": 0},
            "issues": [
                {"code": "E670", "severity": "error", "message": str(exc)}
            ],
        }


def plot_xy_path(
    input_path: Path,
    output_dir: Path,
    *,
    stem: str = "xy",
    requested_sample_column: str = "Sample",
    requested_group_column: str | None = "Group",
    x_reference: Mapping[str, Any],
    y_reference: Mapping[str, Any],
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
    derived_summary: Mapping[str, Any],
    requested_groups: list[str] | str = "all",
    title: str | None = None,
    width_mm: float = 183.0,
    height_mm: float = 120.0,
    dpi: int = 600,
    overwrite: bool = False,
    style_preset: str = "publication-double-column",
    **_: Any,
) -> dict[str, Any]:
    """Validate resolved columns and export the fixed XY bundle."""

    figure = None
    try:
        validate_export_parameters(width_mm, height_mm, dpi)
        frame = _read(input_path)
        if requested_sample_column not in frame.columns:
            raise PlottingError("已映射样品编号列不存在。")
        if requested_groups != "all":
            if requested_group_column is None or requested_group_column not in frame.columns:
                raise PlottingError("输入没有已映射分组列。")
            wanted = {str(item) for item in requested_groups}
            group_text = frame[requested_group_column].astype("string").str.strip()
            frame = frame.loc[group_text.isin(wanted)].copy()
        evaluated = evaluate_xy_variables(
            frame,
            x_reference=_reference(x_reference),
            y_reference=_reference(y_reference),
            analyte_columns=analyte_columns,
            analyte_units=analyte_units,
            derived_summary=derived_summary,
        )
        if evaluated.counts["valid_coordinate_count"] < 2:
            raise PlottingError("二维图至少需要两对有效坐标。")
        figure_paths, source_path, report_path = output_targets(output_dir, stem)
        ensure_outputs_available([*figure_paths, source_path, report_path], overwrite)
        figure, plot_info = build_xy_figure(
            frame,
            x_values=evaluated.x.values,
            y_values=evaluated.y.values,
            valid_mask=evaluated.joint_valid_mask,
            x_label=evaluated.x.label,
            y_label=evaluated.y.label,
            x_scale=evaluated.x.scale,
            y_scale=evaluated.y.scale,
            group_column=(
                requested_group_column
                if requested_group_column in frame.columns
                else None
            ),
            width_mm=width_mm,
            height_mm=height_mm,
            title=title,
            style_preset=style_preset,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        save_figure_bundle(figure, figure_paths, dpi)
        export = pd.DataFrame(
            {
                requested_sample_column: frame.loc[
                    evaluated.joint_valid_mask, requested_sample_column
                ],
                "x": evaluated.x.values.loc[evaluated.joint_valid_mask],
                "y": evaluated.y.values.loc[evaluated.joint_valid_mask],
            }
        )
        if requested_group_column and requested_group_column in frame.columns:
            export.insert(
                1,
                requested_group_column,
                frame.loc[evaluated.joint_valid_mask, requested_group_column],
            )
        export.to_csv(source_path, index=False, encoding="utf-8")
        plt.close(figure)
        figure = None
        report = {
            "status": "ready",
            "operation": "generic_bivariate_plot",
            "configuration": {
                "x": dict(x_reference),
                "y": dict(y_reference),
                "sample_labels_rendered": False,
                "width_mm": width_mm,
                "height_mm": height_mm,
                "png_dpi": dpi,
                "tiff_dpi": dpi,
            },
            "plot": plot_info,
            "outputs": [shareable_file_record(path) for path in figure_paths],
            "source_data": shareable_file_record(source_path),
            "report_file": report_path.name,
            "issues": [],
            "interpretation_guidance": [
                "Describe covariance, clusters, scatter and outliers before proposing a process.",
                "A coordinate-only plot does not apply classification fields or tectonic interpretation.",
            ],
            "scientific_caveat": (
                "Bivariate covariance alone does not identify a unique process or genetic relationship."
            ),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return report
    except (OSError, ValueError, VariableEvaluationError, PlottingError) as exc:
        return {
            "status": "error",
            "operation": "generic_bivariate_plot",
            "issues": [
                {"code": "E672", "severity": "error", "message": str(exc)}
            ],
        }
    finally:
        if figure is not None:
            plt.close(figure)


__all__ = ["inspect_xy_path", "plot_xy_path"]
