"""Safe, strict YAML recipe validation for the GeoSkills v0.4 workflow."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

import yaml

from .analytes import (
    DEFAULT_ANALYTE_REGISTRY,
    REE_ORDER,
    SPIDER_ELEMENT_ORDER,
)
from .registry import BUILTIN_STYLE_PRESETS, DIAGRAMS


RECIPE_SCHEMA_VERSION = "geoskills.recipe/v1"
MAX_RECIPE_BYTES = 256 * 1024
MAX_TASKS = 32

_ROOT_FIELDS = {
    "schema_version",
    "input",
    "columns",
    "output",
    "presets",
    "confirmations",
    "tasks",
}
_REQUIRED_ROOT_FIELDS = _ROOT_FIELDS - {"presets"}
_INPUT_FIELDS = {"file", "sheet", "layout"}
_COLUMN_FIELDS = {"sample_id", "group", "mapping", "units"}
_OUTPUT_FIELDS = {"directory", "report_profile"}
_PRESET_FIELDS = {"extends", "style"}
_STYLE_FIELDS = {"width_mm", "height_mm", "dpi"}
_TASK_FIELDS = {
    "id",
    "diagram",
    "stem",
    "preset",
    "parameters",
    "confirmations",
}
_TOP_CONFIRMATIONS = (
    "input_structure_reviewed",
    "column_mapping_reviewed",
    "units_reviewed",
    "plotted_data_export_reviewed",
)
_TAS_CONFIRMATIONS = (
    "volcanic_samples",
    "composition_basis_reviewed",
)
_PROTECTED_OUTPUT_SEGMENTS = frozenset(
    {".git", ".codex", "skills", "tests"}
)
_RESERVED_TASK_IDS = frozenset({"_work"})
_URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_GLOB_CHARS = frozenset("*?[]{}")
_WINDOWS_ILLEGAL = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_REFERENCE_OPTIONS = {
    "ree": frozenset({"chondrite-sm89"}),
    "spider": frozenset({"pm-sm89", "pm-sm89-modified", "nmorb-sm89"}),
}
_SPIDER_OXIDE_ALTERNATIVES = {
    "K": "K2O",
    "P": "P2O5",
    "Ti": "TiO2",
}
_PARAMETER_FIELDS = {
    "ree": frozenset({"reference", "elements", "groups"}),
    "spider": frozenset({"reference", "elements", "groups"}),
    "harker": frozenset({"x", "y", "groups"}),
    "tas": frozenset({"composition_basis", "groups"}),
}
_PARAMETER_REQUIRED = {
    "ree": frozenset({"reference", "elements"}),
    "spider": frozenset({"reference", "elements"}),
    "harker": frozenset({"x", "y"}),
    "tas": frozenset({"composition_basis"}),
}
_LAYOUTS = frozenset(
    {"row-per-sample", "analyte-per-row", "auto"}
)
_REPORT_PROFILES = frozenset({"shareable", "local-reproducible"})


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    field: str | None = None,
    task_id: str | None = None,
    suggested_action: str | None = None,
) -> dict[str, str]:
    result = {"code": code, "severity": severity, "message": message}
    if field is not None:
        result["field"] = field
    if task_id is not None:
        result["task_id"] = task_id
    if suggested_action is not None:
        result["suggested_action"] = suggested_action
    return result


def _result(
    *,
    recipe: dict[str, Any] | None,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    has_error = any(item["severity"] == "error" for item in issues)
    has_review = any(item["severity"] == "review" for item in issues)
    status = "invalid" if has_error else ("needs_review" if has_review else "ready")
    result = {
        "status": status,
        "recipe": None if has_error else recipe,
        "issues": issues,
    }
    # This is an internal assertion that guards the public JSON-ready promise.
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return result


def _mapping(value: Any, field: str, issues: list[dict[str, str]]) -> dict[Any, Any]:
    if not isinstance(value, Mapping):
        issues.append(
            _issue("E306", "error", "该字段必须是键值映射。", field=field)
        )
        return {}
    return dict(value)


def _unknown_fields(
    value: Mapping[Any, Any],
    allowed: Iterable[str],
    field: str,
    issues: list[dict[str, str]],
    *,
    task_id: str | None = None,
) -> None:
    allowed_set = set(allowed)
    for key in value:
        if not isinstance(key, str) or key not in allowed_set:
            issues.append(
                _issue(
                    "E304",
                    "error",
                    f"发现未支持字段：{key!r}。",
                    field=f"{field}.{key}",
                    task_id=task_id,
                    suggested_action="删除该字段或按模板使用受支持的字段名。",
                )
            )


def _missing_fields(
    value: Mapping[Any, Any],
    required: Iterable[str],
    field: str,
    issues: list[dict[str, str]],
    *,
    task_id: str | None = None,
) -> None:
    for name in sorted(set(required) - set(value)):
        issues.append(
            _issue(
                "E305",
                "error",
                f"缺少必填字段：{name}。",
                field=f"{field}.{name}",
                task_id=task_id,
            )
        )


def _nonempty_string(
    value: Any,
    field: str,
    issues: list[dict[str, str]],
    *,
    task_id: str | None = None,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            _issue(
                "E306",
                "error",
                "该字段必须是非空文本。",
                field=field,
                task_id=task_id,
            )
        )
        return None
    return value.strip()


def _safe_relative_path(
    value: Any,
    field: str,
    issues: list[dict[str, str]],
    *,
    output: bool = False,
) -> str | None:
    text = _nonempty_string(value, field, issues)
    if text is None:
        return None
    windows_path = PureWindowsPath(text)
    unsafe = (
        "\x00" in text
        or any(ord(character) < 32 for character in text)
        or "$" in text
        or "%" in text
        or _URI_PATTERN.match(text) is not None
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or text.startswith(("/", "\\"))
        or any(character in text for character in _GLOB_CHARS)
        or any(character in text for character in '<>:"|')
    )
    normalized = text.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if any(
        part in {"..", ""}
        or part.startswith("~")
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].rstrip(" .").upper()
        in _WINDOWS_RESERVED
        for part in parts
    ):
        unsafe = True
    if unsafe:
        issues.append(
            _issue(
                "E307",
                "error",
                "路径必须是配方目录内的安全相对路径；不能使用 URI、绝对路径、环境变量、通配符或 ..。",
                field=field,
            )
        )
        return None
    cleaned_parts = [part for part in parts if part != "."]
    cleaned = "/".join(cleaned_parts) or "."
    if output and (
        cleaned == "."
        or any(
            part.rstrip(" .").casefold() in _PROTECTED_OUTPUT_SEGMENTS
            for part in cleaned_parts
        )
    ):
        issues.append(
            _issue(
                "E307",
                "error",
                "输出目录必须是专用子目录，且不能指向配方根目录、.git、.codex、skills 或 tests。",
                field=field,
            )
        )
        return None
    return cleaned


def _safe_windows_name(
    value: Any,
    field: str,
    issues: list[dict[str, str]],
    *,
    task_id: str | None = None,
    allow_dot: bool = False,
) -> str | None:
    text = _nonempty_string(value, field, issues, task_id=task_id)
    if text is None:
        return None
    invalid = (
        text in {".", ".."}
        or text[-1] in {" ", "."}
        or any(character in _WINDOWS_ILLEGAL for character in text)
        or any(ord(character) < 32 for character in text)
        or (not allow_dot and Path(text).suffix != "")
        or text.split(".", 1)[0].upper() in _WINDOWS_RESERVED
    )
    if invalid:
        issues.append(
            _issue(
                "E307",
                "error",
                "名称必须是跨 Windows/Linux 安全的单一名称，且不能包含扩展名或路径。",
                field=field,
                task_id=task_id,
            )
        )
        return None
    return text


def _confirmation_map(
    raw: Any,
    required: Iterable[str],
    field: str,
    issues: list[dict[str, str]],
    *,
    task_id: str | None = None,
    optional: Iterable[str] = (),
) -> dict[str, bool]:
    value = _mapping(raw, field, issues)
    allowed = tuple(required) + tuple(optional)
    _unknown_fields(value, allowed, field, issues, task_id=task_id)
    _missing_fields(value, required, field, issues, task_id=task_id)
    normalized: dict[str, bool] = {}
    for name in allowed:
        if name not in value:
            continue
        state = value[name]
        if not isinstance(state, bool):
            issues.append(
                _issue(
                    "E306",
                    "error",
                    "确认项必须明确写为 true 或 false。",
                    field=f"{field}.{name}",
                    task_id=task_id,
                )
            )
            continue
        normalized[name] = state
        if not state:
            issues.append(
                _issue(
                    "R312",
                    "review",
                    "该科学或数据确认项尚未确认。",
                    field=f"{field}.{name}",
                    task_id=task_id,
                    suggested_action="复核后将该项明确设为 true。",
                )
            )
    return normalized


def _validate_input(
    raw: Any, issues: list[dict[str, str]]
) -> dict[str, Any]:
    value = _mapping(raw, "input", issues)
    _unknown_fields(value, _INPUT_FIELDS, "input", issues)
    _missing_fields(value, _INPUT_FIELDS, "input", issues)
    normalized: dict[str, Any] = {}
    input_file = _safe_relative_path(value.get("file"), "input.file", issues)
    if input_file is not None:
        normalized["file"] = input_file
    sheet = value.get("sheet")
    if sheet is None or (
        isinstance(sheet, str) and sheet.strip()
    ) or (
        isinstance(sheet, int)
        and not isinstance(sheet, bool)
        and 0 <= sheet <= 65_535
    ):
        # Excel permits leading/trailing spaces in worksheet names.  Validate
        # against an all-whitespace name, but preserve the exact spelling.
        normalized["sheet"] = sheet
    else:
        issues.append(
            _issue(
                "E306",
                "error",
                "sheet 必须是工作表名称、0–65535 的整数或 null。",
                field="input.sheet",
            )
        )
    layout = value.get("layout")
    if not isinstance(layout, str) or layout not in _LAYOUTS:
        issues.append(
            _issue(
                "E306",
                "error",
                "layout 必须是 row-per-sample、analyte-per-row 或 auto。",
                field="input.layout",
            )
        )
    else:
        normalized["layout"] = layout
    return normalized


def _validate_columns(
    raw: Any, issues: list[dict[str, str]]
) -> tuple[dict[str, Any], set[str]]:
    value = _mapping(raw, "columns", issues)
    _unknown_fields(value, _COLUMN_FIELDS, "columns", issues)
    _missing_fields(value, _COLUMN_FIELDS, "columns", issues)
    normalized: dict[str, Any] = {}

    sample_id = _nonempty_string(value.get("sample_id"), "columns.sample_id", issues)
    if sample_id is not None:
        normalized["sample_id"] = sample_id
    group = value.get("group")
    if group is None:
        normalized["group"] = None
    else:
        group_name = _nonempty_string(group, "columns.group", issues)
        if group_name is not None:
            normalized["group"] = group_name

    mapping = _mapping(value.get("mapping"), "columns.mapping", issues)
    normalized_mapping: dict[str, str] = {}
    source_names: dict[str, str] = {}
    for canonical, source in mapping.items():
        field = f"columns.mapping.{canonical}"
        if not isinstance(canonical, str) or (
            DEFAULT_ANALYTE_REGISTRY.get(canonical) is None
        ):
            issues.append(
                _issue(
                    "E313",
                    "error",
                    "mapping 的键必须是 GeoSkills 精确标准分析物名称；方向为 canonical→source。",
                    field=field,
                )
            )
            continue
        source_name = _nonempty_string(source, field, issues)
        if source_name is None:
            continue
        source_key = source_name.casefold()
        if source_key in source_names:
            issues.append(
                _issue(
                    "E308",
                    "error",
                    "同一来源列不能映射到多个分析物："
                    f"{source_names[source_key]} 与 {canonical}。",
                    field=field,
                )
            )
            continue
        source_names[source_key] = canonical
        normalized_mapping[canonical] = source_name
    if not mapping:
        issues.append(
            _issue(
                "E313",
                "error",
                "columns.mapping 至少需要一个 canonical→source 映射。",
                field="columns.mapping",
            )
        )

    metadata_sources = {
        name.casefold()
        for name in (sample_id, normalized.get("group"))
        if isinstance(name, str)
    }
    overlap = metadata_sources.intersection(source_names)
    if overlap:
        issues.append(
            _issue(
                "E308",
                "error",
                "样品编号/分组列不能同时用作分析物来源列。",
                field="columns.mapping",
            )
        )

    units = _mapping(value.get("units"), "columns.units", issues)
    normalized_units: dict[str, str] = {}
    allowed_unit_keys = {"major_oxides", "trace_elements", *normalized_mapping}
    _unknown_fields(units, allowed_unit_keys, "columns.units", issues)
    for unit_key, unit_value in units.items():
        if not isinstance(unit_key, str) or unit_key not in allowed_unit_keys:
            continue
        expected = (
            "wt%"
            if unit_key == "major_oxides"
            else "ppm" if unit_key == "trace_elements" else None
        )
        definition = DEFAULT_ANALYTE_REGISTRY.get(unit_key)
        if definition is not None:
            expected = definition.required_unit
        if unit_value != expected:
            issues.append(
                _issue(
                    "E313",
                    "error",
                    f"{unit_key} 当前工作流要求明确单位 {expected}。",
                    field=f"columns.units.{unit_key}",
                )
            )
            continue
        normalized_units[unit_key] = unit_value

    for canonical in normalized_mapping:
        definition = DEFAULT_ANALYTE_REGISTRY.get(canonical)
        assert definition is not None
        default_key = (
            "major_oxides"
            if definition.kind == "major_oxide"
            else "trace_elements"
        )
        if canonical not in normalized_units and default_key not in normalized_units:
            issues.append(
                _issue(
                    "E313",
                    "error",
                    f"{canonical} 缺少明确单位；请设置 {default_key} 默认值或单项覆盖。",
                    field=f"columns.units.{canonical}",
                )
            )

    normalized["mapping"] = dict(sorted(normalized_mapping.items()))
    normalized["units"] = dict(sorted(normalized_units.items()))
    return normalized, set(normalized_mapping)


def _validate_output(
    raw: Any, issues: list[dict[str, str]]
) -> dict[str, Any]:
    value = _mapping(raw, "output", issues)
    _unknown_fields(value, _OUTPUT_FIELDS, "output", issues)
    _missing_fields(value, _OUTPUT_FIELDS, "output", issues)
    normalized: dict[str, Any] = {}
    directory = _safe_relative_path(
        value.get("directory"), "output.directory", issues, output=True
    )
    if directory is not None:
        normalized["directory"] = directory
    profile = value.get("report_profile")
    if not isinstance(profile, str) or profile not in _REPORT_PROFILES:
        issues.append(
            _issue(
                "E306",
                "error",
                "report_profile 必须是 shareable 或 local-reproducible。",
                field="output.report_profile",
            )
        )
    else:
        normalized["report_profile"] = profile
    return normalized


def _validate_style(
    raw: Any,
    field: str,
    issues: list[dict[str, str]],
) -> dict[str, int | float]:
    value = _mapping(raw, field, issues)
    _unknown_fields(value, _STYLE_FIELDS, field, issues)
    normalized: dict[str, int | float] = {}
    for name in ("width_mm", "height_mm"):
        if name not in value:
            continue
        number = value[name]
        try:
            converted = float(number)
        except (OverflowError, TypeError, ValueError):
            converted = math.nan
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(converted)
            or not 30 <= converted <= 500
        ):
            issues.append(
                _issue(
                    "E314",
                    "error",
                    f"{name} 必须是 30–500 mm 的有限数值。",
                    field=f"{field}.{name}",
                )
            )
        else:
            normalized[name] = converted
    if "dpi" in value:
        dpi = value["dpi"]
        if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 1200:
            issues.append(
                _issue(
                    "E314",
                    "error",
                    "dpi 必须是 72–1200 的整数。",
                    field=f"{field}.dpi",
                )
            )
        else:
            normalized["dpi"] = dpi
    return normalized


def _validate_presets(
    raw: Any, issues: list[dict[str, str]]
) -> tuple[dict[str, Any], dict[str, str]]:
    if raw is None:
        return {}, {name.casefold(): name for name in BUILTIN_STYLE_PRESETS}
    value = _mapping(raw, "presets", issues)
    normalized: dict[str, Any] = {}
    names = {name.casefold(): name for name in BUILTIN_STYLE_PRESETS}
    for raw_name, raw_preset in value.items():
        name = _safe_windows_name(
            raw_name, f"presets.{raw_name}", issues, allow_dot=True
        )
        if name is None:
            continue
        key = name.casefold()
        if key in names:
            issues.append(
                _issue(
                    "E308",
                    "error",
                    f"预设名称与已有名称重复：{names[key]}。",
                    field=f"presets.{name}",
                )
            )
            continue
        names[key] = name
        preset = _mapping(raw_preset, f"presets.{name}", issues)
        _unknown_fields(preset, _PRESET_FIELDS, f"presets.{name}", issues)
        _missing_fields(preset, _PRESET_FIELDS, f"presets.{name}", issues)
        extends = preset.get("extends")
        if extends not in BUILTIN_STYLE_PRESETS:
            issues.append(
                _issue(
                    "E314",
                    "error",
                    "extends 必须指向 publication-double-column 或 review-preview。",
                    field=f"presets.{name}.extends",
                )
            )
        style = _validate_style(
            preset.get("style"), f"presets.{name}.style", issues
        )
        normalized[name] = {"extends": extends, "style": style}
    return normalized, names


def _groups(
    raw: Any,
    field: str,
    issues: list[dict[str, str]],
    *,
    task_id: str,
    has_group_column: bool,
) -> str | list[str] | None:
    if raw == "all":
        return "all"
    if not isinstance(raw, list) or not raw:
        issues.append(
            _issue(
                "E311",
                "error",
                "groups 必须是 'all' 或非空文本列表。",
                field=field,
                task_id=task_id,
            )
        )
        return None
    if not has_group_column:
        issues.append(
            _issue(
                "E311",
                "error",
                "选择具体 groups 前必须设置 columns.group。",
                field=field,
                task_id=task_id,
            )
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        name = _nonempty_string(
            item, f"{field}[{index}]", issues, task_id=task_id
        )
        if name is None:
            continue
        key = name.casefold()
        if key in seen:
            issues.append(
                _issue(
                    "E308",
                    "error",
                    "groups 不能包含 Windows 不区分大小写的重复名称。",
                    field=f"{field}[{index}]",
                    task_id=task_id,
                )
            )
            continue
        seen.add(key)
        normalized.append(name)
    return normalized


def _canonical(
    raw: Any,
    field: str,
    issues: list[dict[str, str]],
    mapped: set[str],
    *,
    task_id: str,
    allowed: set[str] | frozenset[str] | None = None,
) -> str | None:
    name = _nonempty_string(raw, field, issues, task_id=task_id)
    if name is None:
        return None
    definition = DEFAULT_ANALYTE_REGISTRY.get(name)
    if definition is None or (allowed is not None and name not in allowed):
        issues.append(
            _issue(
                "E311",
                "error",
                "参数必须使用该图解支持的精确标准分析物名称。",
                field=field,
                task_id=task_id,
            )
        )
        return None
    if name not in mapped:
        issues.append(
            _issue(
                "E313",
                "error",
                f"{name} 未在 columns.mapping 中映射到来源列。",
                field=field,
                task_id=task_id,
            )
        )
    return name


def _elements(
    raw: Any,
    field: str,
    issues: list[dict[str, str]],
    mapped: set[str],
    *,
    task_id: str,
    diagram: str,
) -> list[str]:
    minimum = 3 if diagram == "ree" else 5
    allowed = set(REE_ORDER if diagram == "ree" else SPIDER_ELEMENT_ORDER)
    mapped_for_elements = set(mapped)
    if diagram == "spider":
        mapped_for_elements.update(
            element
            for element, oxide in _SPIDER_OXIDE_ALTERNATIVES.items()
            if oxide in mapped
        )
    if not isinstance(raw, list):
        issues.append(
            _issue(
                "E311",
                "error",
                f"elements 必须是至少 {minimum} 项的列表。",
                field=field,
                task_id=task_id,
            )
        )
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        name = _canonical(
            item,
            f"{field}[{index}]",
            issues,
            mapped_for_elements,
            task_id=task_id,
            allowed=allowed,
        )
        if name is None:
            continue
        if name in seen:
            issues.append(
                _issue(
                    "E308",
                    "error",
                    "elements 不能重复。",
                    field=f"{field}[{index}]",
                    task_id=task_id,
                )
            )
            continue
        seen.add(name)
        normalized.append(name)
    if len(raw) < minimum:
        issues.append(
            _issue(
                "E311",
                "error",
                f"{diagram} 图至少需要 {minimum} 个元素。",
                field=field,
                task_id=task_id,
            )
        )
    return normalized


def _validate_parameters(
    raw: Any,
    diagram: str,
    task_id: str,
    mapped: set[str],
    has_group_column: bool,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    field = f"tasks[{task_id}].parameters"
    value = _mapping(raw, field, issues)
    _unknown_fields(value, _PARAMETER_FIELDS[diagram], field, issues, task_id=task_id)
    _missing_fields(value, _PARAMETER_REQUIRED[diagram], field, issues, task_id=task_id)
    normalized: dict[str, Any] = {}
    if "groups" in value:
        selected = _groups(
            value["groups"],
            f"{field}.groups",
            issues,
            task_id=task_id,
            has_group_column=has_group_column,
        )
        if selected is not None:
            normalized["groups"] = selected

    if diagram in {"ree", "spider"}:
        reference = value.get("reference")
        if (
            not isinstance(reference, str)
            or reference not in _REFERENCE_OPTIONS[diagram]
        ):
            issues.append(
                _issue(
                    "E311",
                    "error",
                    f"{diagram} reference 不在已审核的固定选项中。",
                    field=f"{field}.reference",
                    task_id=task_id,
                )
            )
        else:
            normalized["reference"] = reference
        normalized["elements"] = _elements(
            value.get("elements"),
            f"{field}.elements",
            issues,
            mapped,
            task_id=task_id,
            diagram=diagram,
        )
    elif diagram == "harker":
        x = _canonical(
            value.get("x"),
            f"{field}.x",
            issues,
            mapped,
            task_id=task_id,
        )
        if x is not None:
            normalized["x"] = x
        raw_y = value.get("y")
        y_values = raw_y if isinstance(raw_y, list) else [raw_y]
        normalized_y: list[str] = []
        for index, item in enumerate(y_values):
            y_name = _canonical(
                item,
                f"{field}.y[{index}]",
                issues,
                mapped,
                task_id=task_id,
            )
            if y_name is not None:
                if y_name in normalized_y:
                    issues.append(
                        _issue(
                            "E308",
                            "error",
                            "Harker y 变量不能重复。",
                            field=f"{field}.y[{index}]",
                            task_id=task_id,
                        )
                    )
                else:
                    normalized_y.append(y_name)
        if not normalized_y:
            issues.append(
                _issue(
                    "E311",
                    "error",
                    "Harker y 至少需要一个非空标准分析物名称。",
                    field=f"{field}.y",
                    task_id=task_id,
                )
            )
        if x is not None and x in normalized_y:
            issues.append(
                _issue(
                    "E311",
                    "error",
                    "Harker x 与 y 不能使用同一分析物。",
                    field=f"{field}.y",
                    task_id=task_id,
                )
            )
        normalized["y"] = normalized_y
    else:
        basis = value.get("composition_basis")
        if (
            not isinstance(basis, str)
            or basis not in {"anhydrous-normalized", "as-reported"}
        ):
            issues.append(
                _issue(
                    "E311",
                    "error",
                    "TAS composition_basis 必须明确为 anhydrous-normalized 或 as-reported。",
                    field=f"{field}.composition_basis",
                    task_id=task_id,
                )
            )
        else:
            normalized["composition_basis"] = basis
        for required_analyte in ("SiO2", "Na2O", "K2O"):
            if required_analyte not in mapped:
                issues.append(
                    _issue(
                        "E313",
                        "error",
                        f"TAS 需要在 columns.mapping 中映射 {required_analyte}。",
                        field="columns.mapping",
                        task_id=task_id,
                    )
                )
    return normalized


def _validate_tasks(
    raw: Any,
    mapped: set[str],
    has_group_column: bool,
    preset_names: Mapping[str, str],
    issues: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        issues.append(
            _issue("E306", "error", "tasks 必须是列表。", field="tasks")
        )
        return []
    if not raw:
        issues.append(
            _issue("E309", "error", "tasks 至少需要一个任务。", field="tasks")
        )
    if len(raw) > MAX_TASKS:
        issues.append(
            _issue(
                "E309",
                "error",
                f"单个配方最多允许 {MAX_TASKS} 个任务。",
                field="tasks",
            )
        )

    normalized: list[dict[str, Any]] = []
    task_names: dict[str, str] = {}
    stems: dict[str, str] = {}
    for index, raw_task in enumerate(raw[:MAX_TASKS]):
        field = f"tasks[{index}]"
        value = _mapping(raw_task, field, issues)
        _unknown_fields(value, _TASK_FIELDS, field, issues)
        _missing_fields(value, _TASK_FIELDS, field, issues)
        task_id = _safe_windows_name(value.get("id"), f"{field}.id", issues)
        task_label = task_id or f"#{index + 1}"
        if task_id is not None:
            key = task_id.casefold()
            if key in _RESERVED_TASK_IDS:
                issues.append(
                    _issue(
                        "E307",
                        "error",
                        "任务 ID 与 GeoSkills 内部工作目录名称冲突。",
                        field=f"{field}.id",
                        task_id=task_id,
                    )
                )
            if key in task_names:
                issues.append(
                    _issue(
                        "E308",
                        "error",
                        f"任务 ID 与 {task_names[key]!r} 在 Windows 下重复。",
                        field=f"{field}.id",
                        task_id=task_id,
                    )
                )
            else:
                task_names[key] = task_id

        stem = _safe_windows_name(
            value.get("stem"), f"{field}.stem", issues, task_id=task_label
        )
        if stem is not None:
            key = stem.casefold()
            if key in stems:
                issues.append(
                    _issue(
                        "E308",
                        "error",
                        f"输出 stem 与 {stems[key]!r} 在 Windows 下重复。",
                        field=f"{field}.stem",
                        task_id=task_label,
                    )
                )
            else:
                stems[key] = stem

        diagram = value.get("diagram")
        if not isinstance(diagram, str) or diagram not in DIAGRAMS:
            issues.append(
                _issue(
                    "E310",
                    "error",
                    "diagram 只能是 ree、spider、harker 或 tas。",
                    field=f"{field}.diagram",
                    task_id=task_label,
                )
            )
            diagram = None

        preset = value.get("preset")
        preset_name = None
        if isinstance(preset, str):
            preset_name = preset_names.get(preset.casefold())
        if preset_name is None:
            issues.append(
                _issue(
                    "E314",
                    "error",
                    "preset 必须引用固定预设或本配方中的自定义预设。",
                    field=f"{field}.preset",
                    task_id=task_label,
                )
            )

        parameters: dict[str, Any] = {}
        confirmations: dict[str, bool] = {}
        if diagram is not None:
            parameters = _validate_parameters(
                value.get("parameters"),
                diagram,
                task_label,
                mapped,
                has_group_column,
                issues,
            )
            required = _TAS_CONFIRMATIONS if diagram == "tas" else ()
            optional = (
                ("provisional_classification_accepted",)
                if diagram == "tas"
                else ()
            )
            confirmations = _confirmation_map(
                value.get("confirmations"),
                required,
                f"{field}.confirmations",
                issues,
                task_id=task_label,
                optional=optional,
            )
            if (
                diagram == "tas"
                and parameters.get("composition_basis") == "as-reported"
            ):
                accepted = confirmations.get(
                    "provisional_classification_accepted"
                )
                if accepted is not True:
                    if (
                        "provisional_classification_accepted"
                        not in confirmations
                    ):
                        issues.append(
                            _issue(
                                "E305",
                                "error",
                                "as-reported TAS 必须明确提供 "
                                "provisional_classification_accepted。",
                                field=(
                                    f"{field}.confirmations."
                                    "provisional_classification_accepted"
                                ),
                                task_id=task_label,
                            )
                        )
        normalized.append(
            {
                "id": task_id,
                "diagram": diagram,
                "stem": stem,
                "preset": preset_name,
                "parameters": parameters,
                "confirmations": confirmations,
            }
        )
    return normalized


def validate_recipe(document: Any) -> dict[str, Any]:
    """Validate one parsed YAML document and return a JSON-ready result."""

    issues: list[dict[str, str]] = []
    if not isinstance(document, Mapping):
        issues.append(
            _issue(
                "E303",
                "error",
                "配方顶层必须是键值映射。",
                field="$",
            )
        )
        return _result(recipe=None, issues=issues)
    root = dict(document)
    _unknown_fields(root, _ROOT_FIELDS, "$", issues)
    _missing_fields(root, _REQUIRED_ROOT_FIELDS, "$", issues)
    if root.get("schema_version") != RECIPE_SCHEMA_VERSION:
        issues.append(
            _issue(
                "E306",
                "error",
                f"schema_version 必须是 {RECIPE_SCHEMA_VERSION!r}。",
                field="schema_version",
            )
        )

    normalized_input = _validate_input(root.get("input"), issues)
    normalized_columns, mapped = _validate_columns(root.get("columns"), issues)
    normalized_output = _validate_output(root.get("output"), issues)
    normalized_presets, preset_names = _validate_presets(
        root.get("presets"), issues
    )
    normalized_confirmations = _confirmation_map(
        root.get("confirmations"),
        _TOP_CONFIRMATIONS,
        "confirmations",
        issues,
    )
    normalized_tasks = _validate_tasks(
        root.get("tasks"),
        mapped,
        normalized_columns.get("group") is not None,
        preset_names,
        issues,
    )
    recipe = {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "input": normalized_input,
        "columns": normalized_columns,
        "output": normalized_output,
        "presets": normalized_presets,
        "confirmations": normalized_confirmations,
        "tasks": normalized_tasks,
    }
    return _result(recipe=recipe, issues=issues)


def load_recipe(path: str | Path) -> dict[str, Any]:
    """Safely read and validate one UTF-8, single-document YAML recipe."""

    recipe_path = Path(path)
    issues: list[dict[str, str]] = []
    try:
        size = recipe_path.stat().st_size
    except OSError:
        issues.append(
            _issue(
                "E300",
                "error",
                "无法读取配方文件。",
                field="$",
            )
        )
        return _result(recipe=None, issues=issues)
    if size > MAX_RECIPE_BYTES:
        issues.append(
            _issue(
                "E300",
                "error",
                f"配方文件不能超过 {MAX_RECIPE_BYTES} 字节。",
                field="$",
            )
        )
        return _result(recipe=None, issues=issues)
    try:
        text = recipe_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        issues.append(
            _issue(
                "E301",
                "error",
                "配方必须是可读取的 UTF-8 YAML 文件。",
                field="$",
            )
        )
        return _result(recipe=None, issues=issues)
    try:
        document = yaml.safe_load(text)
    except yaml.composer.ComposerError as exc:
        multiple_documents = "expected a single document" in str(exc)
        issues.append(
            _issue(
                "E302" if multiple_documents else "E301",
                "error",
                (
                    "每个配方文件只能包含一个 YAML 文档。"
                    if multiple_documents
                    else "YAML 文档结构无法解析。"
                ),
                field="$",
            )
        )
        return _result(recipe=None, issues=issues)
    except (yaml.YAMLError, OverflowError, RecursionError, ValueError):
        issues.append(
            _issue(
                "E301",
                "error",
                "YAML 语法无法解析。",
                field="$",
            )
        )
        return _result(recipe=None, issues=issues)
    return validate_recipe(document)


def resolve_recipe_path(recipe_path: str | Path, relative_value: str) -> Path:
    """Resolve a previously validated recipe member against its recipe file."""

    issues: list[dict[str, str]] = []
    safe = _safe_relative_path(relative_value, "path", issues)
    if safe is None:
        raise ValueError(issues[0]["message"])
    recipe_root = Path(recipe_path).resolve().parent
    resolved = (recipe_root / Path(safe)).resolve()
    try:
        resolved.relative_to(recipe_root)
    except ValueError as exc:
        raise ValueError(
            "Resolved recipe path escapes the recipe directory."
        ) from exc
    return resolved


__all__ = [
    "MAX_RECIPE_BYTES",
    "MAX_TASKS",
    "RECIPE_SCHEMA_VERSION",
    "load_recipe",
    "resolve_recipe_path",
    "validate_recipe",
]
