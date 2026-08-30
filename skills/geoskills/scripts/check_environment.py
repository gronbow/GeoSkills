#!/usr/bin/env python3
"""Report whether the local Python environment can run or develop GeoSkills."""

from __future__ import annotations

import argparse
import importlib.util
from importlib import metadata
import json
import platform
import sys


RUNTIME_MODULES = {
    "numpy": "numerical calculations",
    "pandas": "CSV, TXT, and table handling",
    "matplotlib": "figure generation and export",
    "PIL": "raster figure validation",
    "openpyxl": "Excel .xlsx input",
    "defusedxml": "safe preflight inspection of Excel XML parts",
    "yaml": "versioned YAML plotting recipes",
}
DEVELOPMENT_MODULES = {
    "pytest": "automated tests",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check the local GeoSkills runtime. Use --dev only when developing "
            "or running the automated test suite."
        )
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="also require developer-only test dependencies",
    )
    parser.add_argument(
        "--include-paths",
        action="store_true",
        help="include the local Python executable path in the diagnostic report",
    )
    return parser.parse_args()


def module_version(name: str) -> str | None:
    package_name = {
        "yaml": "PyYAML",
        "PIL": "Pillow",
    }.get(name, name)
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def build_report(
    *,
    dev: bool = False,
    include_paths: bool = False,
) -> dict[str, object]:
    """Build a JSON-safe environment report for the CLI and unified workflow."""
    required_modules = dict(RUNTIME_MODULES)
    if dev:
        required_modules.update(DEVELOPMENT_MODULES)
    modules = {
        name: {
            "available": importlib.util.find_spec(name) is not None,
            "purpose": purpose,
            "version": module_version(name),
        }
        for name, purpose in required_modules.items()
    }
    missing = [name for name, details in modules.items() if not details["available"]]
    report: dict[str, object] = {
        "check_mode": "development" if dev else "runtime",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.system(),
        "ready": not missing,
        "missing_modules": missing,
        "modules": modules,
    }
    if include_paths:
        report["python_executable"] = sys.executable
    return report


def main() -> int:
    args = parse_args()
    report = build_report(dev=args.dev, include_paths=args.include_paths)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    missing = report["missing_modules"]
    if missing:
        print(
            "GeoSkills environment is not ready; missing: "
            + ", ".join(str(item) for item in missing),
            file=sys.stderr,
        )
        return 1
    print("GeoSkills environment is ready.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
