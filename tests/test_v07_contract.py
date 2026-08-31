from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.recipe import load_recipe, validate_recipe  # noqa: E402
from geoskills_core.registry import diagram_ids, get_diagram  # noqa: E402
from geoskills_core.workflow import create_plan, execute_plan  # noqa: E402


def _recipe() -> dict:
    return {
        "schema_version": "geoskills.recipe/v1",
        "input": {
            "file": "data.csv",
            "sheet": None,
            "layout": "row-per-sample",
        },
        "columns": {
            "sample_id": "Sample",
            "group": "Group",
            "mapping": {
                "SiO2": "SiO2_wt%",
                "MgO": "MgO_wt%",
                "Nb": "Nb_ppm",
                "Y": "Y_ppm",
            },
            "units": {
                "major_oxides": "wt%",
                "trace_elements": "ppm",
            },
        },
        "derived_variables": [
            {
                "id": "Nb_Y",
                "operation": "ratio",
                "numerator": "Nb",
                "denominator": "Y",
                "input_unit": "ppm",
            }
        ],
        "output": {
            "directory": "bundle",
            "report_profile": "shareable",
        },
        "presets": {},
        "confirmations": {
            "input_structure_reviewed": True,
            "column_mapping_reviewed": True,
            "units_reviewed": True,
            "plotted_data_export_reviewed": True,
        },
        "tasks": [
            {
                "id": "xy-main",
                "diagram": "xy",
                "stem": "figure-xy",
                "preset": "publication-double-column",
                "parameters": {
                    "x": {"kind": "direct", "id": "SiO2", "scale": "linear"},
                    "y": {"kind": "derived", "id": "Nb_Y", "scale": "log10"},
                    "groups": "all",
                },
                "confirmations": {},
            }
        ],
    }


def _codes(result: dict) -> set[str]:
    return {str(item["code"]) for item in result["issues"]}


def test_v07_registry_exposes_coordinate_only_xy() -> None:
    assert diagram_ids()[-1] == "xy"
    spec = get_diagram("xy")
    assert spec.operation == "generic_bivariate_plot"
    assert spec.required_assets == ()
    assert "classification" not in spec.operation


def test_xy_recipe_accepts_direct_and_reviewed_same_unit_ratio() -> None:
    result = validate_recipe(_recipe())

    assert result["status"] == "ready"
    parameters = result["recipe"]["tasks"][0]["parameters"]
    assert parameters["x"] == {
        "kind": "direct",
        "id": "SiO2",
        "scale": "linear",
    }
    assert parameters["y"] == {
        "kind": "derived",
        "id": "Nb_Y",
        "scale": "log10",
    }


@pytest.mark.parametrize(
    ("axis", "replacement"),
    [
        ("x", {"kind": "expression", "id": "eval(1)", "scale": "linear"}),
        ("x", {"kind": "direct", "id": "Missing", "scale": "linear"}),
        ("y", {"kind": "derived", "id": "Missing", "scale": "log10"}),
        ("y", {"kind": "derived", "id": "Nb_Y", "scale": "symlog"}),
    ],
)
def test_xy_recipe_rejects_unregistered_variables_and_scales(
    axis: str,
    replacement: dict,
) -> None:
    recipe = _recipe()
    recipe["tasks"][0]["parameters"][axis] = replacement

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E317" in _codes(result)


@pytest.mark.parametrize(
    "duplicate_yaml",
    [
        "confirmations:\n  units_reviewed: false\n  units_reviewed: true\n",
        "input:\n  file: a.csv\n  file: b.csv\n",
        "tasks:\n  - id: first\n    id: second\n",
        (
            "defaults: &defaults\n  units_reviewed: false\n"
            "confirmations:\n  <<: *defaults\n  units_reviewed: true\n"
        ),
    ],
)
def test_yaml_duplicate_keys_are_rejected(
    tmp_path: Path,
    duplicate_yaml: str,
) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(duplicate_yaml, encoding="utf-8")

    result = load_recipe(path)

    assert result["status"] == "invalid"
    assert _codes(result) == {"E301"}


def test_style_budget_blocks_pathological_raster_before_plotting() -> None:
    recipe = _recipe()
    recipe["presets"] = {
        "too-large": {
            "extends": "publication-double-column",
            "style": {"width_mm": 500, "height_mm": 500, "dpi": 1200},
        }
    }
    recipe["tasks"][0]["preset"] = "too-large"

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E314" in _codes(result)


def test_cli_capabilities_is_machine_readable_and_disables_abbreviations() -> None:
    command = [sys.executable, str(SCRIPTS / "geoskills.py"), "capabilities"]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    document = json.loads(completed.stdout)
    assert document["status"] == "ready"
    assert document["result"]["diagram_ids"][-1] == "xy"

    abbreviated = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "geoskills.py"),
            "plan",
            "recipe.yaml",
            "--out",
            "plan.json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert abbreviated.returncode == 1
    error = json.loads(abbreviated.stdout)
    assert error["issues"][0]["code"] == "E900"
    assert "--output" in error["issues"][0]["message"]


def test_xy_workflow_plan_and_run_complete_privacy_safe_bundle(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "Sample": [f"PRIVATE-SAMPLE-{index}" for index in range(4)],
            "Group": ["PRIVATE-PLACE-A", "PRIVATE-PLACE-A", "B", "B"],
            "SiO2_wt%": [48.0, 52.0, 60.0, 70.0],
            "MgO_wt%": [8.0, 6.0, 4.0, 2.0],
            "Nb_ppm": [8.0, 12.0, 20.0, 30.0],
            "Y_ppm": [20.0, 20.0, 20.0, 20.0],
        }
    )
    frame.to_csv(tmp_path / "data.csv", index=False)
    recipe = _recipe()
    recipe["output"]["directory"] = "bundle"
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    plan_path = tmp_path / "plan.json"

    planned = create_plan(recipe_path, plan_path)
    assert planned["status"] == "ready"
    executed = execute_plan(recipe_path, plan_path)

    assert executed["status"] == "ready"
    task = tmp_path / "bundle" / "xy-main"
    assert all(
        (task / f"figure-xy.{extension}").is_file()
        for extension in ("svg", "pdf", "tiff", "png")
    )
    assert not (task / "figure-xy.source_data.csv").exists()
    shareable_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [
            plan_path,
            task / "figure-xy.svg",
            task / "figure-xy.report.json",
            task / "figure-xy.qa.md",
            tmp_path / "bundle" / "run.report.json",
        ]
    )
    assert "PRIVATE-SAMPLE" not in shareable_text


def test_shareable_ree_figure_omits_private_sample_identifiers(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "Sample": [f"PRIVATE-SAMPLE-{index}" for index in range(4)],
            "Group": ["A", "A", "B", "B"],
            "La_ppm": [10.0, 11.0, 12.0, 13.0],
            "Ce_ppm": [20.0, 21.0, 22.0, 23.0],
            "Pr_ppm": [3.0, 3.1, 3.2, 3.3],
            "Nd_ppm": [12.0, 13.0, 14.0, 15.0],
            "Sm_ppm": [2.0, 2.1, 2.2, 2.3],
        }
    )
    frame.to_csv(tmp_path / "data.csv", index=False)
    recipe = _recipe()
    recipe["derived_variables"] = []
    recipe["columns"]["mapping"] = {
        element: f"{element}_ppm" for element in ["La", "Ce", "Pr", "Nd", "Sm"]
    }
    recipe["columns"]["units"] = {"trace_elements": "ppm"}
    recipe["tasks"] = [
        {
            "id": "ree-main",
            "diagram": "ree",
            "stem": "figure-ree",
            "preset": "publication-double-column",
            "parameters": {
                "reference": "chondrite-sm89",
                "elements": ["La", "Ce", "Pr", "Nd", "Sm"],
                "groups": "all",
            },
            "confirmations": {},
        }
    ]
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    plan_path = tmp_path / "plan.json"

    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    result = execute_plan(recipe_path, plan_path)

    assert result["status"] == "ready"
    svg = (
        tmp_path / "bundle" / "ree-main" / "figure-ree.svg"
    ).read_text(encoding="utf-8")
    assert "PRIVATE-SAMPLE" not in svg
    report = json.loads(
        (
            tmp_path / "bundle" / "ree-main" / "figure-ree.report.json"
        ).read_text(encoding="utf-8")
    )
    assert report["details"]["plot_summary"]["sample_ids_rendered"] is False
