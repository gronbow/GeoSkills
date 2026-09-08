from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.recipe import (  # noqa: E402
    MAX_RECIPE_BYTES,
    MAX_TASKS,
    RECIPE_SCHEMA_VERSION,
    load_recipe,
    validate_recipe,
)
from geoskills_core.registry import (  # noqa: E402
    BUILTIN_STYLE_PRESETS,
    DIAGRAMS,
    RegistryError,
    diagram_ids,
    get_diagram,
    registry_snapshot,
    resolve_handler,
)
from geoskills_core.version import VERSION  # noqa: E402


def valid_recipe() -> dict:
    elements = ["La", "Ce", "Pr", "Nd", "Sm"]
    return {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "input": {
            "file": "localdata/published.csv",
            "sheet": None,
            "layout": "auto",
        },
        "columns": {
            "sample_id": "Sample",
            "group": "Group",
            "mapping": {
                **{element: f"{element}_ppm" for element in elements},
                "SiO2": "SiO2_wt%",
                "Na2O": "Na2O_wt%",
                "K2O": "K2O_wt%",
                "MgO": "MgO_wt%",
            },
            "units": {
                "major_oxides": "wt%",
                "trace_elements": "ppm",
            },
        },
        "output": {
            "directory": "outputs/submission",
            "report_profile": "shareable",
        },
        "presets": {
            "journal-main": {
                "extends": "publication-double-column",
                "style": {"width_mm": 183, "height_mm": 120, "dpi": 600},
            }
        },
        "confirmations": {
            "input_structure_reviewed": True,
            "column_mapping_reviewed": True,
            "units_reviewed": True,
            "plotted_data_export_reviewed": True,
        },
        "tasks": [
            {
                "id": "ree-main",
                "diagram": "ree",
                "stem": "figure-ree",
                "preset": "journal-main",
                "parameters": {
                    "reference": "chondrite-sm89",
                    "elements": elements,
                    "groups": "all",
                },
                "confirmations": {},
            },
            {
                "id": "harker-main",
                "diagram": "harker",
                "stem": "figure-harker",
                "preset": "publication-double-column",
                "parameters": {
                    "x": "SiO2",
                    "y": ["MgO", "K2O"],
                    "groups": ["Suite A", "Suite B"],
                },
                "confirmations": {},
            },
            {
                "id": "tas-main",
                "diagram": "tas",
                "stem": "figure-tas",
                "preset": "review-preview",
                "parameters": {
                    "composition_basis": "anhydrous-normalized",
                    "groups": "all",
                },
                "confirmations": {
                    "volcanic_samples": True,
                    "composition_basis_reviewed": True,
                },
            },
        ],
    }


def issue_codes(result: dict) -> set[str]:
    return {item["code"] for item in result["issues"]}


def test_version_and_registry_are_fixed_and_json_ready() -> None:
    assert VERSION == "0.9.0-rc1"
    assert diagram_ids() == (
        "ree", "spider", "harker", "tas", "k2o-sio2", "xy"
    )
    assert set(DIAGRAMS) == {
        "ree", "spider", "harker", "tas", "k2o-sio2", "xy"
    }
    assert BUILTIN_STYLE_PRESETS == (
        "publication-double-column",
        "publication-single-column",
        "review-preview",
    )

    snapshot = registry_snapshot()
    json.dumps(snapshot, ensure_ascii=False)
    assert all(
        item["output_contract"]["source_data_by_profile"]
        == {"shareable": False, "local-reproducible": True}
        for item in snapshot
    )
    required_fields = {
        "id",
        "api_version",
        "display_name_zh",
        "display_name_en",
        "operation",
        "input_profile",
        "adapter",
        "inspector_handler",
        "runner_handler",
        "scientific_parameter_schema",
        "style_parameter_schema",
        "required_confirmations",
        "required_assets",
        "output_contract",
        "privacy_contract",
        "adapter_version",
    }
    assert all(set(record) == required_fields for record in snapshot)
    assert get_diagram("tas").required_confirmations == (
        "volcanic_samples",
        "composition_basis_reviewed",
    )
    assert get_diagram("k2o-sio2").required_assets == (
        "assets/classification/k2o-sio2-pt76-r89-original.json",
    )
    with pytest.raises(RegistryError):
        get_diagram("sr-nd")


def test_registry_handlers_are_imported_only_when_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []

    class FakeModule:
        @staticmethod
        def plot_path() -> None:
            return None

    def fake_import(name: str):
        imported.append(name)
        return FakeModule

    monkeypatch.setattr(importlib, "import_module", fake_import)
    spec = get_diagram("ree")
    assert imported == []
    handler = resolve_handler("ree", "runner")
    assert handler is FakeModule.plot_path
    assert imported == ["plot_ree"]
    with pytest.raises(RegistryError):
        resolve_handler("ree", "normalizer")

    def missing_import(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", missing_import)
    with pytest.raises(RegistryError, match="could not be imported"):
        resolve_handler("ree", "runner")


def test_registry_metadata_is_deeply_immutable() -> None:
    schema = get_diagram("ree").scientific_parameter_schema

    with pytest.raises(TypeError):
        schema["new"] = True
    with pytest.raises(TypeError):
        schema["reference"]["enum"] = ("unreviewed",)


def test_valid_recipe_normalizes_to_json_ready_structure() -> None:
    result = validate_recipe(valid_recipe())

    assert result["status"] == "ready"
    assert result["issues"] == []
    assert result["recipe"]["tasks"][1]["parameters"]["y"] == [
        "MgO",
        "K2O",
    ]
    assert result["recipe"]["columns"]["mapping"]["La"] == "La_ppm"
    assert result["recipe"]["quality"] == {
        "duplicate_sample_ids": "error",
        "non_numeric_values": "error",
        "major_oxide_total": None,
    }
    assert result["recipe"]["derived_variables"] == []
    assert result["recipe"]["data_basis"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_quality_and_same_unit_ratio_are_normalized() -> None:
    recipe = valid_recipe()
    recipe["quality"] = {
        "duplicate_sample_ids": "error",
        "non_numeric_values": "review",
        "major_oxide_total": {
            "analytes": ["SiO2", "Na2O", "K2O", "MgO"],
            "lower": 95,
            "upper": 105,
            "composition_basis": "as-reported",
            "severity": "review",
        },
    }
    recipe["derived_variables"] = [
        {
            "id": "K2O_Na2O",
            "operation": "ratio",
            "numerator": "K2O",
            "denominator": "Na2O",
            "input_unit": "wt%",
        }
    ]
    recipe["confirmations"]["data_quality_reviewed"] = True

    result = validate_recipe(recipe)

    assert result["status"] == "ready"
    assert result["recipe"]["quality"]["major_oxide_total"]["lower"] == 95.0
    assert result["recipe"]["derived_variables"] == [
        {
            "id": "K2O_Na2O",
            "operation": "ratio",
            "numerator": "K2O",
            "denominator": "Na2O",
            "input_unit": "wt%",
        }
    ]
    assert result["recipe"]["confirmations"]["data_quality_reviewed"] is True


def test_k2o_sio2_requires_explicit_anhydrous_basis_and_confirmations() -> None:
    recipe = valid_recipe()
    recipe["data_basis"] = {
        "operation": "normalize-to-100",
        "basis": "anhydrous-100",
        "analytes": ["SiO2", "Na2O", "K2O", "MgO"],
    }
    recipe["confirmations"]["data_basis_reviewed"] = True
    recipe["tasks"] = [
        {
            "id": "k2o-main",
            "diagram": "k2o-sio2",
            "stem": "figure-k2o",
            "preset": "journal-main",
            "parameters": {
                "composition_basis": "anhydrous-normalized",
                "groups": "all",
            },
            "confirmations": {
                "volcanic_samples": True,
                "composition_basis_reviewed": True,
            },
        }
    ]

    result = validate_recipe(recipe)

    assert result["status"] == "ready"
    assert result["recipe"]["data_basis"]["analytes"] == [
        "SiO2",
        "Na2O",
        "K2O",
        "MgO",
    ]

    missing_confirmation = valid_recipe()
    missing_confirmation["data_basis"] = dict(recipe["data_basis"])
    invalid = validate_recipe(missing_confirmation)
    assert invalid["status"] == "invalid"
    assert "E305" in issue_codes(invalid)

    missing_basis = valid_recipe()
    missing_basis["tasks"] = recipe["tasks"]
    invalid = validate_recipe(missing_basis)
    assert invalid["status"] == "invalid"
    assert "E316" in issue_codes(invalid)


def test_data_basis_rejects_volatile_totals_and_double_counted_iron() -> None:
    recipe = valid_recipe()
    recipe["columns"]["mapping"].update(
        {
            "LOI": "LOI_wt%",
            "FeOT": "FeOT_wt%",
            "Fe2O3": "Fe2O3_wt%",
        }
    )
    recipe["data_basis"] = {
        "operation": "normalize-to-100",
        "basis": "anhydrous-100",
        "analytes": ["SiO2", "K2O", "LOI", "FeOT", "Fe2O3"],
    }
    recipe["confirmations"]["data_basis_reviewed"] = True

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E316" in issue_codes(result)


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda recipe: recipe.update(
                {
                    "derived_variables": [
                        {
                            "id": "unsafe",
                            "operation": "expression",
                            "numerator": "K2O",
                            "denominator": "Na2O",
                        }
                    ]
                }
            ),
            "E315",
        ),
        (
            lambda recipe: recipe.update(
                {
                    "derived_variables": [
                        {
                            "id": "SiO2_La",
                            "operation": "ratio",
                            "numerator": "SiO2",
                            "denominator": "La",
                        }
                    ]
                }
            ),
            "E315",
        ),
        (
            lambda recipe: recipe.update(
                {
                    "quality": {"duplicate_sample_ids": "review"}
                }
            ),
            "E306",
        ),
        (
            lambda recipe: recipe.update(
                {
                    "quality": {
                        "major_oxide_total": {
                            "analytes": ["SiO2", "La"],
                            "lower": 105,
                            "upper": 95,
                            "composition_basis": "unknown",
                            "severity": "ignore",
                        }
                    }
                }
            ),
            "E313",
        ),
    ],
)
def test_unsafe_quality_or_derived_recipe_is_rejected(mutator, expected_code: str) -> None:
    recipe = valid_recipe()
    mutator(recipe)

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert expected_code in issue_codes(result)


def test_excel_sheet_name_preserves_significant_edge_spaces() -> None:
    recipe = valid_recipe()
    recipe["input"]["sheet"] = "Table S1 "

    result = validate_recipe(recipe)

    assert result["status"] == "ready"
    assert result["recipe"]["input"]["sheet"] == "Table S1 "


@pytest.mark.parametrize(
    "filename",
    [
        "geoskills_ree_workflow.yaml",
        "geoskills_spider_workflow.yaml",
        "geoskills_major_workflow.yaml",
        "geoskills_xy_workflow.yaml",
    ],
)
def test_bundled_workflow_recipes_remain_valid(filename: str) -> None:
    path = ROOT / "skills" / "geoskills" / "examples" / filename

    result = load_recipe(path)

    assert result["status"] == "ready"


def test_user_recipe_template_starts_with_all_confirmations_disabled() -> None:
    path = (
        ROOT
        / "skills"
        / "geoskills"
        / "examples"
        / "user_recipe_template.yaml"
    )

    result = load_recipe(path)

    assert result["status"] == "needs_review"
    assert result["recipe"] is not None
    assert set(result["recipe"]["confirmations"].values()) == {False}


def test_yaml_loader_is_safe_single_document_and_size_limited(
    tmp_path: Path,
) -> None:
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        yaml.safe_dump(valid_recipe(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    assert load_recipe(recipe_path)["status"] == "ready"

    multiple = tmp_path / "multiple.yaml"
    multiple.write_text("---\na: 1\n---\nb: 2\n", encoding="utf-8")
    assert issue_codes(load_recipe(multiple)) == {"E302"}

    unsafe = tmp_path / "unsafe.yaml"
    unsafe.write_text(
        "!!python/object/apply:os.system ['echo unsafe']\n",
        encoding="utf-8",
    )
    assert issue_codes(load_recipe(unsafe)) == {"E301"}

    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b" " * (MAX_RECIPE_BYTES + 1))
    assert issue_codes(load_recipe(oversized)) == {"E300"}


@pytest.mark.parametrize(
    "bad_path",
    [
        "https://example.com/data.csv",
        "C:/private/data.csv",
        r"\\server\share\data.csv",
        "~/data.csv",
        "$env:DATA/data.csv",
        "data/$env:DATA/data.csv",
        "../data.csv",
        "data/*.csv",
    ],
)
def test_recipe_rejects_nonlocal_or_unsafe_member_paths(
    bad_path: str,
) -> None:
    recipe = valid_recipe()
    recipe["input"]["file"] = bad_path
    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E307" in issue_codes(result)


@pytest.mark.parametrize(
    "bad_output",
    [".git/plots", ".codex/plots", "skills/output", "results/tests"],
)
def test_recipe_rejects_protected_output_directories(
    bad_output: str,
) -> None:
    recipe = valid_recipe()
    recipe["output"]["directory"] = bad_output

    assert "E307" in issue_codes(validate_recipe(recipe))


@pytest.mark.parametrize(
    "bad_output",
    [
        ".git./plots",
        ".codex /plots",
        "results/tests.",
        "NUL",
        "safe/COM1.txt",
    ],
)
def test_windows_equivalent_protected_or_device_paths_are_rejected(
    bad_output: str,
) -> None:
    recipe = valid_recipe()
    recipe["output"]["directory"] = bad_output

    assert "E307" in issue_codes(validate_recipe(recipe))


def test_unknown_fields_and_wrong_mapping_direction_are_errors() -> None:
    recipe = valid_recipe()
    recipe["surprise"] = True
    recipe["tasks"][0]["parameters"]["secret"] = "guess"
    recipe["columns"]["mapping"] = {"La_ppm": "La"}

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert {"E304", "E313"}.issubset(issue_codes(result))
    assert result["recipe"] is None


def test_units_must_cover_every_canonical_mapping() -> None:
    recipe = valid_recipe()
    recipe["columns"]["units"] = {"major_oxides": "wt%"}

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E313" in issue_codes(result)
    assert any(
        item.get("field") == "columns.units.La"
        for item in result["issues"]
    )


def test_windows_casefold_deduplicates_task_ids_and_stems() -> None:
    recipe = valid_recipe()
    duplicate = dict(recipe["tasks"][0])
    duplicate["id"] = "REE-MAIN"
    duplicate["stem"] = "FIGURE-REE"
    duplicate["parameters"] = dict(recipe["tasks"][0]["parameters"])
    duplicate["confirmations"] = {}
    recipe["tasks"].append(duplicate)

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E308" in issue_codes(result)
    duplicate_messages = [
        item["message"] for item in result["issues"] if item["code"] == "E308"
    ]
    assert any("任务 ID" in message for message in duplicate_messages)
    assert any("stem" in message for message in duplicate_messages)


def test_recipe_allows_at_most_32_tasks() -> None:
    recipe = valid_recipe()
    base = recipe["tasks"][0]
    recipe["tasks"] = []
    for index in range(MAX_TASKS + 1):
        task = {
            **base,
            "id": f"task-{index}",
            "stem": f"figure-{index}",
            "parameters": dict(base["parameters"]),
            "confirmations": {},
        }
        recipe["tasks"].append(task)

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E309" in issue_codes(result)


def test_scientific_parameters_are_diagram_specific_and_explicit() -> None:
    recipe = valid_recipe()
    recipe["tasks"][0]["parameters"]["reference"] = "user-guessed"
    recipe["tasks"][0]["parameters"]["elements"] = ["La", "Ce"]
    recipe["tasks"][1]["parameters"]["x"] = ""

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert "E311" in issue_codes(result)


def spider_only_recipe(elements: list[str]) -> dict:
    recipe = valid_recipe()
    recipe["tasks"] = [
        {
            "id": "spider-main",
            "diagram": "spider",
            "stem": "figure-spider",
            "preset": "journal-main",
            "parameters": {
                "reference": "pm-sm89-modified",
                "elements": elements,
                "groups": "all",
            },
            "confirmations": {},
        }
    ]
    return recipe


def test_spider_accepts_only_three_reviewed_oxide_alternatives() -> None:
    recipe = spider_only_recipe(["K", "P", "Ti", "La", "Ce"])
    mapping = recipe["columns"]["mapping"]
    mapping.update(
        {
            "P2O5": "P2O5_wt%",
            "TiO2": "TiO2_wt%",
        }
    )

    result = validate_recipe(recipe)

    assert result["status"] == "ready"
    assert result["recipe"]["tasks"][0]["parameters"]["elements"] == [
        "K",
        "P",
        "Ti",
        "La",
        "Ce",
    ]


def test_spider_still_accepts_direct_k_p_ti_ppm_mappings() -> None:
    recipe = spider_only_recipe(["K", "P", "Ti", "La", "Ce"])
    mapping = recipe["columns"]["mapping"]
    mapping.pop("K2O")
    mapping.update({"K": "K_ppm", "P": "P_ppm", "Ti": "Ti_ppm"})

    result = validate_recipe(recipe)

    assert result["status"] == "ready"


def test_spider_oxide_alternatives_do_not_hide_other_missing_elements() -> None:
    recipe = spider_only_recipe(["K", "P", "Ti", "La", "Nb"])
    recipe["columns"]["mapping"].update(
        {
            "P2O5": "P2O5_wt%",
            "TiO2": "TiO2_wt%",
        }
    )

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    missing = [
        item
        for item in result["issues"]
        if item["code"] == "E313"
        and item.get("field", "").endswith("elements[4]")
    ]
    assert len(missing) == 1
    assert "Nb" in missing[0]["message"]


@pytest.mark.parametrize(
    ("field_path", "bad_value"),
    [
        (("input", "layout"), ["auto"]),
        (("output", "report_profile"), ["shareable"]),
        (("tasks", 0, "diagram"), ["ree"]),
        (("tasks", 0, "parameters", "reference"), ["chondrite-sm89"]),
    ],
)
def test_unhashable_enum_values_return_issues_instead_of_crashing(
    field_path: tuple[object, ...],
    bad_value: object,
) -> None:
    recipe = valid_recipe()
    target = recipe
    for part in field_path[:-1]:
        target = target[part]
    target[field_path[-1]] = bad_value

    result = validate_recipe(recipe)

    assert result["status"] == "invalid"
    assert result["issues"]


def test_extreme_numbers_return_structured_errors(
    tmp_path: Path,
) -> None:
    recipe = valid_recipe()
    recipe["presets"]["journal-main"]["style"]["width_mm"] = 10**10_000
    direct = validate_recipe(recipe)
    assert direct["status"] == "invalid"
    assert "E314" in issue_codes(direct)

    yaml_path = tmp_path / "huge-integer.yaml"
    yaml_path.write_text(
        "schema_version: " + ("9" * 5000) + "\n",
        encoding="utf-8",
    )
    loaded = load_recipe(yaml_path)
    assert loaded["status"] == "invalid"
    assert "E301" in issue_codes(loaded)


def test_false_top_level_confirmation_returns_needs_review() -> None:
    recipe = valid_recipe()
    recipe["confirmations"]["units_reviewed"] = False

    result = validate_recipe(recipe)

    assert result["status"] == "needs_review"
    assert issue_codes(result) == {"R312"}
    assert result["recipe"] is not None


def test_tas_requires_volcanic_and_composition_confirmations() -> None:
    recipe = valid_recipe()
    recipe["tasks"][2]["confirmations"]["volcanic_samples"] = False

    result = validate_recipe(recipe)

    assert result["status"] == "needs_review"
    assert "R312" in issue_codes(result)


def test_as_reported_tas_requires_provisional_acceptance() -> None:
    recipe = valid_recipe()
    task = recipe["tasks"][2]
    task["parameters"]["composition_basis"] = "as-reported"

    missing = validate_recipe(recipe)
    assert missing["status"] == "invalid"
    assert "E305" in issue_codes(missing)

    task["confirmations"]["provisional_classification_accepted"] = False
    pending = validate_recipe(recipe)
    assert pending["status"] == "needs_review"
    assert "R312" in issue_codes(pending)

    task["confirmations"]["provisional_classification_accepted"] = True
    ready = validate_recipe(recipe)
    assert ready["status"] == "ready"
