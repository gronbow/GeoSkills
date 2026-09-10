from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core import adapters, export, workflow  # noqa: E402
from geoskills_core.export import (  # noqa: E402
    AtomicDirectory,
    BundleExportError,
)
from geoskills_core.workflow import create_plan, execute_plan  # noqa: E402


REE_ELEMENTS = ["La", "Ce", "Pr", "Nd", "Sm"]


def _ree_recipe(
    *,
    input_file: str = "input.csv",
    output_directory: str = "bundle",
    task_count: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": "geoskills.recipe/v1",
        "input": {
            "file": input_file,
            "sheet": None,
            "layout": "row-per-sample",
        },
        "columns": {
            "sample_id": "Sample",
            "group": "Group",
            "mapping": {
                element: f"{element}_ppm" for element in REE_ELEMENTS
            },
            "units": {
                "major_oxides": "wt%",
                "trace_elements": "ppm",
            },
        },
        "output": {
            "directory": output_directory,
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
                "id": f"ree-{index + 1}",
                "diagram": "ree",
                "stem": f"figure-ree-{index + 1}",
                "preset": "review-preview",
                "parameters": {
                    "reference": "chondrite-sm89",
                    "elements": REE_ELEMENTS,
                    "groups": "all",
                },
                "confirmations": {},
            }
            for index in range(task_count)
        ],
    }


def _write_recipe(tmp_path: Path, recipe: dict[str, Any]) -> Path:
    path = tmp_path / "recipe.yaml"
    path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _prepare_ree_recipe(
    tmp_path: Path,
    *,
    output_directory: str = "bundle",
    task_count: int = 1,
) -> Path:
    shutil.copyfile(EXAMPLES / "synthetic_ree_data.csv", tmp_path / "input.csv")
    return _write_recipe(
        tmp_path,
        _ree_recipe(
            output_directory=output_directory,
            task_count=task_count,
        ),
    )


def _plan_ready(tmp_path: Path) -> tuple[Path, Path]:
    recipe_path = _prepare_ree_recipe(tmp_path)
    plan_path = tmp_path / "plan.json"
    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    return recipe_path, plan_path


def _issue_codes(result: dict[str, Any]) -> set[str]:
    return {str(item["code"]) for item in result.get("issues", [])}


def _write_ree_rows(
    path: Path,
    *,
    row_count: int,
    unique_groups: int = 1,
) -> None:
    frame = pd.DataFrame(
        {
            "Sample": [f"sample-{index + 1}" for index in range(row_count)],
            "Group": [
                f"group-{(index % unique_groups) + 1}"
                for index in range(row_count)
            ],
            **{
                f"{element}_ppm": [float(index + 1)] * row_count
                for index, element in enumerate(REE_ELEMENTS)
            },
        }
    )
    frame.to_csv(path, index=False)


def test_output_directory_cannot_be_recipe_root(tmp_path: Path) -> None:
    shutil.copyfile(EXAMPLES / "synthetic_ree_data.csv", tmp_path / "input.csv")
    recipe_path = _write_recipe(
        tmp_path,
        _ree_recipe(output_directory="."),
    )
    plan_path = tmp_path / "plan.json"

    result = create_plan(recipe_path, plan_path)

    assert result["status"] == "error"
    assert "E307" in _issue_codes(result)
    assert not plan_path.exists()
    assert (tmp_path / "input.csv").is_file()


def test_plan_blocks_excessive_pattern_artists_without_sampling(
    tmp_path: Path,
) -> None:
    _write_ree_rows(tmp_path / "input.csv", row_count=2_001)
    recipe_path = _write_recipe(tmp_path, _ree_recipe())

    result = create_plan(recipe_path, tmp_path / "plan.json")

    assert result["status"] == "blocked"
    assert "E424" in _issue_codes(result)
    assert not (tmp_path / "bundle").exists()


def test_plan_blocks_excessive_groups_without_merging(
    tmp_path: Path,
) -> None:
    _write_ree_rows(
        tmp_path / "input.csv",
        row_count=65,
        unique_groups=65,
    )
    recipe_path = _write_recipe(tmp_path, _ree_recipe())

    result = create_plan(recipe_path, tmp_path / "plan.json")

    assert result["status"] == "blocked"
    assert "E423" in _issue_codes(result)
    assert not (tmp_path / "bundle").exists()


def test_input_inside_output_is_blocked_without_touching_source(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "bundle"
    source_dir.mkdir()
    source_path = source_dir / "input.csv"
    shutil.copyfile(EXAMPLES / "synthetic_ree_data.csv", source_path)
    original = source_path.read_bytes()
    recipe_path = _write_recipe(
        tmp_path,
        _ree_recipe(
            input_file="bundle/input.csv",
            output_directory="bundle",
        ),
    )
    plan_path = tmp_path / "plan.json"

    planned = create_plan(recipe_path, plan_path)

    assert planned["status"] == "blocked"
    assert "E820" in _issue_codes(planned)
    assert source_path.read_bytes() == original
    assert plan_path.is_file()


def test_plan_cannot_replace_recipe_even_with_overwrite(
    tmp_path: Path,
) -> None:
    recipe_path = _prepare_ree_recipe(tmp_path)
    original = recipe_path.read_bytes()

    result = create_plan(recipe_path, recipe_path, overwrite=True)

    assert result["status"] == "error"
    assert "E822" in _issue_codes(result)
    assert recipe_path.read_bytes() == original


def test_plan_cannot_be_written_inside_final_output(tmp_path: Path) -> None:
    recipe_path = _prepare_ree_recipe(tmp_path)
    plan_path = tmp_path / "bundle" / "plan.json"

    result = create_plan(recipe_path, plan_path)

    assert result["status"] == "error"
    assert "E822" in _issue_codes(result)
    assert not plan_path.exists()


def test_non_geoskills_file_cannot_be_overwritten_as_plan(
    tmp_path: Path,
) -> None:
    recipe_path = _prepare_ree_recipe(tmp_path)
    plan_path = tmp_path / "plan.json"
    sentinel = b"not a GeoSkills plan\n"
    plan_path.write_bytes(sentinel)

    result = create_plan(recipe_path, plan_path, overwrite=True)

    assert result["status"] == "error"
    assert "E821" in _issue_codes(result)
    assert plan_path.read_bytes() == sentinel


def test_ordinary_directory_cannot_be_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)
    target = tmp_path / "bundle"
    target.mkdir()
    sentinel = target / "user-file.txt"
    sentinel.write_text("keep", encoding="utf-8")

    def forbidden_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("runner must not start for an unowned directory")

    monkeypatch.setattr(workflow, "run_task", forbidden_runner)

    result = execute_plan(recipe_path, plan_path, overwrite=True)

    assert result["status"] == "blocked"
    assert "E826" in _issue_codes(result)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_existing_output_without_overwrite_stops_before_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)
    target = tmp_path / "bundle"
    target.mkdir()
    sentinel = target / "user-file.txt"
    sentinel.write_text("keep", encoding="utf-8")

    def forbidden_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("runner must not start without overwrite approval")

    monkeypatch.setattr(workflow, "run_task", forbidden_runner)

    result = execute_plan(recipe_path, plan_path)

    assert result["status"] == "blocked"
    assert "E825" in _issue_codes(result)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_failed_overwrite_preserves_valid_previous_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)
    assert execute_plan(recipe_path, plan_path)["status"] == "ready"
    target = tmp_path / "bundle"
    previous_svg = target / "ree-1" / "figure-ree-1.svg"
    previous_hash = workflow.sha256_file(previous_svg)

    def failed_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "error",
            "issues": [
                {
                    "code": "E-test",
                    "severity": "error",
                    "message": "synthetic failure",
                }
            ],
        }

    monkeypatch.setattr(workflow, "run_task", failed_runner)

    result = execute_plan(recipe_path, plan_path, overwrite=True)

    assert result["status"] == "error"
    assert workflow.sha256_file(previous_svg) == previous_hash


@pytest.mark.parametrize("change", ["extra-file", "extra-directory", "edited-file", "missing-file", "edited-qa"])
def test_overwrite_preserves_user_changes(tmp_path: Path, monkeypatch, change: str) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)
    assert execute_plan(recipe_path, plan_path)["status"] == "ready"
    target = tmp_path / "bundle"
    assert workflow._existing_output_issue(target, overwrite=True) is None
    figure = target / "ree-1" / "figure-ree-1.svg"
    if change == "extra-file":
        (target / "ree-1" / "private-notes.txt").write_text("keep", encoding="utf-8")
    elif change == "extra-directory":
        (target / "notes").mkdir()
    elif change == "edited-file":
        data = figure.read_bytes()
        figure.write_bytes(b"!" + data[1:])  # Same length: require a hash check.
    elif change == "edited-qa":
        (target / "run.qa.md").write_text("My notes", encoding="utf-8")
    else:
        figure.unlink()
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    monkeypatch.setattr(workflow, "run_task", lambda *a, **kw: pytest.fail("must block before plotting"))
    result = execute_plan(recipe_path, plan_path, overwrite=True)
    assert "E826" in _issue_codes(result)
    assert result["status"] == "blocked"
    assert before == {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}


def test_unchanged_complete_bundle_can_be_overwritten(tmp_path: Path) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)
    assert execute_plan(recipe_path, plan_path)["status"] == "ready"
    assert execute_plan(recipe_path, plan_path, overwrite=True)["status"] == "ready"
    assert workflow._existing_output_issue(tmp_path / "bundle", overwrite=True) is None


def test_atomic_directory_keeps_backup_when_restore_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "bundle"
    target.mkdir()
    (target / "old.txt").write_text("recover me", encoding="utf-8")
    real_replace = os.replace

    with pytest.raises(BundleExportError):
        with AtomicDirectory(target, overwrite=True) as transaction:
            staging = transaction.staging_dir
            (staging / "new.txt").write_text("new", encoding="utf-8")

            def fail_promotion_and_restore(
                source: str | os.PathLike[str],
                destination: str | os.PathLike[str],
            ) -> None:
                source_path = Path(source).resolve()
                destination_path = Path(destination).resolve()
                if (
                    source_path == staging
                    and destination_path == target.resolve()
                ):
                    raise OSError("synthetic promotion failure")
                if (
                    source_path.name.startswith(".geoskills-run-backup-")
                    and destination_path == target.resolve()
                ):
                    raise OSError("synthetic restore failure")
                real_replace(source, destination)

            monkeypatch.setattr(export.os, "replace", fail_promotion_and_restore)
            transaction.commit()

    backups = list(tmp_path.glob(".geoskills-run-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "old.txt").read_text(encoding="utf-8") == "recover me"
    assert not target.exists()


@pytest.mark.parametrize(
    "document",
    [
        {
            "schema_version": "geoskills.plan/v1",
            "plan_id": "not-a-sha256",
            "status": "ready",
            "tasks": [{"id": "ree-1"}],
        },
        {
            "schema_version": "geoskills.plan/v1",
            "plan_id": "0" * 64,
            "status": "ready",
            "tasks": [{"id": "Ree-1"}, {"id": "ree-1"}],
        },
        {
            "schema_version": "geoskills.plan/v1",
            "plan_id": "0" * 64,
            "status": "not-a-status",
            "tasks": [{"id": "ree-1"}],
        },
    ],
    ids=[
        "invalid-plan-id",
        "duplicate-casefold-task-id",
        "invalid-status",
    ],
)
def test_malformed_plan_returns_structured_error(
    tmp_path: Path,
    document: dict[str, Any],
) -> None:
    recipe_path = _prepare_ree_recipe(tmp_path)
    plan_path = tmp_path / "malformed-plan.json"
    plan_path.write_text(json.dumps(document), encoding="utf-8")

    result = execute_plan(recipe_path, plan_path)

    assert result["status"] == "error"
    assert _issue_codes(result) == {"E807"}
    assert not (tmp_path / "bundle").exists()


def test_unexpected_runner_file_rejects_whole_bundle_without_path_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)
    secret_value = "PRIVATE-SAMPLE-VALUE"

    def runner_with_extra_file(
        task: dict[str, Any],
        prepared: Any,
        *,
        output_dir: Path,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True)
        (output_dir / "secret-debug.csv").write_text(
            secret_value,
            encoding="utf-8",
        )
        return {"status": "ready", "issues": [], "plot": {}}

    monkeypatch.setattr(workflow, "run_task", runner_with_extra_file)

    result = execute_plan(recipe_path, plan_path)
    payload = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "error"
    assert "E823" in _issue_codes(result)
    assert not (tmp_path / "bundle").exists()
    assert secret_value not in payload
    assert str(tmp_path.resolve()) not in payload
    assert tmp_path.name not in payload


def test_invalid_figure_is_rejected_without_exposing_temporary_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)

    def runner_with_fake_figures(
        task: dict[str, Any],
        prepared: Any,
        *,
        output_dir: Path,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True)
        stem = str(task["stem"])
        (output_dir / f"{stem}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><text>x</text></svg>',
            encoding="utf-8",
        )
        (output_dir / f"{stem}.pdf").write_bytes(
            b"%PDF-1.4\n/CIDFontType2\n%%EOF\n"
        )
        (output_dir / f"{stem}.png").write_text(
            "not a png",
            encoding="utf-8",
        )
        (output_dir / f"{stem}.tiff").write_text(
            "not a tiff",
            encoding="utf-8",
        )
        return {"status": "ready", "issues": [], "plot": {}}

    monkeypatch.setattr(workflow, "run_task", runner_with_fake_figures)

    result = execute_plan(recipe_path, plan_path)
    payload = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "error"
    assert "E824" in _issue_codes(result)
    assert not (tmp_path / "bundle").exists()
    assert str(tmp_path.resolve()) not in payload
    assert tmp_path.name not in payload
    assert ".geoskills-run-stage-" not in payload


def test_review_result_includes_r804_in_api_and_saved_report(
    tmp_path: Path,
) -> None:
    shutil.copyfile(
        EXAMPLES / "synthetic_major_element_data.csv",
        tmp_path / "synthetic_major_element_data.csv",
    )
    recipe = yaml.safe_load(
        (EXAMPLES / "geoskills_major_workflow.yaml").read_text(
            encoding="utf-8"
        )
    )
    recipe["output"]["directory"] = "bundle"
    recipe["presets"]["journal-main"]["style"]["dpi"] = 300
    tas_task = recipe["tasks"][1]
    tas_task["parameters"]["composition_basis"] = "as-reported"
    tas_task["confirmations"]["provisional_classification_accepted"] = True
    recipe["tasks"] = [tas_task]
    recipe_path = _write_recipe(tmp_path, recipe)
    plan_path = tmp_path / "plan.json"
    assert create_plan(recipe_path, plan_path)["status"] == "ready"

    result = execute_plan(recipe_path, plan_path)
    report = json.loads(
        (tmp_path / "bundle" / "run.report.json").read_text(encoding="utf-8")
    )

    assert result["status"] == "review"
    assert "R804" in _issue_codes(result)
    assert "R804" in _issue_codes(report)


def test_execute_uses_one_snapshot_when_source_changes_after_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe_path, plan_path = _plan_ready(tmp_path)
    source_path = tmp_path / "input.csv"
    marker = "TOCTOU-MUTATION"
    real_copyfile = shutil.copyfile
    mutation_count = 0
    observed_canonical = ""
    real_run_task = workflow.run_task

    def copy_then_mutate(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        nonlocal mutation_count
        result = real_copyfile(source, destination, *args, **kwargs)
        if (
            mutation_count == 0
            and Path(destination).name.startswith("source_snapshot")
        ):
            mutation_count += 1
            with Path(source).open("a", encoding="utf-8") as handle:
                handle.write(f"\n{marker}\n")
        return result

    def observing_runner(
        task: dict[str, Any],
        prepared: Any,
        *,
        output_dir: Path,
    ) -> dict[str, Any]:
        nonlocal observed_canonical
        observed_canonical = prepared.path.read_text(encoding="utf-8")
        return real_run_task(task, prepared, output_dir=output_dir)

    monkeypatch.setattr(adapters.shutil, "copyfile", copy_then_mutate)
    monkeypatch.setattr(workflow, "run_task", observing_runner)

    result = execute_plan(recipe_path, plan_path)

    assert mutation_count == 1
    assert marker in source_path.read_text(encoding="utf-8")
    assert marker not in observed_canonical
    assert result["status"] == "ready"
    assert (tmp_path / "bundle" / "ree-1" / "figure-ree-1.svg").is_file()


def test_local_reproducible_blocks_spreadsheet_formula_labels_without_leak(
    tmp_path: Path,
) -> None:
    frame = pd.read_csv(EXAMPLES / "synthetic_ree_data.csv")
    secret_formula = "=HYPERLINK(\"https://invalid.example\",\"private\")"
    frame.loc[0, "Sample"] = secret_formula
    frame.to_csv(tmp_path / "input.csv", index=False)
    recipe = _ree_recipe()
    recipe["output"]["report_profile"] = "local-reproducible"
    recipe_path = _write_recipe(tmp_path, recipe)

    result = workflow.build_plan(recipe_path)
    payload = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "blocked"
    assert "E422" in _issue_codes(result)
    risk = result["plan"]["data_processing"]["quality"]["summary"][
        "spreadsheet_formula_risk"
    ]
    assert risk == {"sample_id_count": 1, "group_count": 0, "total_count": 1}
    assert secret_formula not in payload


def test_shareable_profile_does_not_block_formula_like_sample_label(
    tmp_path: Path,
) -> None:
    frame = pd.read_csv(EXAMPLES / "synthetic_ree_data.csv")
    frame.loc[0, "Sample"] = "=1+1"
    frame.to_csv(tmp_path / "input.csv", index=False)
    recipe_path = _write_recipe(tmp_path, _ree_recipe())

    result = workflow.build_plan(recipe_path)

    assert result["status"] == "ready"
    assert "E422" not in _issue_codes(result)
    assert result["plan"]["data_processing"]["quality"]["summary"][
        "spreadsheet_formula_risk"
    ]["total_count"] == 1
