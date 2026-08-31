from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
LOCAL_RECIPE = ROOT / "local_data" / "v04_published_regression.yaml"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.workflow import (  # noqa: E402
    build_plan,
    create_plan,
    execute_plan,
)


TOP_CONFIRMATIONS = {
    "input_structure_reviewed": True,
    "column_mapping_reviewed": True,
    "units_reviewed": True,
    "plotted_data_export_reviewed": True,
}
REE_ELEMENTS = ["La", "Ce", "Pr"]
SPIDER_ELEMENTS = ["Rb", "Ba", "Th", "U", "Nb"]


def _task(
    task_id: str,
    diagram: str,
    parameters: dict[str, Any],
    *,
    confirmations: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "diagram": diagram,
        "stem": f"figure-{task_id}",
        "preset": "test-small",
        "parameters": parameters,
        "confirmations": confirmations or {},
    }


def _write_recipe(
    directory: Path,
    frame: pd.DataFrame,
    *,
    mapping: dict[str, str],
    units: dict[str, str],
    tasks: list[dict[str, Any]],
    report_profile: str = "shareable",
    quality: dict[str, Any] | None = None,
    derived_variables: list[dict[str, Any]] | None = None,
    data_basis: dict[str, Any] | None = None,
    data_quality_reviewed: bool | None = None,
    data_basis_reviewed: bool | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_csv(directory / "input.csv", index=False)
    recipe = {
        "schema_version": "geoskills.recipe/v1",
        "input": {
            "file": "input.csv",
            "sheet": None,
            "layout": "row-per-sample",
        },
        "columns": {
            "sample_id": "Sample",
            "group": "Group" if "Group" in frame.columns else None,
            "mapping": mapping,
            "units": units,
        },
        "output": {
            "directory": "bundle",
            "report_profile": report_profile,
        },
        "presets": {
            "test-small": {
                "extends": "review-preview",
                "style": {
                    "width_mm": 100,
                    "height_mm": 70,
                    "dpi": 72,
                },
            }
        },
        "confirmations": {
            **TOP_CONFIRMATIONS,
            **(
                {"data_quality_reviewed": data_quality_reviewed}
                if data_quality_reviewed is not None
                else {}
            ),
            **(
                {"data_basis_reviewed": data_basis_reviewed}
                if data_basis_reviewed is not None
                else {}
            ),
        },
        "tasks": tasks,
    }
    if quality is not None:
        recipe["quality"] = quality
    if derived_variables is not None:
        recipe["derived_variables"] = derived_variables
    if data_basis is not None:
        recipe["data_basis"] = data_basis
    path = directory / "recipe.yaml"
    path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _issue_codes(value: object) -> set[str]:
    codes: set[str] = set()
    if isinstance(value, dict):
        code = value.get("code")
        if isinstance(code, str):
            codes.add(code)
        for child in value.values():
            codes.update(_issue_codes(child))
    elif isinstance(value, list):
        for child in value:
            codes.update(_issue_codes(child))
    return codes


@pytest.mark.parametrize(
    ("recipe_name", "data_name", "task_id", "expected_code"),
    [
        (
            "geoskills_spider_workflow.yaml",
            "synthetic_spider_data.csv",
            "spider-main",
            "E423",
        ),
        (
            "geoskills_major_workflow.yaml",
            "synthetic_major_element_data.csv",
            "harker-main",
            "E424",
        ),
    ],
)
def test_single_column_blocks_unreadable_dense_layouts(
    tmp_path: Path,
    recipe_name: str,
    data_name: str,
    task_id: str,
    expected_code: str,
) -> None:
    recipe = yaml.safe_load((EXAMPLES / recipe_name).read_text(encoding="utf-8"))
    shutil.copyfile(EXAMPLES / data_name, tmp_path / data_name)
    recipe["output"]["directory"] = "bundle"
    recipe["tasks"] = [
        task for task in recipe["tasks"] if task["id"] == task_id
    ]
    recipe["tasks"][0]["preset"] = "publication-single-column"
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert expected_code in _issue_codes(result)


def test_quality_error_blocks_plan_without_leaking_rows_or_values(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["PRIVATE-ROW-A", "PRIVATE-ROW-B"],
            "La_ppm": [20.0, "confidential-invalid-token"],
            "Ce_ppm": [40.0, 44.0],
            "Pr_ppm": [5.0, 5.5],
        }
    )
    recipe_path = _write_recipe(
        tmp_path / "quality-error",
        frame,
        mapping={element: f"{element}_ppm" for element in REE_ELEMENTS},
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "ree-main",
                "ree",
                {
                    "reference": "chondrite-sm89",
                    "elements": REE_ELEMENTS,
                    "groups": "all",
                },
            )
        ],
    )

    result = build_plan(recipe_path)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)

    assert result["status"] == "blocked"
    assert "Q003" in _issue_codes(result)
    assert "PRIVATE-ROW" not in encoded
    assert "confidential-invalid-token" not in encoded


def test_quality_review_requires_confirmation_and_is_audited(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["PRIVATE-ROW-A", "PRIVATE-ROW-B"],
            "La_ppm": [20.0, 22.0],
            "Ce_ppm": [40.0, 44.0],
            "Pr_ppm": [5.0, 5.5],
            "SiO2_wt%": [60.0, 65.0],
            "Na2O_wt%": [20.0, 20.0],
        }
    )
    case = tmp_path / "quality-review"
    task = _task(
        "ree-main",
        "ree",
        {
            "reference": "chondrite-sm89",
            "elements": REE_ELEMENTS,
            "groups": "all",
        },
    )
    recipe_path = _write_recipe(
        case,
        frame,
        mapping={
            **{element: f"{element}_ppm" for element in REE_ELEMENTS},
            "SiO2": "SiO2_wt%",
            "Na2O": "Na2O_wt%",
        },
        units={"trace_elements": "ppm", "major_oxides": "wt%"},
        tasks=[task],
        quality={
            "major_oxide_total": {
                "analytes": ["SiO2", "Na2O"],
                "lower": 95,
                "upper": 105,
                "composition_basis": "as-reported",
                "severity": "review",
            }
        },
    )

    first = build_plan(recipe_path)
    assert first["status"] == "needs_confirmation"
    assert {"Q007", "R805"} <= _issue_codes(first)

    recipe_path = _write_recipe(
        case,
        frame,
        mapping={
            **{element: f"{element}_ppm" for element in REE_ELEMENTS},
            "SiO2": "SiO2_wt%",
            "Na2O": "Na2O_wt%",
        },
        units={"trace_elements": "ppm", "major_oxides": "wt%"},
        tasks=[task],
        quality={
            "major_oxide_total": {
                "analytes": ["SiO2", "Na2O"],
                "lower": 95,
                "upper": 105,
                "composition_basis": "as-reported",
                "severity": "review",
            }
        },
        data_quality_reviewed=True,
    )
    plan_path = case / "plan.json"
    planned = create_plan(recipe_path, plan_path)
    executed = execute_plan(recipe_path, plan_path)

    assert planned["status"] == "ready"
    assert executed["status"] == "review"
    task_report = json.loads(
        (case / "bundle" / "ree-main" / "figure-ree-main.report.json").read_text(
            encoding="utf-8"
        )
    )
    quality = task_report["details"]["data_processing"]["quality"]
    assert quality["major_oxide_total"]["below_range_count"] == 2
    assert quality["major_oxide_total"]["evaluated_row_count"] == 2
    encoded = json.dumps(task_report, ensure_ascii=False, allow_nan=False)
    assert "PRIVATE-ROW" not in encoded


def test_derived_ratio_is_pinned_in_plan_and_shareable_report(
    tmp_path: Path,
) -> None:
    elements = ["Rb", "Ba", "Th", "U", "Nb", "Y"]
    frame = pd.DataFrame(
        {
            "Sample": ["A", "B", "C"],
            **{
                f"{element}_ppm": [float(index + 1), float(index + 2), float(index + 3)]
                for index, element in enumerate(elements)
            },
        }
    )
    case = tmp_path / "derived-ratio"
    recipe_path = _write_recipe(
        case,
        frame,
        mapping={element: f"{element}_ppm" for element in elements},
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "spider-main",
                "spider",
                {
                    "reference": "pm-sm89",
                    "elements": ["Rb", "Ba", "Th", "U", "Nb"],
                    "groups": "all",
                },
            )
        ],
        derived_variables=[
            {
                "id": "Nb_Y",
                "operation": "ratio",
                "numerator": "Nb",
                "denominator": "Y",
                "input_unit": "ppm",
            }
        ],
    )
    plan_path = case / "plan.json"

    planned = create_plan(recipe_path, plan_path)
    executed = execute_plan(recipe_path, plan_path)

    assert planned["status"] == "ready"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    summary = plan["data_processing"]["derived_variables"]["summary"]
    assert summary["variable_count"] == 1
    assert summary["variables"][0]["valid_count"] == 3
    assert executed["status"] == "ready"
    report = json.loads(
        (
            case
            / "bundle"
            / "spider-main"
            / "figure-spider-main.report.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        report["details"]["data_processing"]["derived_variables"]["variables"][0][
            "formula"
        ]
        == "Nb/Y"
    )
    assert not list((case / "bundle").rglob("*.source_data.csv"))


def test_anhydrous_basis_and_k2o_diagram_run_end_to_end(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["PRIVATE-K-01", "PRIVATE-K-02"],
            "Group": ["Suite A", "Suite B"],
            "SiO2_wt%": [40.0, 44.0],
            "Na2O_wt%": [2.4, 2.4],
            "K2O_wt%": [0.4, 1.92],
            "MgO_wt%": [37.2, 31.68],
        }
    )
    case = tmp_path / "k2o-basis"
    recipe_path = _write_recipe(
        case,
        frame,
        mapping={
            "SiO2": "SiO2_wt%",
            "Na2O": "Na2O_wt%",
            "K2O": "K2O_wt%",
            "MgO": "MgO_wt%",
        },
        units={"major_oxides": "wt%"},
        tasks=[
            _task(
                "k2o-main",
                "k2o-sio2",
                {
                    "composition_basis": "anhydrous-normalized",
                    "groups": "all",
                },
                confirmations={
                    "volcanic_samples": True,
                    "composition_basis_reviewed": True,
                },
            )
        ],
        report_profile="local-reproducible",
        data_basis={
            "operation": "normalize-to-100",
            "basis": "anhydrous-100",
            "analytes": ["SiO2", "Na2O", "K2O", "MgO"],
        },
        data_basis_reviewed=True,
    )
    plan_path = case / "plan.json"

    planned = create_plan(recipe_path, plan_path)
    executed = execute_plan(recipe_path, plan_path)

    assert planned["status"] == "ready"
    assert executed["status"] == "ready"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    basis = plan["data_processing"]["data_basis"]
    assert basis["definition"]["operation"] == "normalize-to-100"
    assert basis["summary"]["valid_row_count"] == 2
    encoded_plan = json.dumps(plan, ensure_ascii=False, allow_nan=False)
    assert "PRIVATE-K" not in encoded_plan

    task_dir = case / "bundle" / "k2o-main"
    plotted = pd.read_csv(task_dir / "figure-k2o-main.source_data.csv")
    assert plotted["SiO2"].tolist() == pytest.approx([50.0, 55.0])
    assert plotted["K2O"].tolist() == pytest.approx([0.5, 2.4])
    report = json.loads(
        (task_dir / "figure-k2o-main.report.json").read_text(encoding="utf-8")
    )
    assert report["details"]["data_processing"]["data_basis"][
        "valid_row_count"
    ] == 2
    assert report["details"]["plot_summary"]["complete_domain_x"] == [
        48.0,
        63.0,
    ]
    assert "PRIVATE-K" not in json.dumps(
        report, ensure_ascii=False, allow_nan=False
    )


@pytest.mark.parametrize(
    ("case_name", "frame", "mapping"),
    [
        (
            "unit-conflict",
            pd.DataFrame(
                {
                    "Sample": ["S1", "S2"],
                    "Group": ["A", "A"],
                    "La_ppb": [20.0, 22.0],
                    "Ce_ppm": [40.0, 44.0],
                    "Pr_ppm": [5.0, 5.5],
                }
            ),
            {"La": "La_ppb", "Ce": "Ce_ppm", "Pr": "Pr_ppm"},
        ),
        (
            "analyte-conflict",
            pd.DataFrame(
                {
                    "Sample": ["S1", "S2"],
                    "Group": ["A", "A"],
                    "La_ppm": [20.0, 22.0],
                    "Ce_ppm": [40.0, 44.0],
                    "Pr_ppm": [5.0, 5.5],
                }
            ),
            {"La": "Ce_ppm", "Ce": "La_ppm", "Pr": "Pr_ppm"},
        ),
    ],
)
def test_e415_rejects_explicit_header_conflicts(
    tmp_path: Path,
    case_name: str,
    frame: pd.DataFrame,
    mapping: dict[str, str],
) -> None:
    recipe_path = _write_recipe(
        tmp_path / case_name,
        frame,
        mapping=mapping,
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "ree-main",
                "ree",
                {
                    "reference": "chondrite-sm89",
                    "elements": REE_ELEMENTS,
                    "groups": "all",
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert "E415" in _issue_codes(result)


def test_ree_and_spider_group_filters_reach_exported_source(
    tmp_path: Path,
) -> None:
    elements = [*REE_ELEMENTS, *SPIDER_ELEMENTS]
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2", "S3"],
            "Group": ["A", "A", "B"],
            "La_ppm": [20.0, 22.0, 35.0],
            "Ce_ppm": [40.0, 44.0, 70.0],
            "Pr_ppm": [5.0, 5.5, 8.0],
            "Rb_ppm": [30.0, 32.0, 60.0],
            "Ba_ppm": [300.0, 320.0, 600.0],
            "Th_ppm": [5.0, 5.5, 10.0],
            "U_ppm": [1.2, 1.3, 2.5],
            "Nb_ppm": [15.0, 16.0, 30.0],
        }
    )
    recipe_path = _write_recipe(
        tmp_path / "filtered-patterns",
        frame,
        mapping={element: f"{element}_ppm" for element in elements},
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "ree-main",
                "ree",
                {
                    "reference": "chondrite-sm89",
                    "elements": REE_ELEMENTS,
                    "groups": ["A"],
                },
            ),
            _task(
                "spider-main",
                "spider",
                {
                    "reference": "pm-sm89",
                    "elements": SPIDER_ELEMENTS,
                    "groups": ["A"],
                },
            ),
        ],
        report_profile="local-reproducible",
    )
    plan_path = recipe_path.parent / "plan.json"

    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    executed = execute_plan(recipe_path, plan_path)

    assert executed["status"] == "ready"
    for task_id in ("ree-main", "spider-main"):
        source = pd.read_csv(
            recipe_path.parent
            / "bundle"
            / task_id
            / f"figure-{task_id}.source_data.csv"
        )
        assert len(source) == 2
        assert set(source["Group"].astype(str).str.strip()) == {"A"}


def test_missing_group_blocks_with_e412(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "Group": ["A", "B"],
            "La_ppm": [20.0, 30.0],
            "Ce_ppm": [40.0, 60.0],
            "Pr_ppm": [5.0, 7.5],
        }
    )
    recipe_path = _write_recipe(
        tmp_path / "missing-group",
        frame,
        mapping={element: f"{element}_ppm" for element in REE_ELEMENTS},
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "ree-main",
                "ree",
                {
                    "reference": "chondrite-sm89",
                    "elements": REE_ELEMENTS,
                    "groups": ["not-present"],
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert "E412" in _issue_codes(result)


def test_spider_zero_positive_selection_blocks_with_e419(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2", "S3", "S4"],
            "Group": ["A", "A", "B", "B"],
            **{
                f"{element}_ppm": [10.0, 12.0, None, None]
                for element in SPIDER_ELEMENTS
            },
        }
    )
    recipe_path = _write_recipe(
        tmp_path / "no-positive-spider-data",
        frame,
        mapping={
            element: f"{element}_ppm" for element in SPIDER_ELEMENTS
        },
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "spider-main",
                "spider",
                {
                    "reference": "pm-sm89",
                    "elements": SPIDER_ELEMENTS,
                    "groups": ["B"],
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert "E419" in _issue_codes(result)


def test_ree_zero_positive_selection_blocks_with_e419(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2", "S3", "S4"],
            "Group": ["A", "A", "B", "B"],
            **{
                f"{element}_ppm": [10.0, 12.0, None, None]
                for element in REE_ELEMENTS
            },
        }
    )
    recipe_path = _write_recipe(
        tmp_path / "no-positive-ree-data",
        frame,
        mapping={
            element: f"{element}_ppm" for element in REE_ELEMENTS
        },
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "ree-main",
                "ree",
                {
                    "reference": "chondrite-sm89",
                    "elements": REE_ELEMENTS,
                    "groups": ["B"],
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert "E419" in _issue_codes(result)


def test_spider_direct_k_is_preferred_before_oxide_fallback(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "Group": ["A", "A"],
            "Rb_ppm": [None, None],
            "Ba_ppm": [None, None],
            "Th_ppm": [None, None],
            "U_ppm": [None, None],
            "K_ppm": [25000.0, 27000.0],
        }
    )
    elements = ["Rb", "Ba", "Th", "U", "K"]
    recipe_path = _write_recipe(
        tmp_path / "direct-k",
        frame,
        mapping={element: f"{element}_ppm" for element in elements},
        units={"trace_elements": "ppm"},
        tasks=[
            _task(
                "spider-main",
                "spider",
                {
                    "reference": "pm-sm89",
                    "elements": elements,
                    "groups": "all",
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "ready"
    assert "E419" not in _issue_codes(result)


def test_harker_limits_panels_with_e416(tmp_path: Path) -> None:
    frame = pd.read_csv(EXAMPLES / "synthetic_major_element_data.csv")
    mapping = {
        "SiO2": "SiO2_wt%",
        "TiO2": "TiO2_wt%",
        "Al2O3": "Al2O3_wt%",
        "Fe2O3T": "Fe2O3T_wt%",
        "MnO": "MnO_wt%",
        "MgO": "MgO_wt%",
        "CaO": "CaO_wt%",
        "Na2O": "Na2O_wt%",
        "K2O": "K2O_wt%",
        "P2O5": "P2O5_wt%",
        "Rb": "Rb_ppm",
    }
    recipe_path = _write_recipe(
        tmp_path / "too-many-harker-panels",
        frame,
        mapping=mapping,
        units={"major_oxides": "wt%", "trace_elements": "ppm"},
        tasks=[
            _task(
                "harker-main",
                "harker",
                {
                    "x": "SiO2",
                    "y": [
                        "TiO2",
                        "Al2O3",
                        "Fe2O3T",
                        "MnO",
                        "MgO",
                        "CaO",
                        "Na2O",
                        "K2O",
                        "P2O5",
                        "Rb",
                    ],
                    "groups": "all",
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert "E416" in _issue_codes(result)


def test_harker_selected_subset_needs_two_complete_pairs(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "Group": ["A", "B"],
            "SiO2_wt%": [50.0, 55.0],
            "MgO_wt%": [7.0, 4.0],
        }
    )
    recipe_path = _write_recipe(
        tmp_path / "short-harker-subset",
        frame,
        mapping={"SiO2": "SiO2_wt%", "MgO": "MgO_wt%"},
        units={"major_oxides": "wt%"},
        tasks=[
            _task(
                "harker-main",
                "harker",
                {
                    "x": "SiO2",
                    "y": ["MgO"],
                    "groups": ["B"],
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert "E417" in _issue_codes(result)


def test_tas_selected_subset_needs_a_complete_coordinate(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2", "S3"],
            "Group": ["A", "B", "B"],
            "SiO2_wt%": [50.0, None, None],
            "Na2O_wt%": [3.0, None, None],
            "K2O_wt%": [1.0, None, None],
        }
    )
    recipe_path = _write_recipe(
        tmp_path / "empty-tas-subset",
        frame,
        mapping={
            "SiO2": "SiO2_wt%",
            "Na2O": "Na2O_wt%",
            "K2O": "K2O_wt%",
        },
        units={"major_oxides": "wt%"},
        tasks=[
            _task(
                "tas-main",
                "tas",
                {
                    "composition_basis": "anhydrous-normalized",
                    "groups": ["B"],
                },
                confirmations={
                    "volcanic_samples": True,
                    "composition_basis_reviewed": True,
                },
            )
        ],
    )

    result = build_plan(recipe_path)

    assert result["status"] == "blocked"
    assert "E418" in _issue_codes(result)


def test_major_example_basis_and_scientific_audit_reports(
    tmp_path: Path,
) -> None:
    source_data = EXAMPLES / "synthetic_major_element_data.csv"
    frame = pd.read_csv(source_data)
    major_columns = [
        "SiO2_wt%",
        "TiO2_wt%",
        "Al2O3_wt%",
        "Fe2O3T_wt%",
        "MnO_wt%",
        "MgO_wt%",
        "CaO_wt%",
        "Na2O_wt%",
        "K2O_wt%",
        "P2O5_wt%",
    ]
    totals = frame[major_columns].sum(axis=1)
    assert ((totals - 100.0).abs() <= 0.001).all()

    case = tmp_path / "major-example"
    case.mkdir()
    shutil.copyfile(
        source_data,
        case / "synthetic_major_element_data.csv",
    )
    recipe = yaml.safe_load(
        (EXAMPLES / "geoskills_major_workflow.yaml").read_text(
            encoding="utf-8"
        )
    )
    recipe["output"]["directory"] = "bundle"
    recipe["presets"]["journal-main"]["style"]["dpi"] = 300
    recipe_path = case / "recipe.yaml"
    recipe_path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    plan_path = case / "plan.json"

    planned = create_plan(recipe_path, plan_path)
    executed = execute_plan(recipe_path, plan_path)

    assert planned["status"] == "ready"
    assert executed["status"] == "review"
    harker_report = json.loads(
        (
            case
            / "bundle"
            / "harker-main"
            / "figure-harker.report.json"
        ).read_text(encoding="utf-8")
    )
    tas_report = json.loads(
        (
            case
            / "bundle"
            / "tas-main"
            / "figure-tas.report.json"
        ).read_text(encoding="utf-8")
    )
    k2o_report = json.loads(
        (
            case
            / "bundle"
            / "k2o-series-main"
            / "figure-k2o-sio2.report.json"
        ).read_text(encoding="utf-8")
    )
    run_report = json.loads(
        (case / "bundle" / "run.report.json").read_text(encoding="utf-8")
    )
    analyte_units = harker_report["details"]["analyte_units"]
    assert analyte_units["SiO2"] == "wt%"
    assert analyte_units["Rb"] == "ppm"
    assert tas_report["details"]["scientific_confirmations"] == {
        "volcanic_samples": True,
        "composition_basis_reviewed": True,
    }
    assert k2o_report["status"] == "review"
    assert {item["code"] for item in k2o_report["issues"]} == {"W812"}
    assert run_report["details"]["data_confirmations"] == {
        **TOP_CONFIRMATIONS,
        "data_basis_reviewed": True,
    }


def test_shareable_plan_and_reports_redact_source_names_and_selected_groups(
    tmp_path: Path,
) -> None:
    sentinel_group = "PRIVATE-LOCALITY-X"
    sentinel_file = "PROJECT-ALPHA-sample-001.csv"
    sentinel_x_column = "PRIVATE-SILICA-COLUMN"
    frame = pd.DataFrame(
        {
            "Sample": ["PRIVATE-SAMPLE-A", "PRIVATE-SAMPLE-B", "OTHER"],
            "Group": [sentinel_group, sentinel_group, "Public group"],
            sentinel_x_column: [50.0, 55.0, 60.0],
            "MgO_wt%": [8.0, 6.0, 4.0],
        }
    )
    case = tmp_path / "shareable-redaction"
    recipe_path = _write_recipe(
        case,
        frame,
        mapping={"SiO2": sentinel_x_column, "MgO": "MgO_wt%"},
        units={"major_oxides": "wt%", "trace_elements": "ppm"},
        tasks=[
            _task(
                "harker-main",
                "harker",
                {
                    "x": "SiO2",
                    "y": ["MgO"],
                    "groups": [sentinel_group],
                },
            )
        ],
    )
    (case / "input.csv").rename(case / sentinel_file)
    recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    recipe["input"]["file"] = sentinel_file
    recipe_path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    plan_path = case / "plan.json"

    planned = create_plan(recipe_path, plan_path)
    executed = execute_plan(recipe_path, plan_path)

    assert planned["status"] == "ready"
    assert executed["status"] == "ready"
    shareable_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [plan_path, *sorted((case / "bundle").rglob("*.json")), *sorted((case / "bundle").rglob("*.md"))]
    )
    for token in (sentinel_group, sentinel_file, sentinel_x_column, "PRIVATE-SAMPLE"):
        assert token not in shareable_text
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    selection = plan["tasks"][0]["parameters"]["groups"]
    assert selection["selection_mode"] == "selected"
    assert selection["selected_group_count"] == 1
    assert len(selection["selection_sha256"]) == 64


def test_changing_private_group_selection_invalidates_saved_plan(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["A1", "A2", "B1", "B2"],
            "Group": ["PRIVATE-A", "PRIVATE-A", "PRIVATE-B", "PRIVATE-B"],
            "SiO2_wt%": [50.0, 52.0, 60.0, 62.0],
            "MgO_wt%": [8.0, 7.0, 4.0, 3.0],
        }
    )
    case = tmp_path / "group-plan-invalidation"
    recipe_path = _write_recipe(
        case,
        frame,
        mapping={"SiO2": "SiO2_wt%", "MgO": "MgO_wt%"},
        units={"major_oxides": "wt%", "trace_elements": "ppm"},
        tasks=[
            _task(
                "harker-main",
                "harker",
                {"x": "SiO2", "y": ["MgO"], "groups": ["PRIVATE-A"]},
            )
        ],
    )
    plan_path = case / "plan.json"
    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    recipe["tasks"][0]["parameters"]["groups"] = ["PRIVATE-B"]
    recipe_path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    executed = execute_plan(recipe_path, plan_path)

    assert executed["status"] == "blocked"
    assert "R803" in _issue_codes(executed)
    assert not (case / "bundle").exists()


def test_local_published_recipe_build_plan_is_ready() -> None:
    if not LOCAL_RECIPE.is_file():
        pytest.skip("local published regression recipe is not available")
    recipe = yaml.safe_load(LOCAL_RECIPE.read_text(encoding="utf-8"))
    input_path = LOCAL_RECIPE.parent / str(recipe["input"]["file"])
    if not input_path.is_file():
        pytest.skip("local published regression input is not available")

    result = build_plan(LOCAL_RECIPE)

    assert result["status"] == "ready"
    assert result["plan"] is not None
    tasks = result["plan"]["tasks"]
    assert {task["diagram"] for task in tasks} == {
        "ree",
        "spider",
        "harker",
    }
    assert all(task["inspection"]["status"] == "ready" for task in tasks)
