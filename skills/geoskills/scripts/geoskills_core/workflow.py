"""Deterministic plan/run orchestration for GeoSkills."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image

from .adapters import PreparedInput, inspect_task, prepare_mapped_input, run_task
from .errors import GeoSkillsError
from .export import (
    AtomicDirectory,
    BundleExportError,
    shareable_file_record,
    sha256_file,
)
from .recipe import load_recipe, resolve_recipe_path
from .registry import DIAGRAM_API_VERSION, get_diagram
from .style_contract import BUILTIN_STYLE_DEFAULTS
from .reports import (
    REPORT_SCHEMA_NAME,
    REPORT_SCHEMA_VERSION,
    ReportError,
    build_report,
    render_qa_markdown,
    validate_report,
)
from .version import VERSION


PLAN_SCHEMA_VERSION = "geoskills.plan/v1"
CLI_REPORT_SCHEMA_VERSION = "geoskills.cli-report/v1"
MAX_PLAN_BYTES = 2 * 1024 * 1024
_PLAN_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PLAN_STATUSES = frozenset({"ready", "needs_confirmation", "blocked"})

_SKILL_ROOT = Path(__file__).resolve().parents[2]
_ASSET_PATHS = {
    "chondrite-sm89": "assets/normalization/chondrite-sm89.json",
    "pm-sm89": "assets/normalization/primitive-mantle-sm89.json",
    "pm-sm89-modified": (
        "assets/normalization/primitive-mantle-modified-sm89.json"
    ),
    "nmorb-sm89": "assets/normalization/nmorb-sm89.json",
    "tas-lemaitre-2002": "assets/classification/tas-lemaitre-2002.json",
    "k2o-sio2-pt76-r89-original": (
        "assets/classification/k2o-sio2-pt76-r89-original.json"
    ),
}
_BUILTIN_STYLE_DEFAULTS = BUILTIN_STYLE_DEFAULTS
_DIAGRAM_STYLE_DEFAULTS: Mapping[str, Mapping[str, Any]] = {
    "ree": {
        "axes_frame": "full",
        "legend_layout": "inside-auto",
        "grid_style": "none",
        "y_margin": 0.08,
    },
    "spider": {
        "axes_frame": "full",
        "legend_layout": "inside-auto",
        "grid_style": "none",
        "y_margin": 0.08,
    },
    "harker": {
        "axes_frame": "full",
        "margin_fraction": 0.06,
    },
    "tas": {"legend_layout": "inside-auto"},
    "k2o-sio2": {"legend_layout": "inside-auto"},
    "xy": {
        "axes_frame": "full",
        "legend_layout": "inside-auto",
        "margin_fraction": 0.06,
    },
}


class WorkflowError(GeoSkillsError):
    """An expected plan or run failure."""

    default_code = "E800"


def _issue(
    code: str,
    severity: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    result.update(extra)
    return result


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _write_json_atomic(
    path: Path,
    value: Mapping[str, Any],
    *,
    overwrite: bool,
) -> None:
    destination = Path(path)
    if destination.exists():
        if not overwrite:
            raise WorkflowError(
                "计划文件已经存在；如需替换，请明确使用 --overwrite-plan。",
                code="E801",
                details={"filename": destination.name},
            )
        try:
            _load_plan(destination)
        except WorkflowError as exc:
            raise WorkflowError(
                "仅允许覆盖由 GeoSkills 创建的有效计划文件。",
                code="E821",
                details={"filename": destination.name},
            ) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=".geoskills-plan-",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_plan(path: Path) -> dict[str, Any]:
    plan_path = Path(path)
    if not plan_path.exists() or not plan_path.is_file():
        raise WorkflowError(
            "找不到计划文件。",
            code="E802",
            details={"filename": plan_path.name or "plan"},
        )
    if plan_path.stat().st_size > MAX_PLAN_BYTES:
        raise WorkflowError(
            "计划文件超过安全大小限制。",
            code="E803",
            details={"filename": plan_path.name},
        )
    try:
        document = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(
            "计划文件不是有效的 UTF-8 JSON。",
            code="E804",
            details={"filename": plan_path.name},
        ) from exc
    if not isinstance(document, dict):
        raise WorkflowError("计划文件顶层必须是对象。", code="E805")
    if document.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise WorkflowError(
            f"计划格式必须是 {PLAN_SCHEMA_VERSION}。",
            code="E806",
        )
    if not isinstance(document.get("tasks"), list):
        raise WorkflowError("计划文件缺少任务列表。", code="E807")
    if document.get("status") not in _PLAN_STATUSES:
        raise WorkflowError("计划文件 status 无效。", code="E807")
    plan_id = document.get("plan_id")
    if not isinstance(plan_id, str) or _PLAN_ID_PATTERN.fullmatch(plan_id) is None:
        raise WorkflowError("计划文件 plan_id 无效。", code="E807")
    tasks = document["tasks"]
    if not tasks:
        raise WorkflowError("计划文件任务列表不能为空。", code="E807")
    task_ids: list[str] = []
    for item in tasks:
        if not isinstance(item, dict):
            raise WorkflowError("计划文件任务必须是对象。", code="E807")
        task_id = item.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise WorkflowError("计划文件任务缺少有效 ID。", code="E807")
        task_ids.append(task_id.casefold())
    if len(task_ids) != len(set(task_ids)):
        raise WorkflowError("计划文件任务 ID 不能重复。", code="E807")
    return document


def _asset_ids(task: Mapping[str, Any]) -> tuple[str, ...]:
    diagram = str(task["diagram"])
    if diagram in {"ree", "spider"}:
        return (str(task["parameters"]["reference"]),)
    if diagram == "tas":
        return ("tas-lemaitre-2002",)
    if diagram == "k2o-sio2":
        return ("k2o-sio2-pt76-r89-original",)
    return ()


def _asset_records(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for asset_id in _asset_ids(task):
        relative = _ASSET_PATHS[asset_id]
        path = _SKILL_ROOT / relative
        if not path.is_file():
            raise WorkflowError(
                "内置科学参考文件缺失，已停止任务。",
                code="E808",
                details={"asset_id": asset_id, "filename": path.name},
            )
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorkflowError(
                "内置科学参考文件无法读取，已停止任务。",
                code="E818",
                details={"asset_id": asset_id, "filename": path.name},
            ) from exc
        source = document.get("source", {})
        record: dict[str, Any] = {
            "id": asset_id,
            "asset_id": str(document.get("id", asset_id)),
            "display_name": str(document.get("display_name", asset_id)),
            "asset_schema_version": str(
                document.get("schema_version", "unknown")
            ),
            "filename": path.name,
            "sha256": sha256_file(path),
        }
        if document.get("unit") is not None:
            record["unit"] = str(document["unit"])
        for key in (
            "doi",
            "geometry_doi",
            "table",
            "classification_doi",
            "boundary_doi",
        ):
            if source.get(key) is not None:
                record[key] = str(source[key])
        records.append(record)
    return records


def _expanded_style(
    task: Mapping[str, Any],
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    preset_name = str(task["preset"])
    custom = recipe.get("presets", {}).get(preset_name)
    if custom is None:
        base_name = preset_name
        overrides: Mapping[str, Any] = {}
    else:
        base_name = str(custom["extends"])
        overrides = custom["style"]
    try:
        style = dict(_BUILTIN_STYLE_DEFAULTS[base_name])
    except KeyError as exc:
        raise WorkflowError("绘图预设不在固定注册表中。", code="E809") from exc
    style.update(dict(overrides))
    style.update(_DIAGRAM_STYLE_DEFAULTS[str(task["diagram"])])
    if str(task["diagram"]) in {"ree", "spider"}:
        style["show_sample_ids"] = (
            recipe["output"]["report_profile"] != "shareable"
        )
    style["preset"] = preset_name
    style["base_preset"] = base_name
    return style


def _selected_tasks(
    recipe: Mapping[str, Any],
    selected_task_ids: Sequence[str] | None,
) -> list[dict[str, Any]]:
    all_tasks = list(recipe["tasks"])
    if selected_task_ids is None:
        return [deepcopy(task) for task in all_tasks]
    requested = [str(item) for item in selected_task_ids]
    if not requested:
        raise WorkflowError("至少需要选择一个任务。", code="E810")
    if len(set(requested)) != len(requested):
        raise WorkflowError("任务选择不能重复。", code="E811")
    by_id = {str(task["id"]): task for task in all_tasks}
    missing = [task_id for task_id in requested if task_id not in by_id]
    if missing:
        raise WorkflowError(
            "所选任务不存在。",
            code="E812",
            details={"task_ids": missing},
        )
    requested_set = set(requested)
    return [
        deepcopy(task)
        for task in all_tasks
        if str(task["id"]) in requested_set
    ]


def _confirmation_issues(
    recipe: Mapping[str, Any],
    tasks: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for name, confirmed in recipe["confirmations"].items():
        if confirmed is not True:
            issues.append(
                _issue(
                    "R801",
                    "review",
                    "运行前需要完成数据确认。",
                    field=f"confirmations.{name}",
                    suggested_action="核对对应内容后，将该项明确改为 true。",
                )
            )
    for task in tasks:
        task_id = str(task["id"])
        for name, confirmed in task.get("confirmations", {}).items():
            if confirmed is not True:
                issues.append(
                    _issue(
                        "R802",
                        "review",
                        "运行前需要完成任务专属科学确认。",
                        task_id=task_id,
                        field=f"tasks[{task_id}].confirmations.{name}",
                        suggested_action="完成专业复核后，将该项明确改为 true。",
                    )
                )
    return issues


def _expected_outputs(
    task: Mapping[str, Any],
    report_profile: str,
) -> list[str]:
    task_id = str(task["id"])
    stem = str(task["stem"])
    filenames = [
        *(f"{stem}.{extension}" for extension in ("svg", "pdf", "tiff", "png")),
        f"{stem}.report.json",
        f"{stem}.qa.md",
    ]
    if report_profile == "local-reproducible":
        filenames.insert(4, f"{stem}.source_data.csv")
    return [f"{task_id}/{filename}" for filename in filenames]


def _mapping_snapshot(prepared: PreparedInput) -> list[dict[str, str]]:
    return [
        {
            "source_column": mapping.source_column,
            "canonical_analyte": mapping.canonical_analyte,
            "unit": mapping.unit,
        }
        for mapping in prepared.mappings
    ]


def _shareable_source(source: Mapping[str, Any]) -> dict[str, Any]:
    """Return source provenance without user-identifying file metadata."""

    return {
        str(key): deepcopy(value)
        for key, value in source.items()
        if str(key) not in {"filename", "sheet", "sheet_names"}
    }


def _shareable_mapping(
    mapping: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    """Keep scientific mapping semantics without private source headers."""

    return [
        {
            str(key): str(value)
            for key, value in item.items()
            if str(key) != "source_column"
        }
        for item in mapping
    ]


def _shareable_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Replace selected group values with a deterministic count-only digest."""

    result = deepcopy(dict(parameters))
    groups = result.get("groups")
    if isinstance(groups, list):
        group_values = [str(value) for value in groups]
        result["groups"] = {
            "selection_mode": "selected",
            "selected_group_count": len(group_values),
            "selection_sha256": _digest_json(group_values),
        }
    return result


def _shareable_issue(
    issue: Mapping[str, Any],
    *,
    sensitive_tokens: Sequence[str],
) -> dict[str, Any]:
    """Keep actionable issue fields while removing private diagnostic payloads."""

    result = {
        str(key): deepcopy(value)
        for key, value in issue.items()
        if str(key)
        in {
            "code",
            "severity",
            "message",
            "field",
            "suggested_action",
            "task_id",
            "asset_id",
        }
    }
    tokens = sorted(
        {str(value) for value in sensitive_tokens if str(value)},
        key=len,
        reverse=True,
    )
    for key, value in list(result.items()):
        if not isinstance(value, str):
            continue
        redacted = value
        for token in tokens:
            redacted = redacted.replace(token, "<redacted>")
        result[key] = redacted
    return result


def _task_records(
    *,
    tasks: Sequence[Mapping[str, Any]],
    assets: Mapping[str, list[dict[str, Any]]],
    inspections: Mapping[str, Mapping[str, Any]],
    report_profile: str,
    shareable: bool,
    sensitive_tokens: Sequence[str] = (),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task["id"])
        parameters = (
            _shareable_parameters(task["parameters"])
            if shareable
            else deepcopy(task["parameters"])
        )
        inspection = deepcopy(inspections[task_id])
        if shareable and isinstance(inspection.get("issues"), list):
            inspection["issues"] = [
                _shareable_issue(item, sensitive_tokens=sensitive_tokens)
                for item in inspection["issues"]
                if isinstance(item, Mapping)
            ]
        records.append(
            {
                "id": task_id,
                "diagram": task["diagram"],
                "stem": task["stem"],
                "preset": task["preset"],
                "parameters": parameters,
                "confirmations": deepcopy(task["confirmations"]),
                "style": deepcopy(task["style"]),
                "registry_contract": get_diagram(
                    str(task["diagram"])
                ).to_dict(),
                "inspection": inspection,
                "assets": deepcopy(assets[task_id]),
                "expected_outputs": _expected_outputs(task, report_profile),
            }
        )
    return records


def _recipe_member_paths(
    recipe_path: str | Path,
    recipe: Mapping[str, Any],
) -> tuple[Path, Path, list[dict[str, Any]]]:
    """Resolve source/output members and flag destructive overlap."""

    try:
        source_path = resolve_recipe_path(
            recipe_path, str(recipe["input"]["file"])
        )
        output_path = resolve_recipe_path(
            recipe_path, str(recipe["output"]["directory"])
        )
    except ValueError as exc:
        raise WorkflowError(
            "配方成员解析后超出配方目录，已停止操作。",
            code="E820",
        ) from exc
    issues: list[dict[str, Any]] = []
    recipe_root = Path(recipe_path).resolve().parent
    lexical_source = Path(
        os.path.abspath(
            recipe_root / Path(str(recipe["input"]["file"]))
        )
    )
    lexical_output = Path(
        os.path.abspath(
            recipe_root / Path(str(recipe["output"]["directory"]))
        )
    )
    source_in_output = False
    for candidate_source, candidate_output in (
        (source_path, output_path),
        (lexical_source, lexical_output),
    ):
        try:
            candidate_source.relative_to(candidate_output)
        except ValueError:
            continue
        source_in_output = True
        break
    if source_in_output:
        issues.append(
            _issue(
                "E820",
                "error",
                "输出目录不能包含原始输入文件；否则覆盖运行可能删除源数据。",
                field="output.directory",
                suggested_action="选择与输入文件分离的专用输出子目录。",
            )
        )
    return source_path, output_path, issues


def _finalize_plan(
    *,
    recipe: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    assets: Mapping[str, list[dict[str, Any]]],
    inspections: Mapping[str, Mapping[str, Any]],
    mapping: Sequence[Mapping[str, str]],
    source: Mapping[str, Any],
    quality: Mapping[str, Any],
    derived: Mapping[str, Any],
    basis: Mapping[str, Any],
    preflight_issues: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the deterministic plan from one already-read data snapshot."""

    confirmation_issues = _confirmation_issues(recipe, tasks)
    processing_issues = [
        dict(issue)
        for summary in (quality, derived, basis)
        for issue in summary.get("issues", [])
        if isinstance(issue, Mapping)
    ]
    processing_review_required = any(
        issue.get("severity") == "review" for issue in processing_issues
    )
    if (
        processing_review_required
        and recipe["confirmations"].get("data_quality_reviewed") is not True
        and not any(
            item.get("field") == "confirmations.data_quality_reviewed"
            for item in confirmation_issues
        )
    ):
        confirmation_issues.append(
            _issue(
                "R805",
                "review",
                "数据质控或派生变量存在需要人工复核的状态。",
                field="confirmations.data_quality_reviewed",
                suggested_action="复核计数摘要后，在配方中明确设置 data_quality_reviewed: true。",
            )
        )
    inspection_issues = [
        issue
        for task in tasks
        for issue in inspections[str(task["id"])]["issues"]
    ]
    blocked = (
        bool(preflight_issues)
        or any(issue.get("severity") == "error" for issue in processing_issues)
        or any(
            inspections[str(task["id"])]["status"] != "ready"
            for task in tasks
        )
    )
    status = (
        "blocked"
        if blocked
        else ("needs_confirmation" if confirmation_issues else "ready")
    )
    issues = [
        *[dict(item) for item in preflight_issues],
        *confirmation_issues,
        *processing_issues,
        *inspection_issues,
    ]
    data_processing = {
        "quality": {
            "policy": deepcopy(recipe["quality"]),
            "summary": deepcopy(dict(quality)),
        },
        "derived_variables": {
            "definitions": deepcopy(recipe["derived_variables"]),
            "summary": deepcopy(dict(derived)),
        },
        "data_basis": {
            "definition": deepcopy(recipe.get("data_basis")),
            "summary": deepcopy(dict(basis)),
        },
    }
    report_profile = str(recipe["output"]["report_profile"])
    sensitive_tokens = [
        str(recipe["input"].get("file", "")),
        Path(str(recipe["input"].get("file", ""))).name,
        str(recipe["input"].get("sheet") or ""),
        str(source.get("filename", "")),
        str(source.get("sheet", "")),
        *[
            str(group)
            for task in tasks
            for group in (
                task.get("parameters", {}).get("groups", [])
                if isinstance(task.get("parameters", {}).get("groups"), list)
                else []
            )
        ],
    ]
    exact_task_records = _task_records(
        tasks=tasks,
        assets=assets,
        inspections=inspections,
        report_profile=report_profile,
        shareable=False,
    )
    public_task_records = _task_records(
        tasks=tasks,
        assets=assets,
        inspections=inspections,
        report_profile=report_profile,
        shareable=True,
        sensitive_tokens=sensitive_tokens,
    )
    public_issues = [
        _shareable_issue(item, sensitive_tokens=sensitive_tokens)
        for item in issues
    ]

    plan_basis = {
        "tool_version": VERSION,
        "diagram_api_version": DIAGRAM_API_VERSION,
        "recipe": {
            "schema_version": recipe["schema_version"],
            "input": recipe["input"],
            "columns": recipe["columns"],
            "quality": recipe["quality"],
            "derived_variables": recipe["derived_variables"],
            "data_basis": recipe.get("data_basis"),
            "output": recipe["output"],
            "presets": recipe["presets"],
            "confirmations": recipe["confirmations"],
        },
        "input": dict(source),
        "column_mapping": [dict(item) for item in mapping],
        "data_processing": data_processing,
        "tasks": exact_task_records,
    }
    plan_id = _digest_json(plan_basis)
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "status": status,
        "tool": {
            "name": "GeoSkills",
            "version": VERSION,
            "diagram_api_version": DIAGRAM_API_VERSION,
        },
        "input": _shareable_source(source),
        "column_mapping": _shareable_mapping(mapping),
        "data_processing": data_processing,
        "output": recipe["output"],
        "confirmations": recipe["confirmations"],
        "tasks": public_task_records,
        "issues": public_issues,
    }
    return {"status": status, "plan": plan, "issues": public_issues}


def build_plan(
    recipe_path: str | Path,
    *,
    selected_task_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate a recipe and input, but never create final figure outputs."""

    source_path = Path(recipe_path)
    loaded = load_recipe(source_path)
    if loaded["status"] == "invalid" or loaded["recipe"] is None:
        return {
            "status": "error",
            "plan": None,
            "issues": loaded["issues"],
        }
    recipe = loaded["recipe"]
    try:
        tasks = _selected_tasks(recipe, selected_task_ids)
        for task in tasks:
            task["style"] = _expanded_style(task, recipe)
        assets = {
            str(task["id"]): _asset_records(task) for task in tasks
        }
    except GeoSkillsError as exc:
        return {
            "status": "error",
            "plan": None,
            "issues": [exc.to_issue()],
        }

    try:
        _, _, preflight_issues = _recipe_member_paths(source_path, recipe)
    except GeoSkillsError as exc:
        return {
            "status": "error",
            "plan": None,
            "issues": [exc.to_issue()],
        }
    try:
        with tempfile.TemporaryDirectory(prefix="geoskills-plan-") as directory:
            prepared = prepare_mapped_input(
                recipe,
                recipe_path=source_path,
                work_dir=Path(directory),
            )
            inspections = {
                str(task["id"]): inspect_task(task, prepared)
                for task in tasks
            }
            mapping = _mapping_snapshot(prepared)
            source = prepared.source
            quality = prepared.quality
            derived = prepared.derived
            basis = prepared.basis
    except GeoSkillsError as exc:
        safe_issue = exc.to_issue()
        preflight_issues.append(safe_issue)
        source = {
            "filename": Path(str(recipe["input"]["file"])).name,
            "format": Path(str(recipe["input"]["file"])).suffix.lower(),
        }
        mapping = []
        quality = {}
        derived = {}
        basis = {}
        inspections = {
            str(task["id"]): {
                "task_id": str(task["id"]),
                "diagram": str(task["diagram"]),
                "status": "blocked",
                "recognized_analytes": [],
                "issues": [],
            }
            for task in tasks
        }
    except (OSError, ValueError):
        return {
            "status": "error",
            "plan": None,
            "issues": [
                _issue(
                    "E899",
                    "error",
                    "读取或检查配方输入时发生未预期错误。",
                )
            ],
        }

    return _finalize_plan(
        recipe=recipe,
        tasks=tasks,
        assets=assets,
        inspections=inspections,
        mapping=mapping,
        source=source,
        quality=quality,
        derived=derived,
        basis=basis,
        preflight_issues=preflight_issues,
    )


def create_plan(
    recipe_path: str | Path,
    plan_path: str | Path,
    *,
    selected_task_ids: Sequence[str] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Build and atomically save a privacy-safe execution plan."""

    result = build_plan(
        recipe_path,
        selected_task_ids=selected_task_ids,
    )
    plan = result.get("plan")
    if plan is not None:
        try:
            loaded = load_recipe(recipe_path)
            recipe = loaded.get("recipe")
            if recipe is None:
                raise WorkflowError(
                    "写入计划前配方复核失败。",
                    code="E822",
                )
            input_path, output_path, _ = _recipe_member_paths(
                recipe_path, recipe
            )
            destination_path = Path(plan_path)
            destination = destination_path.resolve()
            lexical_destination = Path(os.path.abspath(destination_path))
            protected = {
                Path(recipe_path).resolve(),
                input_path.resolve(),
                Path(os.path.abspath(Path(recipe_path))),
                Path(os.path.abspath(input_path)),
            }
            if (
                destination in protected
                or lexical_destination in protected
                or _path_is_within(destination_path, output_path)
            ):
                raise WorkflowError(
                    "计划文件不能覆盖配方、原始输入，也不能放在最终输出目录内。",
                    code="E822",
                    details={"filename": destination.name or "plan"},
                )
            _write_json_atomic(Path(plan_path), plan, overwrite=overwrite)
        except GeoSkillsError as exc:
            return {
                "status": "error",
                "plan": None,
                "issues": [exc.to_issue()],
            }
    return {
        "status": result["status"],
        "plan_id": None if plan is None else plan["plan_id"],
        "plan_file": None if plan is None else Path(plan_path).name,
        "issues": result["issues"],
    }


def _safe_run_issues(report: Mapping[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for item in report.get("issues", []):
        severity = str(item.get("severity", "review"))
        if severity not in {"info", "warning", "review", "error"}:
            severity = "review"
        results.append(
            {
                "code": str(item.get("code", "R899")),
                "severity": severity,
                "message": str(item.get("message", "需要人工复核。")),
            }
        )
    return results


def _safe_plot_summary(
    diagram: str,
    legacy_report: Mapping[str, Any],
) -> dict[str, Any]:
    plot = legacy_report.get("plot", {})
    if not isinstance(plot, Mapping):
        return {}
    common = {
        "sample_count",
        "group_count",
        "palette_repeated",
        "marker_repeated",
        "axes_frame",
        "legend_position",
    }
    diagram_fields = {
        "ree": {
            "normalization_id",
            "y_limits",
            "unity_line_visible",
            "plotted_sample_count",
            "legend_sample_count",
            "sample_ids_rendered",
            "group_legend_title",
            "line_style_repeated",
            "grid_style",
            "legend_fallback",
            "legend_collision_free",
            "inside_legend_strategy",
        },
        "spider": {
            "normalization_id",
            "y_limits",
            "unity_line_visible",
            "plotted_sample_count",
            "line_style_repeated",
            "grid_style",
            "legend_fallback",
            "legend_collision_free",
            "inside_legend_strategy",
        },
        "harker": {
            "panel_count",
            "rows",
            "columns",
            "x_limits",
            "legend_columns",
            "legend_rows",
            "legend_within_figure",
            "shared_x_label",
        },
        "tas": {
            "classification_status_counts",
            "field_counts",
            "x_limits",
            "y_limits",
            "legend_fallback",
        },
        "k2o-sio2": {
            "classification_status_counts",
            "field_counts",
            "x_limits",
            "y_limits",
            "complete_domain_x",
            "visible_coordinate_count",
            "outside_axes_count",
            "legend_fallback",
        },
        "xy": {
            "joint_valid_count",
            "x_scale",
            "y_scale",
            "sample_labels_rendered",
        },
    }
    allowed = common | diagram_fields.get(diagram, set())

    def without_exact_source_extrema(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): without_exact_source_extrema(item)
                for key, item in value.items()
                if str(key).casefold()
                not in {
                    "data_min",
                    "data_max",
                    "raw_min",
                    "raw_max",
                    "observed_min",
                    "observed_max",
                    "source_min",
                    "source_max",
                }
            }
        if isinstance(value, (list, tuple)):
            return [
                without_exact_source_extrema(item) for item in value
            ]
        return deepcopy(value)

    return {
        str(key): without_exact_source_extrema(value)
        for key, value in plot.items()
        if key in allowed
    }


def _safe_scientific_details(
    task: Mapping[str, Any],
    prepared: PreparedInput,
    legacy_report: Mapping[str, Any],
    *,
    plan_id: str,
    report_profile: str,
) -> dict[str, Any]:
    diagram = str(task["diagram"])
    details: dict[str, Any] = {
        "task_id": str(task["id"]),
        "diagram": diagram,
        "plan_id": plan_id,
        "scientific_parameters": _shareable_parameters(task["parameters"]),
        "scientific_confirmations": deepcopy(task["confirmations"]),
        "analyte_units": {
            mapping.canonical_analyte: mapping.unit
            for mapping in prepared.mappings
        },
        "style": deepcopy(task["style"]),
        "reference_assets": deepcopy(task["assets"]),
        "report_profile": report_profile,
        "data_processing": {
            "quality": deepcopy(prepared.quality),
            "derived_variables": deepcopy(prepared.derived),
            "data_basis": deepcopy(prepared.basis),
        },
        "plot_summary": _safe_plot_summary(diagram, legacy_report),
    }
    conversions = legacy_report.get("oxide_conversions")
    if isinstance(conversions, list) and conversions:
        details["oxide_conversions"] = [
            {
                str(key): deepcopy(value)
                for key, value in conversion.items()
                if str(key) != "source_column"
            }
            for conversion in conversions
            if isinstance(conversion, Mapping)
        ]
    guidance = legacy_report.get("interpretation_guidance")
    if isinstance(guidance, list):
        details["interpretation_guidance"] = [
            str(item) for item in guidance
        ]
    caveat = legacy_report.get("scientific_caveat")
    if isinstance(caveat, str) and caveat.strip():
        details["scientific_caveat"] = caveat.strip()
    return details


def _task_directory_files(task_dir: Path, *, task_id: str) -> set[str]:
    if task_dir.is_symlink() or not task_dir.is_dir():
        raise WorkflowError(
            "绘图任务输出必须是普通目录。",
            code="E823",
            details={"task_id": task_id},
        )
    names: set[str] = set()
    for entry in task_dir.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise WorkflowError(
                "绘图任务生成了未经允许的目录或链接。",
                code="E823",
                details={"task_id": task_id, "filename": entry.name},
            )
        names.add(entry.name)
    return names


def _verify_figure_bundle(
    figure_paths: Sequence[Path],
    *,
    width_mm: float,
    height_mm: float,
    dpi: int,
    task_id: str,
) -> dict[str, Any]:
    """Verify that every claimed publication artifact is genuinely readable."""

    by_suffix = {path.suffix.lower(): path for path in figure_paths}
    expected_pixels = (
        round(float(width_mm) / 25.4 * int(dpi)),
        round(float(height_mm) / 25.4 * int(dpi)),
    )
    try:
        svg_root = ET.parse(by_suffix[".svg"]).getroot()
        if not svg_root.tag.casefold().endswith("svg"):
            raise ValueError("not-svg")
        svg_text_nodes = [
            node
            for node in svg_root.iter()
            if node.tag.casefold().endswith("text")
        ]
        if not svg_text_nodes:
            raise ValueError("svg-text-not-editable")

        pdf_bytes = by_suffix[".pdf"].read_bytes()
        if (
            not pdf_bytes.startswith(b"%PDF-")
            or not pdf_bytes.rstrip().endswith(b"%%EOF")
            or (
                b"/CIDFontType2" not in pdf_bytes
                and b"/FontFile2" not in pdf_bytes
            )
        ):
            raise ValueError("invalid-pdf-or-font")

        raster_details: dict[str, dict[str, Any]] = {}
        for suffix, expected_format in ((".png", "PNG"), (".tiff", "TIFF")):
            path = by_suffix[suffix]
            with Image.open(path) as image:
                if image.format != expected_format:
                    raise ValueError(f"wrong-{expected_format.lower()}-format")
                image.verify()
            with Image.open(path) as image:
                size = tuple(int(value) for value in image.size)
                if any(
                    abs(actual - expected) > 3
                    for actual, expected in zip(size, expected_pixels)
                ):
                    raise ValueError(f"wrong-{expected_format.lower()}-size")
                dpi_value = image.info.get("dpi", (0.0, 0.0))
                if not isinstance(dpi_value, tuple) or len(dpi_value) < 2:
                    raise ValueError(f"missing-{expected_format.lower()}-dpi")
                dpi_pair = tuple(float(value) for value in dpi_value[:2])
                if any(abs(value - int(dpi)) > 2.0 for value in dpi_pair):
                    raise ValueError(f"wrong-{expected_format.lower()}-dpi")
                rgba = image.convert("RGBA")
                corners = [
                    rgba.getpixel((0, 0)),
                    rgba.getpixel((size[0] - 1, 0)),
                    rgba.getpixel((0, size[1] - 1)),
                    rgba.getpixel((size[0] - 1, size[1] - 1)),
                ]
                if any(
                    pixel[3] != 255
                    or any(channel < 250 for channel in pixel[:3])
                    for pixel in corners
                ):
                    raise ValueError(
                        f"nonwhite-{expected_format.lower()}-background"
                    )
                compression = None
                if suffix == ".tiff":
                    compression = int(image.tag_v2.get(259, 0))
                    if compression != 5:
                        raise ValueError("tiff-not-lzw")
                raster_details[suffix.lstrip(".")] = {
                    "pixels": list(size),
                    "dpi": [round(value, 3) for value in dpi_pair],
                    **(
                        {"compression_tag": compression}
                        if compression is not None
                        else {}
                    ),
                }
    except (
        ET.ParseError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise WorkflowError(
            "图件包未通过格式、尺寸或可编辑性验证，完整输出已取消。",
            code="E824",
            details={
                "task_id": task_id,
                "reason_code": type(exc).__name__,
            },
        ) from exc

    return {
        "complete_figure_bundle": True,
        "figure_formats": ["svg", "pdf", "tiff", "png"],
        "final_size_mm": [float(width_mm), float(height_mm)],
        "svg_text_editable": True,
        "pdf_embedded_truetype_font": True,
        "raster_dpi": int(dpi),
        "raster_files": raster_details,
        "tiff_compression": "LZW",
        "white_background": True,
    }


def _write_task_reports(
    *,
    task: Mapping[str, Any],
    task_dir: Path,
    staging_root: Path,
    prepared: PreparedInput,
    legacy_report: Mapping[str, Any],
    plan_id: str,
    report_profile: str,
) -> tuple[Path, Path, str]:
    stem = str(task["stem"])
    task_id = str(task["id"])
    legacy_report_path = task_dir / f"{stem}.report.json"
    source_data_path = task_dir / f"{stem}.source_data.csv"
    legacy_allowed = {
        *(f"{stem}.{extension}" for extension in ("svg", "pdf", "tiff", "png")),
        f"{stem}.source_data.csv",
        f"{stem}.report.json",
    }
    unexpected_legacy = sorted(
        _task_directory_files(task_dir, task_id=task_id) - legacy_allowed
    )
    if unexpected_legacy:
        raise WorkflowError(
            "绘图器生成了不在固定合同中的额外文件，完整输出已取消。",
            code="E823",
            details={"task_id": task_id, "filenames": unexpected_legacy},
        )
    if legacy_report_path.exists():
        legacy_report_path.unlink()
    if report_profile == "shareable" and source_data_path.exists():
        source_data_path.unlink()

    figure_paths = [
        task_dir / f"{stem}.{extension}"
        for extension in ("svg", "pdf", "tiff", "png")
    ]
    missing = [path.name for path in figure_paths if not path.is_file()]
    if missing:
        raise WorkflowError(
            "绘图器未生成完整图件包。",
            code="E813",
            details={"task_id": str(task["id"]), "filenames": missing},
        )
    figure_qa = _verify_figure_bundle(
        figure_paths,
        width_mm=float(task["style"]["width_mm"]),
        height_mm=float(task["style"]["height_mm"]),
        dpi=int(task["style"]["dpi"]),
        task_id=task_id,
    )
    output_paths = list(figure_paths)
    if report_profile == "local-reproducible":
        if not source_data_path.is_file():
            raise WorkflowError(
                "本地可复现模式缺少绘图源数据导出。",
                code="E814",
                details={"task_id": str(task["id"])},
            )
        output_paths.append(source_data_path)
    output_records = [
        shareable_file_record(
            path,
            bundle_root=staging_root,
            role=(
                "plotted-source-sensitive"
                if path.suffix.lower() == ".csv"
                else "figure"
            ),
        )
        for path in output_paths
    ]
    issues = [
        *_safe_run_issues(legacy_report),
        *_safe_run_issues({"issues": prepared.quality.get("issues", [])}),
        *_safe_run_issues({"issues": prepared.derived.get("issues", [])}),
        *_safe_run_issues({"issues": prepared.basis.get("issues", [])}),
    ]
    tas_review_codes = {"W711", "W712", "W713", "W714", "W715"}
    k2o_review_codes = {"W811", "W812", "W813", "W814", "W815"}
    review_required = any(
        issue["severity"] in {"review", "error"}
        or (
            str(task["diagram"]) == "tas"
            and issue["code"] in tas_review_codes
        )
        or (
            str(task["diagram"]) == "k2o-sio2"
            and issue["code"] in k2o_review_codes
        )
        for issue in issues
    )
    report = build_report(
        operation=get_diagram(str(task["diagram"])).operation,
        status="review" if review_required else "ready",
        source=prepared.source,
        outputs=output_records,
        issues=issues,
        qa={
            **figure_qa,
            "source_export": (
                "included-sensitive"
                if report_profile == "local-reproducible"
                else "omitted-shareable"
            ),
        },
        next_actions=(
            ["请完成人工科学审核后再用于论文解释。"]
            if review_required
            else ["请在投稿前核对图例、标签和科学解释。"]
        ),
        review_required=review_required,
        details=_safe_scientific_details(
            task,
            prepared,
            legacy_report,
            plan_id=plan_id,
            report_profile=report_profile,
        ),
        shareable=True,
    )
    report_path = task_dir / f"{stem}.report.json"
    qa_path = task_dir / f"{stem}.qa.md"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    qa_path.write_text(render_qa_markdown(report), encoding="utf-8")
    expected_final = {
        Path(value).name for value in task["expected_outputs"]
    }
    actual_final = _task_directory_files(task_dir, task_id=task_id)
    if actual_final != expected_final:
        raise WorkflowError(
            "任务最终文件集合与已审核计划不一致，完整输出已取消。",
            code="E823",
            details={
                "task_id": task_id,
                "missing": sorted(expected_final - actual_final),
                "unexpected": sorted(actual_final - expected_final),
            },
        )
    return report_path, qa_path, str(report["status"])


def _verified_remove_work_dir(work_dir: Path, staging_root: Path) -> None:
    resolved_work = work_dir.resolve()
    resolved_stage = staging_root.resolve()
    if (
        resolved_work.parent != resolved_stage
        or resolved_work.name != "_work"
    ):
        raise WorkflowError("拒绝清理未经验证的临时目录。", code="E815")
    if resolved_work.exists():
        shutil.rmtree(resolved_work)


def _path_is_within(path: Path, directory: Path) -> bool:
    candidates = (
        (path.resolve(), directory.resolve()),
        (
            Path(os.path.abspath(path)),
            Path(os.path.abspath(directory)),
        ),
    )
    for candidate_path, candidate_directory in candidates:
        try:
            candidate_path.relative_to(candidate_directory)
        except ValueError:
            continue
        return True
    return False


def _existing_output_issue(
    target: Path,
    *,
    overwrite: bool,
) -> dict[str, Any] | None:
    if not target.exists():
        return None
    if not overwrite:
        return _issue(
            "E825",
            "review",
            "完整输出目录已经存在；尚未执行任何绘图。",
            suggested_action="审核旧输出后，明确使用 --overwrite。",
        )
    if target.is_symlink() or not target.is_dir():
        return _issue(
            "E826",
            "error",
            "仅允许覆盖普通的 GeoSkills 输出目录。",
        )
    marker = target / "run.report.json"
    try:
        if (
            not marker.is_file()
            or marker.is_symlink()
            or marker.stat().st_size > MAX_PLAN_BYTES
        ):
            raise ValueError("missing-or-unsafe-marker")
        document = json.loads(marker.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("invalid-marker")
        validate_report(document, require_shareable=True)
        if (
            document.get("schema")
            != {
                "name": REPORT_SCHEMA_NAME,
                "version": REPORT_SCHEMA_VERSION,
            }
            or document.get("operation")
            != "multi_task_geochemistry_workflow"
        ):
            raise ValueError("foreign-marker")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ReportError,
        ValueError,
    ):
        return _issue(
            "E826",
            "error",
            "现有目录不是可验证的 GeoSkills 完整输出；为保护文件，拒绝覆盖。",
            suggested_action="改用新的 output.directory，或先人工整理旧目录。",
        )
    return None


def _verify_run_directory(
    staging_root: Path,
    *,
    task_ids: Sequence[str],
) -> None:
    expected_files = {"run.report.json", "run.qa.md"}
    expected_directories = {str(value) for value in task_ids}
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for entry in staging_root.iterdir():
        if entry.is_symlink():
            raise WorkflowError(
                "完整输出包含未经允许的链接，已取消提交。",
                code="E823",
            )
        if entry.is_file():
            actual_files.add(entry.name)
        elif entry.is_dir():
            actual_directories.add(entry.name)
        else:
            raise WorkflowError(
                "完整输出包含不受支持的文件类型，已取消提交。",
                code="E823",
            )
    if (
        actual_files != expected_files
        or actual_directories != expected_directories
    ):
        raise WorkflowError(
            "完整输出目录与已审核计划不一致，已取消提交。",
            code="E823",
            details={
                "unexpected_files": sorted(actual_files - expected_files),
                "unexpected_directories": sorted(
                    actual_directories - expected_directories
                ),
            },
        )


def _verify_task_assets(task: Mapping[str, Any]) -> None:
    for record in task.get("assets", []):
        asset_id = str(record["id"])
        relative = _ASSET_PATHS.get(asset_id)
        if relative is None:
            raise WorkflowError(
                "计划引用了未知的内置科学参考。",
                code="E828",
                details={"asset_id": asset_id},
            )
        path = _SKILL_ROOT / relative
        if (
            not path.is_file()
            or sha256_file(path) != str(record["sha256"])
        ):
            raise WorkflowError(
                "内置科学参考在执行期间发生变化，完整输出已取消。",
                code="E828",
                details={"asset_id": asset_id},
            )


def execute_plan(
    recipe_path: str | Path,
    plan_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Revalidate a saved plan and atomically execute all selected tasks."""

    try:
        saved_plan = _load_plan(Path(plan_path))
        selected_ids = [str(task["id"]) for task in saved_plan["tasks"]]
        loaded = load_recipe(recipe_path)
        recipe = loaded.get("recipe")
        if recipe is None:
            return {
                "status": "error",
                "output_directory": None,
                "issues": loaded["issues"],
            }
        tasks = _selected_tasks(recipe, selected_ids)
        for task in tasks:
            task["style"] = _expanded_style(task, recipe)
        assets = {
            str(task["id"]): _asset_records(task) for task in tasks
        }
        _, target, path_issues = _recipe_member_paths(recipe_path, recipe)
        if path_issues:
            return {
                "status": "blocked",
                "output_directory": None,
                "issues": path_issues,
            }
        if _path_is_within(Path(plan_path), target):
            return {
                "status": "blocked",
                "output_directory": None,
                "issues": [
                    _issue(
                        "E822",
                        "error",
                        "计划文件不能位于最终输出目录内。",
                        suggested_action="把计划文件移到输出目录外并重新生成计划。",
                    )
                ],
            }
        output_issue = _existing_output_issue(target, overwrite=overwrite)
        if output_issue is not None:
            return {
                "status": "blocked",
                "output_directory": None,
                "issues": [output_issue],
            }
        report_profile = str(recipe["output"]["report_profile"])
        task_outputs: list[Path] = []
        task_summaries: list[dict[str, Any]] = []
        with AtomicDirectory(target, overwrite=overwrite) as transaction:
            staging_root = transaction.staging_dir
            work_dir = staging_root / "_work"
            prepared = prepare_mapped_input(
                recipe,
                recipe_path=Path(recipe_path),
                work_dir=work_dir,
            )
            inspections = {
                str(task["id"]): inspect_task(task, prepared)
                for task in tasks
            }
            current = _finalize_plan(
                recipe=recipe,
                tasks=tasks,
                assets=assets,
                inspections=inspections,
                mapping=_mapping_snapshot(prepared),
                source=prepared.source,
                quality=prepared.quality,
                derived=prepared.derived,
                basis=prepared.basis,
                preflight_issues=(),
            )
            current_plan = current["plan"]
            execution_tasks = _task_records(
                tasks=tasks,
                assets=assets,
                inspections=inspections,
                report_profile=report_profile,
                shareable=False,
            )
            if current_plan["plan_id"] != saved_plan["plan_id"]:
                return {
                    "status": "blocked",
                    "output_directory": None,
                    "issues": [
                        _issue(
                            "R803",
                            "review",
                            "配方、输入文件或内置参考已经变化；旧计划已失效。",
                            suggested_action="重新运行 plan，审核新计划后再运行。",
                        )
                    ],
                }
            if (
                saved_plan["status"] != "ready"
                or current["status"] != "ready"
            ):
                return {
                    "status": (
                        "needs_confirmation"
                        if current["status"] == "needs_confirmation"
                        else "blocked"
                    ),
                    "output_directory": None,
                    "issues": current["issues"],
                }
            for task in execution_tasks:
                task_dir = staging_root / str(task["id"])
                _verify_task_assets(task)
                legacy_report = run_task(
                    task,
                    prepared,
                    output_dir=task_dir,
                )
                _verify_task_assets(task)
                if legacy_report.get("status") != "ready":
                    raise WorkflowError(
                        "绘图任务未成功完成，完整输出已取消。",
                        code="E817",
                        details={
                            "task_id": str(task["id"]),
                            "issues": _safe_run_issues(legacy_report),
                        },
                    )
                report_path, qa_path, task_status = _write_task_reports(
                    task=task,
                    task_dir=task_dir,
                    staging_root=staging_root,
                    prepared=prepared,
                    legacy_report=legacy_report,
                    plan_id=str(current_plan["plan_id"]),
                    report_profile=report_profile,
                )
                task_files = sorted(
                    path for path in task_dir.iterdir() if path.is_file()
                )
                task_outputs.extend(task_files)
                task_summaries.append(
                    {
                        "task_id": str(task["id"]),
                        "diagram": str(task["diagram"]),
                        "report_filename": report_path.name,
                        "qa_filename": qa_path.name,
                        "status": task_status,
                    }
                )
            _verified_remove_work_dir(work_dir, staging_root)

            workflow_review = any(
                item["status"] == "review" for item in task_summaries
            )
            workflow_issues = [
                _issue(
                    "R804",
                    "review",
                    "该任务已生成图件，但包含必须人工复核的科学状态。",
                    task_id=str(item["task_id"]),
                )
                for item in task_summaries
                if item["status"] == "review"
            ]
            workflow_issues.extend(
                _safe_run_issues(
                    {"issues": prepared.quality.get("issues", [])}
                )
            )
            workflow_issues.extend(
                _safe_run_issues(
                    {"issues": prepared.derived.get("issues", [])}
                )
            )
            workflow_issues.extend(
                _safe_run_issues(
                    {"issues": prepared.basis.get("issues", [])}
                )
            )
            run_output_records = [
                shareable_file_record(
                    path,
                    bundle_root=staging_root,
                    role=(
                        "plotted-source-sensitive"
                        if path.suffix.lower() == ".csv"
                        else "task-output"
                    ),
                )
                for path in task_outputs
            ]
            run_report = build_report(
                operation="multi_task_geochemistry_workflow",
                status="review" if workflow_review else "ready",
                source=prepared.source,
                outputs=run_output_records,
                issues=workflow_issues,
                qa={
                    "atomic_directory_commit": True,
                    "task_count": len(task_summaries),
                    "all_tasks_completed": True,
                },
                next_actions=[
                    (
                        "请先解决任务报告中的科学复核状态，再用于投稿。"
                        if workflow_review
                        else "请审核各任务的 QA 摘要和图件后再用于投稿。"
                    )
                ],
                review_required=workflow_review,
                details={
                    "plan_id": str(current_plan["plan_id"]),
                    "report_profile": report_profile,
                    "data_confirmations": deepcopy(
                        current_plan["confirmations"]
                    ),
                    "data_processing": deepcopy(
                        current_plan["data_processing"]
                    ),
                    "task_summaries": task_summaries,
                },
                shareable=True,
            )
            run_report_path = staging_root / "run.report.json"
            run_qa_path = staging_root / "run.qa.md"
            run_report_path.write_text(
                json.dumps(
                    run_report,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            run_qa_path.write_text(
                render_qa_markdown(run_report),
                encoding="utf-8",
            )
            _verify_run_directory(
                staging_root,
                task_ids=[
                    str(task["id"]) for task in execution_tasks
                ],
            )
            transaction.commit()
        return {
            "status": "review" if workflow_review else "ready",
            "plan_id": saved_plan["plan_id"],
            "output_directory": str(recipe["output"]["directory"]),
            "task_count": len(task_summaries),
            "issues": workflow_issues,
        }
    except GeoSkillsError as exc:
        return {
            "status": "error",
            "output_directory": None,
            "issues": [exc.to_issue()],
        }
    except (BundleExportError, ReportError):
        return {
            "status": "error",
            "output_directory": None,
            "issues": [
                _issue(
                    "E827",
                    "error",
                    "输出事务或质量报告失败；最终输出未提交。若同目录出现 .geoskills-run-backup-* 恢复目录，请保留并人工恢复。",
                )
            ],
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "status": "error",
            "output_directory": None,
            "issues": [
                _issue(
                    "E899",
                    "error",
                    "执行工作流时发生未预期错误；最终输出未提交。",
                )
            ],
        }


__all__ = [
    "CLI_REPORT_SCHEMA_VERSION",
    "MAX_PLAN_BYTES",
    "PLAN_SCHEMA_VERSION",
    "WorkflowError",
    "build_plan",
    "create_plan",
    "execute_plan",
]
