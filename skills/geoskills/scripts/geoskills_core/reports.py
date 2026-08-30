"""Versioned, privacy-aware machine and human QA reports for GeoSkills."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from .export import AtomicBundle


class ReportError(ValueError):
    """Raised when a report would be invalid or unsafe to share."""


REPORT_SCHEMA_NAME = "geoskills-output-report"
REPORT_SCHEMA_VERSION = "1.0.0"
REPORT_STATUSES = frozenset(
    {"ready", "needs_input", "review", "blocked", "error"}
)
ISSUE_SEVERITIES = frozenset({"info", "warning", "review", "error"})

# This is intentionally available without adding a jsonschema dependency.
REPORT_JSON_SCHEMA: Mapping[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"urn:geoskills:schema:{REPORT_SCHEMA_NAME}:{REPORT_SCHEMA_VERSION}",
    "title": "GeoSkills output report",
    "type": "object",
    "required": [
        "schema",
        "status",
        "operation",
        "review_required",
        "source",
        "outputs",
        "issues",
        "next_actions",
        "privacy",
    ],
    "properties": {
        "schema": {
            "type": "object",
            "const": {
                "name": REPORT_SCHEMA_NAME,
                "version": REPORT_SCHEMA_VERSION,
            },
        },
        "status": {"enum": sorted(REPORT_STATUSES)},
        "operation": {"type": "string", "minLength": 1},
        "review_required": {"type": "boolean"},
        "source": {"type": "object"},
        "outputs": {"type": "array"},
        "issues": {"type": "array"},
        "next_actions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "privacy": {"type": "object"},
    },
}

_SHAREABLE_SOURCE_KEYS = frozenset(
    {
        "file_sha256",
        "size_bytes",
        "format",
        "layout",
        "row_count",
        "column_count",
        "file_sha256",
        "size_bytes",
    }
)
_FORBIDDEN_SHAREABLE_KEYS = frozenset(
    {
        "path",
        "absolute_path",
        "resolved_path",
        "input_path",
        "output_path",
        "report_file",
        "raw_data",
        "data",
        "values",
        "records",
        "preview",
        "examples",
        "samples",
        "sample_ids",
        "source_values",
        "data_min",
        "data_max",
        "raw_min",
        "raw_max",
        "observed_min",
        "observed_max",
        "source_min",
        "source_max",
    }
)
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_absolute_path_text(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    return (
        PureWindowsPath(text).is_absolute()
        or PurePosixPath(text).is_absolute()
        or bool(_WINDOWS_DRIVE.match(text))
    )


def _assert_shareable(value: Any, trail: str = "report") -> None:
    """Reject common path and raw-data leaks in a shareable report."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in _FORBIDDEN_SHAREABLE_KEYS:
                raise ReportError(
                    f"可分享报告不能包含字段 {trail}.{key_text}。"
                )
            _assert_shareable(item, f"{trail}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_shareable(item, f"{trail}[{index}]")
    elif isinstance(value, str) and _is_absolute_path_text(value):
        raise ReportError(f"可分享报告不能包含绝对路径：{trail}。")


def _normalise_source(
    source: Mapping[str, Any] | None,
    *,
    shareable: bool,
) -> dict[str, Any]:
    result = dict(source or {})
    if shareable:
        for sensitive_key in ("filename", "sheet", "sheet_names"):
            result.pop(sensitive_key, None)
        unsupported = sorted(set(result) - _SHAREABLE_SOURCE_KEYS)
        if unsupported:
            raise ReportError(
                "可分享报告的 source 包含未经允许的字段："
                + ", ".join(unsupported)
                + "。"
            )
        _assert_shareable(result, "report.source")
    return result


def _normalise_outputs(
    outputs: Sequence[Mapping[str, Any]],
    *,
    shareable: bool,
) -> list[dict[str, Any]]:
    records = [dict(item) for item in outputs]
    for index, record in enumerate(records):
        required = {"filename", "format", "bytes", "sha256"}
        missing = sorted(required - set(record))
        if missing:
            raise ReportError(
                f"outputs[{index}] 缺少字段：" + ", ".join(missing) + "。"
            )
        if shareable:
            _assert_shareable(record, f"report.outputs[{index}]")
    return records


def _normalise_issues(
    issues: Sequence[Mapping[str, Any]],
    *,
    shareable: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, value in enumerate(issues):
        item = dict(value)
        missing = sorted({"code", "severity", "message"} - set(item))
        if missing:
            raise ReportError(
                f"issues[{index}] 缺少字段：" + ", ".join(missing) + "。"
            )
        if item["severity"] not in ISSUE_SEVERITIES:
            raise ReportError(
                f"issues[{index}] 的 severity 无效：{item['severity']}。"
            )
        if shareable:
            _assert_shareable(item, f"report.issues[{index}]")
        results.append(item)
    return results


def build_report(
    *,
    operation: str,
    status: str,
    source: Mapping[str, Any] | None = None,
    outputs: Sequence[Mapping[str, Any]] = (),
    issues: Sequence[Mapping[str, Any]] = (),
    qa: Mapping[str, Any] | None = None,
    next_actions: Sequence[str] = (),
    review_required: bool = False,
    details: Mapping[str, Any] | None = None,
    shareable: bool = True,
) -> dict[str, Any]:
    """Build one deterministic report that follows the current schema.

    Shareable mode is the default.  It rejects absolute paths, raw-data-like
    fields, and source metadata beyond a small allow-list.  Local diagnostics
    must opt out explicitly with ``shareable=False``.
    """

    clean_operation = str(operation).strip()
    if not clean_operation:
        raise ReportError("operation 不能为空。")
    if status not in REPORT_STATUSES:
        raise ReportError(
            f"status 无效：{status}。可用值：{', '.join(sorted(REPORT_STATUSES))}。"
        )

    action_list = [str(action).strip() for action in next_actions]
    if any(not action for action in action_list):
        raise ReportError("next_actions 不能包含空白项目。")

    report: dict[str, Any] = {
        "schema": {
            "name": REPORT_SCHEMA_NAME,
            "version": REPORT_SCHEMA_VERSION,
        },
        "status": status,
        "operation": clean_operation,
        "review_required": bool(review_required),
        "source": _normalise_source(source, shareable=shareable),
        "outputs": _normalise_outputs(outputs, shareable=shareable),
        "issues": _normalise_issues(issues, shareable=shareable),
        "qa": dict(qa or {}),
        "next_actions": action_list,
        "privacy": {
            "mode": "shareable" if shareable else "local-diagnostic",
            "absolute_paths_included": not shareable,
            "source_values_included": not shareable,
        },
    }
    if details:
        report["details"] = dict(details)
    if shareable:
        _assert_shareable(report)
    validate_report(report, require_shareable=shareable)
    return report


def validate_report(
    report: Mapping[str, Any],
    *,
    require_shareable: bool = False,
) -> None:
    """Perform lightweight validation without an optional schema library."""

    required = set(REPORT_JSON_SCHEMA["required"])
    missing = sorted(required - set(report))
    if missing:
        raise ReportError("报告缺少字段：" + ", ".join(missing) + "。")
    if report.get("schema") != {
        "name": REPORT_SCHEMA_NAME,
        "version": REPORT_SCHEMA_VERSION,
    }:
        raise ReportError("报告 schema 名称或版本不受支持。")
    if report.get("status") not in REPORT_STATUSES:
        raise ReportError("报告 status 无效。")
    if not isinstance(report.get("review_required"), bool):
        raise ReportError("review_required 必须是布尔值。")
    if require_shareable:
        privacy = report.get("privacy", {})
        if privacy.get("mode") != "shareable":
            raise ReportError("当前操作要求可分享报告。")
        _assert_shareable(report)


def _markdown_text(value: Any) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _status_label(status: str) -> str:
    return {
        "ready": "技术生成完成",
        "needs_input": "需要补充信息",
        "review": "等待审核",
        "blocked": "已阻止输出",
        "error": "运行失败",
    }[status]


def render_qa_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise Chinese QA summary from a shareable report."""

    validate_report(report, require_shareable=True)
    lines = [
        "# GeoSkills 图件质量检查摘要",
        "",
        f"- 任务：{_markdown_text(report['operation'])}",
        f"- 状态：{_status_label(str(report['status']))}",
        f"- 需要人工审核：{'是' if report['review_required'] else '否'}",
        (
            f"- 报告格式：{REPORT_SCHEMA_NAME} "
            f"{REPORT_SCHEMA_VERSION}"
        ),
    ]
    if report["status"] == "ready":
        lines.append(
            "- 说明：技术生成已完成；仍需按最终尺寸进行视觉与科学审核。"
        )
    lines.extend(["", "## 输出文件", ""])

    outputs = list(report["outputs"])
    if outputs:
        lines.extend(
            [
                "| 文件 | 格式 | 大小（字节） | SHA-256 |",
                "|---|---:|---:|---|",
            ]
        )
        for record in outputs:
            digest = _markdown_text(record["sha256"])
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_text(record["filename"]),
                        _markdown_text(record["format"]),
                        _markdown_text(record["bytes"]),
                        digest,
                    ]
                )
                + " |"
            )
    else:
        lines.append("- 尚未生成输出文件。")

    lines.extend(["", "## 检查结果", ""])
    issues = list(report["issues"])
    if not issues:
        lines.append("- ✅ 未发现阻断问题。")
    else:
        icons = {
            "info": "ℹ️",
            "warning": "⚠️",
            "review": "🔎",
            "error": "❌",
        }
        for issue in issues:
            lines.append(
                f"- {icons[issue['severity']]} "
                f"[{_markdown_text(issue['code'])}] "
                f"{_markdown_text(issue['message'])}"
            )

    lines.extend(["", "## 下一步", ""])
    actions = list(report["next_actions"])
    if actions:
        lines.extend(f"- {_markdown_text(action)}" for action in actions)
    else:
        lines.append("- 无。")

    lines.extend(
        [
            "",
            "## 隐私说明",
            "",
            "- 本摘要采用可分享模式，仅记录文件名、大小和校验值。",
            "- 本摘要不包含本地绝对路径或源数据值。",
            "",
        ]
    )
    return "\n".join(lines)


def write_report_files(
    bundle: AtomicBundle,
    stem: str,
    report: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Write versioned JSON and Chinese Markdown reports into a staging bundle."""

    validate_report(report, require_shareable=True)
    clean_stem = str(stem).strip()
    if not clean_stem or Path(clean_stem).name != clean_stem or Path(
        clean_stem
    ).suffix:
        raise ReportError("报告名称必须是不含路径和扩展名的文件名。")

    json_path = bundle.stage_path(f"{clean_stem}.report.json")
    markdown_path = bundle.stage_path(f"{clean_stem}.qa.md")
    json_path.write_text(
        json.dumps(deepcopy(dict(report)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_qa_markdown(report), encoding="utf-8")
    return json_path, markdown_path
