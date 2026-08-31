"""Thin, fixed adapters between unified recipes and reviewed plotters."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .analytes import (
    DEFAULT_ANALYTE_REGISTRY,
    infer_unit,
    match_analyte,
    normalize_unit,
)
from .errors import GeoSkillsError
from .basis import apply_data_basis
from .derived import apply_derived_variables
from .io import adapt_transposed_table, read_table, validate_input_file
from .quality import assess_data_quality
from .validation import ColumnMapping, validate_column_mappings


MAX_PLOT_POINTS = 100_000
MAX_PLOT_GROUPS = 64
MAX_PLOT_ARTISTS = 2_000
_SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class AdapterError(GeoSkillsError):
    """A recipe cannot be translated safely to a reviewed plotter."""

    default_code = "E400"


@dataclass(frozen=True)
class PreparedInput:
    """One temporary canonical table and its share-safe provenance."""

    path: Path
    basis_path: Path | None
    source: dict[str, Any]
    sample_column: str
    group_column: str | None
    mappings: tuple[ColumnMapping, ...]
    quality: dict[str, Any]
    derived: dict[str, Any]
    basis: dict[str, Any]


def _spreadsheet_formula_count(series: pd.Series) -> int:
    """Count text labels which spreadsheet software may evaluate as formulae."""

    def is_risky(value: object) -> bool:
        if pd.isna(value):
            return False
        text = str(value).lstrip(" \u00a0")
        return bool(text) and text.startswith(_SPREADSHEET_FORMULA_PREFIXES)

    return int(series.map(is_risky).sum())


def _plot_budget_issues(
    diagram: str,
    parameters: Mapping[str, Any],
    frame: pd.DataFrame | None,
    group_column: str | None,
) -> list[dict[str, str]]:
    """Fail closed before plotting would create excessive vector content."""

    if frame is None:
        return []
    row_count = int(frame.shape[0])
    if diagram in {"ree", "spider"}:
        series_count = len(parameters.get("elements", []))
        artist_count = row_count
    elif diagram == "harker":
        series_count = len(parameters.get("y", []))
        artist_count = 1
    else:
        series_count = 1
        artist_count = 1
    group_count = 1
    if group_column is not None and group_column in frame.columns:
        group_text = (
            frame[group_column]
            .astype("string")
            .str.strip()
            .fillna("Unspecified")
            .replace("", "Unspecified")
        )
        group_count = int(group_text.nunique(dropna=False))
        if diagram not in {"ree", "spider"}:
            artist_count = group_count * max(series_count, 1)
    point_count = row_count * max(series_count, 1)
    issues: list[dict[str, str]] = []
    if point_count > MAX_PLOT_POINTS:
        issues.append(
            {
                "code": "E422",
                "severity": "error",
                "message": (
                    "图件预计数据点数量超过安全上限；GeoSkills 不会静默抽样。"
                ),
                "field": "tasks.parameters",
                "suggested_action": (
                    "把完整数据按科学问题拆分为多个任务，或减少一次绘制的变量数量。"
                ),
            }
        )
    if group_count > MAX_PLOT_GROUPS:
        issues.append(
            {
                "code": "E423",
                "severity": "error",
                "message": (
                    "图件分组数量超过安全且可读的上限；GeoSkills 不会合并分组。"
                ),
                "field": "tasks.parameters.groups",
                "suggested_action": "按科研问题拆分分组，并为每个子集建立独立任务。",
            }
        )
    if artist_count > MAX_PLOT_ARTISTS:
        issues.append(
            {
                "code": "E424",
                "severity": "error",
                "message": (
                    "图件预计独立绘图对象数量超过安全上限；GeoSkills 不会静默简化。"
                ),
                "field": "tasks.parameters",
                "suggested_action": (
                    "把样品或变量拆分为多幅完整图件，并分别审核其配方。"
                ),
            }
        )
    return issues


def _unit_for(
    canonical: str,
    source_spec: object,
    units: Mapping[str, object],
) -> str:
    if isinstance(source_spec, Mapping) and source_spec.get("unit") is not None:
        return normalize_unit(source_spec["unit"])
    if canonical in units:
        return normalize_unit(units[canonical])
    definition = DEFAULT_ANALYTE_REGISTRY.get(canonical)
    if definition is None:
        return "unknown"
    family_key = (
        "major_oxides"
        if definition.kind == "major_oxide"
        else "trace_elements"
    )
    return normalize_unit(units.get(family_key, "unknown"))


def _source_column(source_spec: object) -> str:
    if isinstance(source_spec, Mapping):
        value = source_spec.get("source")
    else:
        value = source_spec
    if value is None or not str(value).strip():
        raise AdapterError(
            "列映射必须提供非空原始列名。",
            code="E401",
        )
    return str(value)


def prepare_mapped_input(
    recipe: Mapping[str, Any],
    *,
    recipe_path: Path,
    work_dir: Path,
) -> PreparedInput:
    """Create a temporary canonical CSV without changing the user's source."""

    recipe_directory = recipe_path.resolve().parent
    input_value = str(recipe["input"]["file"])
    input_path = (recipe_directory / input_value).resolve()
    try:
        input_path.relative_to(recipe_directory)
    except ValueError as exc:
        raise AdapterError(
            "输入文件必须位于配方目录或其子目录中。",
            code="E402",
        ) from exc

    layout = recipe["input"].get("layout", "auto")
    transposer = None if layout == "row-per-sample" else adapt_transposed_table
    validated_input = validate_input_file(input_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = work_dir / f"source_snapshot{validated_input.suffix.lower()}"
    shutil.copyfile(validated_input, snapshot_path)
    frame, source = read_table(
        snapshot_path,
        recipe["input"].get("sheet"),
        transposer=transposer,
    )
    source["filename"] = validated_input.name
    if frame is None:
        raise AdapterError(
            "Excel 文件包含多个工作表；必须在配方中明确 input.sheet。",
            code="E403",
            details={
                "sheet_count": len(source.get("sheet_names", [])),
                "available_sheet_indices": list(
                    range(len(source.get("sheet_names", [])))
                ),
            },
        )
    if (
        layout == "analyte-per-row"
        and source.get("layout") != "column_per_sample_transposed"
    ):
        raise AdapterError(
            "配方声明 analyte-per-row，但未识别出唯一可转置结构。",
            code="E404",
        )

    columns = recipe["columns"]
    sample_source = str(columns["sample_id"])
    group_value = columns.get("group")
    group_source = None if group_value is None else str(group_value)
    available = {str(column) for column in frame.columns}
    if sample_source not in available:
        raise AdapterError(
            "配方指定的样品编号列不存在。",
            code="E405",
            details={"column": sample_source},
        )
    if group_source is not None and group_source not in available:
        raise AdapterError(
            "配方指定的分组列不存在。",
            code="E406",
            details={"column": group_source},
        )
    if group_source == sample_source:
        raise AdapterError(
            "样品编号列和分组列不能是同一列。",
            code="E407",
        )

    mapping_config = columns.get("mapping", {})
    units = columns.get("units", {})
    mappings = tuple(
        ColumnMapping(
            source_column=_source_column(source_spec),
            canonical_analyte=str(canonical),
            unit=_unit_for(str(canonical), source_spec, units),
            origin="recipe",
        )
        for canonical, source_spec in mapping_config.items()
    )
    mapping_issues = validate_column_mappings(
        mappings,
        available_columns=frame.columns,
    )
    if mapping_issues:
        raise AdapterError(
            "列映射未通过安全检查。",
            code="E408",
            details={"issues": [item.to_dict() for item in mapping_issues]},
        )
    header_conflicts: list[dict[str, str]] = []
    for mapping in mappings:
        header_unit = infer_unit(mapping.source_column)
        declared_unit = normalize_unit(mapping.unit)
        matched = match_analyte(mapping.source_column)
        if header_unit != "unknown" and header_unit != declared_unit:
            header_conflicts.append(
                {
                    "source_column": mapping.source_column,
                    "canonical_analyte": mapping.canonical_analyte,
                    "header_unit": header_unit,
                    "declared_unit": declared_unit,
                    "conflict": "unit",
                }
            )
        if (
            matched is not None
            and matched.canonical != mapping.canonical_analyte
        ):
            header_conflicts.append(
                {
                    "source_column": mapping.source_column,
                    "canonical_analyte": mapping.canonical_analyte,
                    "header_analyte": matched.canonical,
                    "conflict": "analyte",
                }
            )
    if header_conflicts:
        raise AdapterError(
            "原始列名中的明确分析物或单位与配方声明不一致；GeoSkills 不会猜测、交换或自动换算。",
            code="E415",
            details={"conflicts": header_conflicts},
        )

    used_sources = [sample_source]
    if group_source is not None:
        used_sources.append(group_source)
    used_sources.extend(item.source_column for item in mappings)
    duplicates = sorted(
        {
            value
            for value in used_sources
            if used_sources.count(value) > 1
        }
    )
    if duplicates:
        raise AdapterError(
            "同一原始列不能同时承担多个角色。",
            code="E409",
            details={"columns": duplicates},
        )

    canonical = pd.DataFrame({"Sample": frame[sample_source]})
    if group_source is not None:
        canonical["Group"] = frame[group_source]
    for mapping in mappings:
        canonical[f"{mapping.canonical_analyte}_{mapping.unit}"] = frame[
            mapping.source_column
        ]
    mapped_column_count = int(canonical.shape[1])

    analyte_columns = {
        mapping.canonical_analyte: f"{mapping.canonical_analyte}_{mapping.unit}"
        for mapping in mappings
    }
    analyte_units = {
        mapping.canonical_analyte: mapping.unit for mapping in mappings
    }
    try:
        quality = assess_data_quality(
            canonical,
            sample_column="Sample",
            analyte_columns=analyte_columns,
            analyte_units=analyte_units,
            policy=recipe.get("quality", {}),
        )
        canonical, derived = apply_derived_variables(
            canonical,
            specifications=recipe.get("derived_variables", ()),
            analyte_columns=analyte_columns,
            analyte_units=analyte_units,
        )
        basis_frame, basis = apply_data_basis(
            canonical,
            specification=recipe.get("data_basis"),
            analyte_columns=analyte_columns,
            analyte_units=analyte_units,
        )
    except (KeyError, ValueError) as exc:
        raise AdapterError(
            "数据质控或派生变量处理无法按已验证配方安全完成。",
            code="E416",
        ) from exc

    formula_risk = {
        "sample_id_count": _spreadsheet_formula_count(canonical["Sample"]),
        "group_count": (
            _spreadsheet_formula_count(canonical["Group"])
            if "Group" in canonical.columns
            else 0
        ),
    }
    formula_risk["total_count"] = (
        formula_risk["sample_id_count"] + formula_risk["group_count"]
    )
    if formula_risk["total_count"]:
        quality["spreadsheet_formula_risk"] = formula_risk
        if recipe["output"]["report_profile"] == "local-reproducible":
            quality["issues"].append(
                {
                    "code": "E422",
                    "severity": "error",
                    "message": (
                        "样品或分组文本可能被电子表格软件解释为公式；"
                        "已阻止本地可复现 CSV 导出。"
                    ),
                    "field": "columns.sample_id/columns.group",
                    "suggested_action": (
                        "在数据副本中把相应标签改为不以 =、+、-、@、制表符"
                        "或回车开头的纯文本，再重新生成计划。"
                    ),
                }
            )
            quality["status"] = "error"

    mapped_path = work_dir / "mapped_input.csv"
    canonical.to_csv(mapped_path, index=False)
    basis_path: Path | None = None
    if basis.get("configured") is True:
        basis_path = work_dir / "basis_input.csv"
        basis_frame.to_csv(basis_path, index=False)
    safe_source = {
        key: value
        for key, value in source.items()
        if key
        in {
            "filename",
            "file_sha256",
            "size_bytes",
            "format",
            "sheet",
            "layout",
        }
    }
    safe_source["row_count"] = int(canonical.shape[0])
    safe_source["column_count"] = mapped_column_count
    return PreparedInput(
        path=mapped_path,
        basis_path=basis_path,
        source=safe_source,
        sample_column="Sample",
        group_column="Group" if group_source is not None else None,
        mappings=mappings,
        quality=quality,
        derived=derived,
        basis=basis,
    )


def _safe_issues(report: Mapping[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for item in report.get("issues", []):
        severity = str(item.get("severity", "review"))
        if severity not in {"info", "warning", "review", "error"}:
            severity = "review"
        results.append(
            {
                "code": str(item.get("code", "E499")),
                "severity": severity,
                "message": str(item.get("message", "需要人工复核。")),
            }
        )
    return results


def _basis_aware_path(
    task: Mapping[str, Any],
    prepared: PreparedInput,
) -> Path:
    """Select a transformed table only when the reviewed task requires it."""

    diagram = str(task["diagram"])
    basis = str(task.get("parameters", {}).get("composition_basis", ""))
    if diagram == "k2o-sio2":
        if prepared.basis_path is None:
            raise AdapterError(
                "K2O-SiO2 图缺少已审核的无水基准表。",
                code="E420",
            )
        return prepared.basis_path
    if (
        diagram == "tas"
        and basis == "anhydrous-normalized"
        and prepared.basis_path is not None
    ):
        return prepared.basis_path
    return prepared.path


def inspect_task(
    task: Mapping[str, Any],
    prepared: PreparedInput,
) -> dict[str, Any]:
    """Run the appropriate reviewed inspector without importing plotters."""

    diagram = str(task["diagram"])
    parameters = task.get("parameters", {})
    selected_groups = parameters.get("groups", "all")
    missing_groups: list[str] = []
    selected_frame: pd.DataFrame | None = None
    inspection_path = _basis_aware_path(task, prepared)
    if selected_groups != "all":
        if prepared.group_column is None:
            missing_groups = [str(item) for item in selected_groups]
        else:
            canonical_frame = pd.read_csv(inspection_path)
            group_text = (
                canonical_frame[prepared.group_column]
                .astype("string")
                .str.strip()
            )
            available_groups = {
                str(value)
                for value in group_text.dropna()
                if str(value).strip()
            }
            missing_groups = sorted(
                str(item)
                for item in selected_groups
                if str(item) not in available_groups
            )
            if not missing_groups:
                requested_groups = {str(item) for item in selected_groups}
                selected_frame = canonical_frame.loc[
                    group_text.isin(requested_groups)
                ].copy()
                if diagram in {"ree", "spider"}:
                    inspection_path = _task_input_path(task, prepared)
    elif diagram in {"ree", "spider", "harker", "tas", "k2o-sio2", "xy"}:
        selected_frame = pd.read_csv(inspection_path)

    if diagram == "ree":
        from inspect_data import inspect_path

        report = inspect_path(
            inspection_path,
            requested_sample_column=prepared.sample_column,
            requested_group_column=prepared.group_column,
        )
        recognized = [
            item["element"]
            for item in report.get("ree", {}).get("recognized", [])
        ]
    elif diagram == "spider":
        from inspect_spider_data import inspect_spider_path

        report = inspect_spider_path(
            inspection_path,
            requested_sample_column=prepared.sample_column,
            requested_group_column=prepared.group_column,
        )
        recognized = [
            item["element"]
            for item in report.get("trace_elements", {}).get("recognized", [])
        ]
    elif diagram in {"harker", "tas", "k2o-sio2"}:
        from inspect_major_data import inspect_major_path

        report = inspect_major_path(
            inspection_path,
            requested_sample_column=prepared.sample_column,
            requested_group_column=prepared.group_column,
        )
        recognized = [
            item["analyte"]
            for item in report.get("analytes", {}).get("recognized", [])
        ]
    elif diagram == "xy":
        from plot_xy import inspect_xy_path

        analyte_columns = {
            mapping.canonical_analyte: (
                f"{mapping.canonical_analyte}_{mapping.unit}"
            )
            for mapping in prepared.mappings
        }
        analyte_units = {
            mapping.canonical_analyte: mapping.unit
            for mapping in prepared.mappings
        }
        report = inspect_xy_path(
            inspection_path,
            x_reference=parameters["x"],
            y_reference=parameters["y"],
            analyte_columns=analyte_columns,
            analyte_units=analyte_units,
            derived_summary=prepared.derived,
            requested_groups=parameters.get("groups", "all"),
            group_column=prepared.group_column,
        )
        recognized = list(report.get("recognized_analytes", []))
    else:
        raise AdapterError(
            "图件类型不在固定注册表中。",
            code="E410",
            details={"diagram": diagram},
        )

    issues = _safe_issues(report)
    budget_issues = _plot_budget_issues(
        diagram,
        parameters,
        selected_frame,
        prepared.group_column,
    )
    issues.extend(budget_issues)
    resource_blocked = bool(budget_issues)
    layout_blocked = False
    if task.get("style", {}).get("base_preset") == "publication-single-column":
        if diagram == "spider" and len(parameters.get("elements", [])) > 14:
            layout_blocked = True
            issues.append(
                {
                    "code": "E423",
                    "severity": "review",
                    "message": "单栏蛛网图最多允许 14 个元素，以保证最终尺寸标签可读。",
                    "field": "tasks.parameters.elements",
                    "suggested_action": (
                        "减少元素数量，或改用 publication-double-column。"
                    ),
                }
            )
        if diagram == "harker" and len(parameters.get("y", [])) > 2:
            layout_blocked = True
            issues.append(
                {
                    "code": "E424",
                    "severity": "review",
                    "message": "单栏 Harker 图最多允许 2 个面板，以保证最终尺寸可读。",
                    "field": "tasks.parameters.y",
                    "suggested_action": (
                        "拆分 Harker 任务，或改用 publication-double-column。"
                    ),
                }
            )
    requested: list[str] = []
    if diagram in {"ree", "spider"}:
        requested = [str(value) for value in parameters.get("elements", [])]
    elif diagram == "harker":
        requested = [
            str(parameters.get("x", "")),
            *[str(value) for value in parameters.get("y", [])],
        ]
    elif diagram == "tas":
        requested = ["SiO2", "Na2O", "K2O"]
    elif diagram == "k2o-sio2":
        requested = ["SiO2", "K2O"]
    elif diagram == "xy":
        requested = [
            str(axis.get("id", ""))
            for axis in (parameters.get("x", {}), parameters.get("y", {}))
            if axis.get("kind") == "direct"
        ]
    missing = sorted(
        {value for value in requested if value and value not in set(recognized)}
    )
    if missing:
        issues.append(
            {
                "code": "E411",
                "severity": "review",
                "message": "任务所需分析项目未全部映射到输入表。",
                "field": "columns.mapping",
                "suggested_action": "补充列映射并重新生成计划。",
            }
        )
    if missing_groups:
        issues.append(
            {
                "code": "E412",
                "severity": "review",
                "message": "任务选择的分组未在输入表中找到。",
                "field": "tasks.parameters.groups",
                "suggested_action": "核对分组名称和 columns.group 后重新生成计划。",
            }
        )
    pattern_blocked = False
    if diagram in {"ree", "spider"} and not missing and not missing_groups:
        inspection_frame = pd.read_csv(inspection_path)
        canonical_columns = {
            mapping.canonical_analyte: (
                f"{mapping.canonical_analyte}_{mapping.unit}"
            )
            for mapping in prepared.mappings
        }
        spider_sources = {"K": "K2O", "P": "P2O5", "Ti": "TiO2"}
        positive_found = False
        for analyte in (str(value) for value in parameters.get("elements", [])):
            source_analyte = analyte
            if (
                diagram == "spider"
                and source_analyte not in canonical_columns
            ):
                source_analyte = spider_sources.get(analyte, analyte)
            column = canonical_columns.get(source_analyte)
            if column is None:
                continue
            values = pd.to_numeric(inspection_frame[column], errors="coerce")
            if bool((values.notna() & np.isfinite(values) & (values > 0)).any()):
                positive_found = True
                break
        if not positive_found:
            pattern_blocked = True
            issues.append(
                {
                    "code": "E419",
                    "severity": "review",
                    "message": "所选样品和元素没有任何可绘制的正有限值。",
                    "field": "tasks.parameters.groups",
                    "suggested_action": "检查分组、所选元素、缺失值和非正值。",
                }
            )
    harker_blocked = False
    if diagram == "harker":
        requested_y = [str(value) for value in parameters.get("y", [])]
        if len(requested_y) > 9:
            harker_blocked = True
            issues.append(
                {
                    "code": "E416",
                    "severity": "review",
                    "message": "Harker 图一次最多绘制 9 个 Y 变量。",
                    "field": "tasks.parameters.y",
                    "suggested_action": "拆分为多个 Harker 任务后重新生成计划。",
                }
            )
        if not missing and not missing_groups and selected_frame is not None:
            canonical_columns = {
                mapping.canonical_analyte: (
                    f"{mapping.canonical_analyte}_{mapping.unit}"
                )
                for mapping in prepared.mappings
            }
            x_name = str(parameters.get("x", ""))
            x_column = canonical_columns.get(x_name)
            insufficient: list[str] = []
            if x_column is not None:
                x_values = pd.to_numeric(
                    selected_frame[x_column], errors="coerce"
                )
                for y_name in requested_y:
                    y_column = canonical_columns.get(y_name)
                    if y_column is None:
                        continue
                    y_values = pd.to_numeric(
                        selected_frame[y_column], errors="coerce"
                    )
                    paired = (
                        x_values.notna()
                        & y_values.notna()
                        & np.isfinite(x_values)
                        & np.isfinite(y_values)
                    )
                    if int(paired.sum()) < 2:
                        insufficient.append(y_name)
            if insufficient:
                harker_blocked = True
                issues.append(
                    {
                        "code": "E417",
                        "severity": "review",
                        "message": "Harker 图的部分 X–Y 组合少于 2 对完整有限值。",
                        "field": "tasks.parameters.y",
                        "suggested_action": "检查缺失值、分组筛选或拆分任务后重新生成计划。",
                    }
                )
    tas_blocked = False
    if (
        diagram == "tas"
        and not missing
        and not missing_groups
        and selected_frame is not None
    ):
        canonical_columns = {
            mapping.canonical_analyte: (
                f"{mapping.canonical_analyte}_{mapping.unit}"
            )
            for mapping in prepared.mappings
        }
        silica = pd.to_numeric(
            selected_frame[canonical_columns["SiO2"]], errors="coerce"
        )
        sodium = pd.to_numeric(
            selected_frame[canonical_columns["Na2O"]], errors="coerce"
        )
        potassium = pd.to_numeric(
            selected_frame[canonical_columns["K2O"]], errors="coerce"
        )
        finite = (
            silica.notna()
            & sodium.notna()
            & potassium.notna()
            & np.isfinite(silica)
            & np.isfinite(sodium)
            & np.isfinite(potassium)
        )
        if int(finite.sum()) == 0:
            tas_blocked = True
            issues.append(
                {
                    "code": "E418",
                    "severity": "review",
                    "message": "所选样品没有可用于 TAS 分类的完整有限坐标。",
                    "field": "tasks.parameters.groups",
                    "suggested_action": "检查分组筛选以及 SiO2、Na2O、K2O 数据。",
                }
            )
    k2o_blocked = False
    if (
        diagram == "k2o-sio2"
        and not missing
        and not missing_groups
        and selected_frame is not None
    ):
        canonical_columns = {
            mapping.canonical_analyte: (
                f"{mapping.canonical_analyte}_{mapping.unit}"
            )
            for mapping in prepared.mappings
        }
        silica = pd.to_numeric(
            selected_frame[canonical_columns["SiO2"]], errors="coerce"
        )
        potassium = pd.to_numeric(
            selected_frame[canonical_columns["K2O"]], errors="coerce"
        )
        finite = (
            silica.notna()
            & potassium.notna()
            & np.isfinite(silica)
            & np.isfinite(potassium)
            & silica.ge(0)
            & potassium.ge(0)
        )
        if int(finite.sum()) == 0:
            k2o_blocked = True
            issues.append(
                {
                    "code": "E421",
                    "severity": "review",
                    "message": "所选样品没有可用于 K2O-SiO2 图的完整非负坐标。",
                    "field": "tasks.parameters.groups",
                    "suggested_action": "检查分组筛选、数据基准以及 SiO2 和 K2O 数据。",
                }
            )
    status = str(report.get("status", "blocked"))
    if (
        missing
        or missing_groups
        or pattern_blocked
        or harker_blocked
        or tas_blocked
        or k2o_blocked
        or resource_blocked
        or layout_blocked
        or status != "ready"
    ):
        status = "blocked"
    return {
        "task_id": str(task["id"]),
        "diagram": diagram,
        "status": status,
        "recognized_analytes": recognized,
        "issues": issues,
    }


def _comma_list(value: object) -> str | None:
    if value is None or value == "all":
        return None
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def _task_input_path(
    task: Mapping[str, Any],
    prepared: PreparedInput,
) -> Path:
    """Create a private per-task view with reviewed basis and group selection."""

    base_path = _basis_aware_path(task, prepared)
    if str(task["diagram"]) not in {"ree", "spider"}:
        return base_path
    selected = task.get("parameters", {}).get("groups", "all")
    if selected == "all":
        return base_path
    if prepared.group_column is None:
        raise AdapterError(
            "按组筛选前必须明确分组列。",
            code="E413",
        )
    frame = pd.read_csv(base_path)
    group_text = frame[prepared.group_column].astype("string").str.strip()
    requested = {str(item) for item in selected}
    subset = frame.loc[group_text.isin(requested)].copy()
    if subset.empty:
        raise AdapterError(
            "所选分组没有可绘制样品。",
            code="E414",
        )
    task_id = str(task["id"])
    subset_path = prepared.path.parent / f"mapped_input.{task_id}.csv"
    subset.to_csv(subset_path, index=False)
    return subset_path


def run_task(
    task: Mapping[str, Any],
    prepared: PreparedInput,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Call one fixed v0.3 plotter with fully expanded recipe parameters."""

    diagram = str(task["diagram"])
    parameters = dict(task.get("parameters", {}))
    style = dict(task.get("style", {}))
    task_input_path = _task_input_path(task, prepared)
    output_dir.mkdir(parents=True, exist_ok=False)
    common = {
        "input_path": task_input_path,
        "output_dir": output_dir,
        "stem": str(task["stem"]),
        "requested_sheet": None,
        "requested_sample_column": prepared.sample_column,
        "requested_group_column": prepared.group_column,
        "title": parameters.get("title"),
        "dpi": int(style["dpi"]),
        "overwrite": False,
        "style_preset": str(style["base_preset"]),
    }

    if diagram == "ree":
        from plot_ree import plot_path

        return plot_path(
            **common,
            requested_elements=_comma_list(parameters["elements"]),
            width_mm=float(style["width_mm"]),
            height_mm=float(style["height_mm"]),
            y_margin=float(style.get("y_margin", 0.08)),
            axes_frame=str(style.get("axes_frame", "full")),
            legend_layout=str(style.get("legend_layout", "inside-auto")),
            grid_style=str(style.get("grid_style", "none")),
            show_sample_ids=bool(style.get("show_sample_ids", True)),
            group_legend_title="Group",
            show_reference_note=bool(style.get("show_reference_note", True)),
        )
    if diagram == "spider":
        from plot_spider import plot_spider_path

        return plot_spider_path(
            **common,
            reference_key=str(parameters["reference"]),
            requested_elements=_comma_list(parameters["elements"]),
            width_mm=float(style["width_mm"]),
            height_mm=float(style["height_mm"]),
            y_margin=float(style.get("y_margin", 0.08)),
            axes_frame=str(style.get("axes_frame", "full")),
            legend_layout=str(style.get("legend_layout", "inside-auto")),
            grid_style=str(style.get("grid_style", "none")),
            show_sample_ids=bool(style.get("show_sample_ids", True)),
            group_legend_title="Group",
            show_reference_note=bool(style.get("show_reference_note", True)),
        )
    if diagram == "harker":
        from plot_harker import plot_harker_path

        return plot_harker_path(
            **common,
            requested_x=str(parameters["x"]),
            requested_y=_comma_list(parameters["y"]),
            requested_groups=_comma_list(parameters.get("groups", "all")),
            width_mm=float(style["width_mm"]),
            height_mm=(
                None
                if style.get("height_mm") is None
                else float(style["height_mm"])
            ),
            columns=(
                None
                if parameters.get("columns") is None
                else int(parameters["columns"])
            ),
            axes_frame=str(style.get("axes_frame", "full")),
            margin_fraction=float(style.get("margin_fraction", 0.06)),
        )
    if diagram == "tas":
        from plot_tas import plot_tas_path

        confirmations = task.get("confirmations", {})
        return plot_tas_path(
            **common,
            requested_groups=_comma_list(parameters.get("groups", "all")),
            confirm_volcanic=bool(confirmations.get("volcanic_samples")),
            composition_basis=str(parameters["composition_basis"]),
            width_mm=float(style["width_mm"]),
            height_mm=float(style["height_mm"]),
            legend_layout=str(style.get("legend_layout", "inside-auto")),
            show_reference_note=bool(style.get("show_reference_note", True)),
        )
    if diagram == "k2o-sio2":
        from plot_k2o_sio2 import plot_k2o_sio2_path

        confirmations = task.get("confirmations", {})
        return plot_k2o_sio2_path(
            **common,
            requested_groups=_comma_list(parameters.get("groups", "all")),
            confirm_volcanic=bool(confirmations.get("volcanic_samples")),
            composition_basis=str(parameters["composition_basis"]),
            width_mm=float(style["width_mm"]),
            height_mm=float(style["height_mm"]),
            legend_layout=str(style.get("legend_layout", "inside-auto")),
            show_reference_note=bool(style.get("show_reference_note", True)),
        )
    if diagram == "xy":
        from plot_xy import plot_xy_path

        analyte_columns = {
            mapping.canonical_analyte: (
                f"{mapping.canonical_analyte}_{mapping.unit}"
            )
            for mapping in prepared.mappings
        }
        analyte_units = {
            mapping.canonical_analyte: mapping.unit
            for mapping in prepared.mappings
        }
        return plot_xy_path(
            **common,
            x_reference=parameters["x"],
            y_reference=parameters["y"],
            analyte_columns=analyte_columns,
            analyte_units=analyte_units,
            derived_summary=prepared.derived,
            requested_groups=parameters.get("groups", "all"),
            width_mm=float(style["width_mm"]),
            height_mm=float(style["height_mm"]),
        )
    raise AdapterError(
        "图件类型不在固定注册表中。",
        code="E410",
        details={"diagram": diagram},
    )
