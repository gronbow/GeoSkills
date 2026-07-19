"""Tests for the beginner-friendly GeoSKILLS environment checker."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = (
    REPOSITORY_ROOT
    / "skills"
    / "plot-ree-patterns"
    / "scripts"
    / "check_environment.py"
)


def test_development_environment_is_ready() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        capture_output=True,
        check=False,
        text=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["ready"] is True
    assert report["missing_modules"] == []
