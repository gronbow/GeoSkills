#!/usr/bin/env python3
"""Report whether the local Python environment can support GeoSkills development."""

from __future__ import annotations

import importlib.util
import json
import platform
import sys


REQUIRED_MODULES = {
    "numpy": "numerical calculations",
    "pandas": "CSV, TXT, and table handling",
    "matplotlib": "figure generation and export",
    "openpyxl": "Excel .xlsx input",
    "pytest": "automated tests",
}


def main() -> int:
    modules = {
        name: {
            "available": importlib.util.find_spec(name) is not None,
            "purpose": purpose,
        }
        for name, purpose in REQUIRED_MODULES.items()
    }
    missing = [name for name, details in modules.items() if not details["available"]]
    report = {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "ready": not missing,
        "missing_modules": missing,
        "modules": modules,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if missing:
        print(
            "GeoSkills environment is not ready; missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1
    print("GeoSkills environment is ready.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
