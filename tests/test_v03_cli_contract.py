from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"


LEGACY_CLI_CONTRACT = {
    "inspect_data.py": ("--sheet", "--sample-column", "--group-column"),
    "inspect_spider_data.py": ("--sheet", "--sample-column", "--group-column"),
    "inspect_major_data.py": ("--sheet", "--sample-column", "--group-column"),
    "normalize_ree.py": ("--output", "--overwrite"),
    "normalize_spider.py": ("--output", "--reference", "--overwrite"),
    "plot_ree.py": (
        "--output-dir",
        "--axes-frame",
        "--legend-layout",
        "--overwrite",
    ),
    "plot_spider.py": (
        "--output-dir",
        "--reference",
        "--elements",
        "--overwrite",
    ),
    "plot_harker.py": ("--output-dir", "--x", "--y", "--overwrite"),
    "plot_tas.py": (
        "--output-dir",
        "--confirm-volcanic",
        "--composition-basis",
        "--overwrite",
    ),
}


def test_v03_command_names_and_options_remain_available() -> None:
    """Keep the released v0.3 command surface while v0.4 adds one entry point."""
    for script_name, required_options in LEGACY_CLI_CONTRACT.items():
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script_name), "--help"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        for option in required_options:
            assert option in result.stdout
