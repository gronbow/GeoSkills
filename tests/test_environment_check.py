"""Tests for the beginner-friendly GeoSkills environment checker."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = (
    REPOSITORY_ROOT
    / "skills"
    / "geoskills"
    / "scripts"
    / "check_environment.py"
)


def run_check(*options: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), *options],
        capture_output=True,
        check=False,
        text=True,
    )
    return result, json.loads(result.stdout)


def test_runtime_environment_is_ready_without_local_paths() -> None:
    result, report = run_check()

    assert result.returncode == 0
    assert report["check_mode"] == "runtime"
    assert report["ready"] is True
    assert report["missing_modules"] == []
    assert "pytest" not in report["modules"]
    assert "yaml" in report["modules"]
    assert "defusedxml" in report["modules"]
    assert report["modules"]["defusedxml"]["version"]
    assert report["modules"]["PIL"]["version"]
    assert "python_executable" not in report


def test_development_check_includes_pytest() -> None:
    result, report = run_check("--dev")

    assert result.returncode == 0
    assert report["check_mode"] == "development"
    assert report["ready"] is True
    assert "pytest" in report["modules"]


def test_paths_are_only_included_when_explicitly_requested() -> None:
    result, report = run_check("--include-paths")

    assert result.returncode == 0
    assert report["python_executable"] == sys.executable


def test_build_report_is_reusable_by_the_unified_cli() -> None:
    sys.path.insert(0, str(CHECK_SCRIPT.parent))
    try:
        from check_environment import build_report

        report = build_report()
    finally:
        sys.path.remove(str(CHECK_SCRIPT.parent))

    assert report["ready"] is True
    assert report["check_mode"] == "runtime"
