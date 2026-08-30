#!/usr/bin/env python3
"""Unified, machine-readable GeoSkills v0.4 command line."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path
from typing import Any, NoReturn


SCRIPTS_DIR = Path(__file__).resolve().parent
TOOL_VERSION = str(
    runpy.run_path(
        str(SCRIPTS_DIR / "geoskills_core" / "version.py")
    )["VERSION"]
)
DIAGRAM_API_VERSION = "geoskills.diagram/v1"
CLI_REPORT_SCHEMA_VERSION = "geoskills.cli-report/v1"


def _issue(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def envelope(
    command: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CLI_REPORT_SCHEMA_VERSION,
        "command": command,
        "status": status,
        "tool": {
            "name": "GeoSkills",
            "version": TOOL_VERSION,
        },
        "result": result or {},
        "issues": issues or [],
    }


def emit(document: dict[str, Any]) -> None:
    print(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )


def exit_code(status: str) -> int:
    if status == "ready":
        return 0
    if status in {"blocked", "needs_confirmation", "review"}:
        return 2
    return 1


class JsonArgumentParser(argparse.ArgumentParser):
    """Return malformed command lines as the same JSON contract."""

    def error(self, message: str) -> NoReturn:
        command = (
            sys.argv[1]
            if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
            else "unknown"
        )
        emit(
            envelope(
                command,
                "error",
                issues=[_issue("E900", "error", message)],
            )
        )
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="GeoSkills 本地地球化学绘图工作流。",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version", help="显示工具与接口版本")
    commands.add_parser("capabilities", help="列出已审核图解和固定参数合同")

    self_check = commands.add_parser(
        "self-check",
        help="检查本地运行环境",
    )
    self_check.add_argument(
        "--dev",
        action="store_true",
        help="同时检查开发测试依赖",
    )
    self_check.add_argument(
        "--include-paths",
        action="store_true",
        help="明确允许诊断结果包含本地 Python 路径",
    )

    plan = commands.add_parser(
        "plan",
        help="检查配方和输入并保存可审核计划，不出图",
        allow_abbrev=False,
    )
    plan.add_argument("recipe", type=Path, help="YAML 配方文件")
    plan.add_argument(
        "--output",
        type=Path,
        required=True,
        help="计划 JSON 文件",
    )
    plan.add_argument(
        "--task",
        action="append",
        dest="tasks",
        help="只选择该任务 ID；可重复使用",
    )
    plan.add_argument(
        "--overwrite-plan",
        action="store_true",
        help="明确替换已有计划文件",
    )

    run = commands.add_parser(
        "run",
        help="复核计划未变化后，一次性生成完整输出",
        allow_abbrev=False,
    )
    run.add_argument("recipe", type=Path, help="YAML 配方文件")
    run.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="先前生成并审核过的计划 JSON",
    )
    run.add_argument(
        "--overwrite",
        action="store_true",
        help="明确原子替换已有完整输出目录",
    )
    return parser


def command_version() -> tuple[dict[str, Any], int]:
    document = envelope(
        "version",
        "ready",
        result={
            "tool_version": TOOL_VERSION,
            "diagram_api_version": DIAGRAM_API_VERSION,
        },
    )
    return document, 0


def command_capabilities() -> tuple[dict[str, Any], int]:
    from geoskills_core.registry import diagram_ids, registry_snapshot

    document = envelope(
        "capabilities",
        "ready",
        result={
            "diagram_api_version": DIAGRAM_API_VERSION,
            "diagram_ids": list(diagram_ids()),
            "diagrams": registry_snapshot(),
        },
    )
    return document, 0


def command_self_check(
    *,
    dev: bool,
    include_paths: bool,
) -> tuple[dict[str, Any], int]:
    from check_environment import build_report

    report = build_report(dev=dev, include_paths=include_paths)
    status = "ready" if bool(report["ready"]) else "error"
    if include_paths:
        report["privacy_warning"] = (
            "该诊断由用户明确要求，包含本地 Python 可执行文件路径；"
            "分享前请先检查。"
        )
    issues = (
        []
        if status == "ready"
        else [
            _issue(
                "E901",
                "error",
                "本地环境缺少运行所需模块。",
            )
        ]
    )
    return (
        envelope(
            "self-check",
            status,
            result=report,
            issues=issues,
        ),
        exit_code(status),
    )


def command_plan(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from geoskills_core.workflow import create_plan

    report = create_plan(
        args.recipe,
        args.output,
        selected_task_ids=args.tasks,
        overwrite=args.overwrite_plan,
    )
    status = str(report["status"])
    result = {
        key: value
        for key, value in report.items()
        if key not in {"status", "issues"}
    }
    return (
        envelope(
            "plan",
            status,
            result=result,
            issues=report["issues"],
        ),
        exit_code(status),
    )


def command_run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from geoskills_core.workflow import execute_plan

    report = execute_plan(
        args.recipe,
        args.plan,
        overwrite=args.overwrite,
    )
    status = str(report["status"])
    result = {
        key: value
        for key, value in report.items()
        if key not in {"status", "issues"}
    }
    return (
        envelope(
            "run",
            status,
            result=result,
            issues=report["issues"],
        ),
        exit_code(status),
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        if args.command == "version":
            document, code = command_version()
        elif args.command == "capabilities":
            document, code = command_capabilities()
        elif args.command == "self-check":
            document, code = command_self_check(
                dev=args.dev,
                include_paths=args.include_paths,
            )
        elif args.command == "plan":
            document, code = command_plan(args)
        else:
            document, code = command_run(args)
    except Exception:
        document = envelope(
            str(args.command),
            "error",
            issues=[
                _issue(
                    "E999",
                    "error",
                    "GeoSkills 遇到未预期错误；请运行 self-check 并保存命令输出。",
                )
            ],
        )
        code = 1
    emit(document)
    print(
        f"GeoSkills {args.command}: {document['status']}.",
        file=sys.stderr,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
