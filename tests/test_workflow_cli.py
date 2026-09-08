from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
CLI = SCRIPTS / "geoskills.py"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.workflow import create_plan, execute_plan  # noqa: E402


REE_ELEMENTS = ["La", "Ce", "Pr", "Nd", "Sm"]


def ree_recipe(
    *,
    report_profile: str = "shareable",
    confirmed: bool = True,
    tasks: int = 1,
) -> dict:
    return {
        "schema_version": "geoskills.recipe/v1",
        "input": {
            "file": "input.csv",
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
            "directory": "bundle",
            "report_profile": report_profile,
        },
        "presets": {},
        "confirmations": {
            "input_structure_reviewed": confirmed,
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
            for index in range(tasks)
        ],
    }


def prepare_recipe(
    tmp_path: Path,
    *,
    report_profile: str = "shareable",
    confirmed: bool = True,
    tasks: int = 1,
) -> Path:
    shutil.copyfile(
        EXAMPLES / "synthetic_ree_data.csv",
        tmp_path / "input.csv",
    )
    path = tmp_path / "recipe.yaml"
    path.write_text(
        yaml.safe_dump(
            ree_recipe(
                report_profile=report_profile,
                confirmed=confirmed,
                tasks=tasks,
            ),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def prepare_spider_recipe(tmp_path: Path) -> Path:
    shutil.copyfile(
        EXAMPLES / "synthetic_spider_data.csv",
        tmp_path / "input.csv",
    )
    elements = ["Rb", "Ba", "Th", "U", "Nb", "Ta", "K", "P", "Ti"]
    recipe = {
        "schema_version": "geoskills.recipe/v1",
        "input": {
            "file": "input.csv",
            "sheet": None,
            "layout": "row-per-sample",
        },
        "columns": {
            "sample_id": "Sample",
            "group": "Group",
            "mapping": {
                "Rb": "Rb_ppm",
                "Ba": "Ba_ppm",
                "Th": "Th_ppm",
                "U": "U_ppm",
                "Nb": "Nb_ppm",
                "Ta": "Ta_ppm",
                "K2O": "K2O_wt%",
                "P2O5": "P2O5_wt%",
                "TiO2": "TiO2_wt%",
            },
            "units": {
                "major_oxides": "wt%",
                "trace_elements": "ppm",
            },
        },
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
                "id": "spider-main",
                "diagram": "spider",
                "stem": "figure-spider",
                "preset": "review-preview",
                "parameters": {
                    "reference": "pm-sm89-modified",
                    "elements": elements,
                    "groups": "all",
                },
                "confirmations": {},
            }
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def prepare_major_multitask_recipe(tmp_path: Path) -> Path:
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
    path = tmp_path / "recipe.yaml"
    path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def parse_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_version_works_without_site_packages() -> None:
    result = subprocess.run(
        [sys.executable, "-S", str(CLI), "version"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    report = parse_stdout(result)
    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["result"]["tool_version"] == "0.9.0-rc1"


def test_self_check_is_machine_readable_and_private_by_default() -> None:
    result = run_cli("self-check")

    report = parse_stdout(result)
    assert result.returncode == 0
    assert report["status"] == "ready"
    assert "python_executable" not in report["result"]
    assert str(ROOT.resolve()) not in result.stdout


def test_plan_then_run_shareable_bundle(tmp_path: Path) -> None:
    recipe_path = prepare_recipe(tmp_path)
    plan_path = tmp_path / "plan.json"

    planned = run_cli(
        "plan",
        str(recipe_path),
        "--output",
        str(plan_path),
    )
    plan_report = parse_stdout(planned)

    assert planned.returncode == 0
    assert plan_report["status"] == "ready"
    assert plan_path.is_file()
    assert not (tmp_path / "bundle").exists()
    plan_text = plan_path.read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) not in plan_text
    assert "SYN-01" not in plan_text

    executed = run_cli(
        "run",
        str(recipe_path),
        "--plan",
        str(plan_path),
    )
    run_report = parse_stdout(executed)

    assert executed.returncode == 0
    assert run_report["status"] == "ready"
    task_dir = tmp_path / "bundle" / "ree-1"
    for suffix in ("svg", "pdf", "tiff", "png", "report.json", "qa.md"):
        assert (task_dir / f"figure-ree-1.{suffix}").is_file()
    assert not (task_dir / "figure-ree-1.source_data.csv").exists()
    report_text = (tmp_path / "bundle" / "run.report.json").read_text(
        encoding="utf-8"
    )
    task_report_text = (
        task_dir / "figure-ree-1.report.json"
    ).read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) not in report_text
    assert "SYN-01" not in report_text
    assert '"data_min"' not in task_report_text
    assert '"data_max"' not in task_report_text


def test_missing_confirmation_returns_exit_two_and_no_figures(
    tmp_path: Path,
) -> None:
    recipe_path = prepare_recipe(tmp_path, confirmed=False)
    plan_path = tmp_path / "plan.json"

    result = run_cli(
        "plan",
        str(recipe_path),
        "--output",
        str(plan_path),
    )
    report = parse_stdout(result)

    assert result.returncode == 2
    assert report["status"] == "needs_confirmation"
    assert plan_path.is_file()
    assert not (tmp_path / "bundle").exists()


def test_blocked_input_still_writes_reviewable_plan(tmp_path: Path) -> None:
    recipe_path = prepare_recipe(tmp_path)
    (tmp_path / "input.csv").unlink()
    plan_path = tmp_path / "plan.json"

    result = create_plan(recipe_path, plan_path)

    assert result["status"] == "blocked"
    assert plan_path.is_file()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["status"] == "blocked"
    assert "filename" not in plan["input"]
    issue = next(item for item in result["issues"] if item["code"] == "E106")
    assert "input.csv" not in issue["message"]
    assert "input.file" in issue["suggested_action"]
    assert str(tmp_path.resolve()) not in plan_path.read_text(encoding="utf-8")


def test_same_recipe_and_input_produce_identical_plan(tmp_path: Path) -> None:
    recipe_path = prepare_recipe(tmp_path)
    first_path = tmp_path / "first-plan.json"
    second_path = tmp_path / "second-plan.json"

    first = create_plan(recipe_path, first_path)
    second = create_plan(recipe_path, second_path)

    assert first["plan_id"] == second["plan_id"]
    assert first_path.read_bytes() == second_path.read_bytes()


def test_stale_input_blocks_run_without_creating_output(
    tmp_path: Path,
) -> None:
    recipe_path = prepare_recipe(tmp_path)
    plan_path = tmp_path / "plan.json"
    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    with (tmp_path / "input.csv").open("a", encoding="utf-8") as handle:
        handle.write("\n")

    result = execute_plan(recipe_path, plan_path)

    assert result["status"] == "blocked"
    assert result["issues"][0]["code"] == "R803"
    assert not (tmp_path / "bundle").exists()


def test_local_reproducible_keeps_sensitive_plotted_source(
    tmp_path: Path,
) -> None:
    recipe_path = prepare_recipe(
        tmp_path,
        report_profile="local-reproducible",
    )
    plan_path = tmp_path / "plan.json"
    assert create_plan(recipe_path, plan_path)["status"] == "ready"

    result = execute_plan(recipe_path, plan_path)

    assert result["status"] == "ready"
    source = (
        tmp_path
        / "bundle"
        / "ree-1"
        / "figure-ree-1.source_data.csv"
    )
    assert source.is_file()
    report_text = (tmp_path / "bundle" / "run.report.json").read_text(
        encoding="utf-8"
    )
    assert "plotted-source-sensitive" in report_text
    assert str(tmp_path.resolve()) not in report_text


def test_spider_recipe_preserves_three_reviewed_oxide_conversions(
    tmp_path: Path,
) -> None:
    recipe_path = prepare_spider_recipe(tmp_path)
    plan_path = tmp_path / "plan.json"

    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    result = execute_plan(recipe_path, plan_path)

    assert result["status"] == "ready"
    task_dir = tmp_path / "bundle" / "spider-main"
    assert (task_dir / "figure-spider.svg").is_file()
    report = json.loads(
        (task_dir / "figure-spider.report.json").read_text(encoding="utf-8")
    )
    assert report["details"]["diagram"] == "spider"
    assert {
        item["element"] for item in report["details"]["oxide_conversions"]
    } == {"K", "P", "Ti"}
    assert all(
        "source_column" not in item
        for item in report["details"]["oxide_conversions"]
    )
    assert (
        report["details"]["reference_assets"][0]["doi"]
        == "10.1144/GSL.SP.1989.042.01.19"
    )
    assert report["details"]["plot_summary"]["inside_legend_strategy"] in {
        "stacked",
        "compact-two-column",
        "compact-wide",
        None,
    }
    report_text = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert '"data_min"' not in report_text
    assert '"data_max"' not in report_text
    assert report["qa"]["svg_text_editable"] is True
    assert not (task_dir / "figure-spider.source_data.csv").exists()


def test_major_example_runs_harker_tas_and_k2o_as_one_transaction(
    tmp_path: Path,
) -> None:
    recipe_path = prepare_major_multitask_recipe(tmp_path)
    plan_path = tmp_path / "plan.json"

    planned = create_plan(recipe_path, plan_path)
    executed = execute_plan(recipe_path, plan_path)

    assert planned["status"] == "ready"
    assert executed["status"] == "review"
    assert executed["task_count"] == 3
    assert (tmp_path / "bundle" / "harker-main" / "figure-harker.pdf").is_file()
    assert (tmp_path / "bundle" / "tas-main" / "figure-tas.pdf").is_file()
    assert (
        tmp_path / "bundle" / "k2o-series-main" / "figure-k2o-sio2.pdf"
    ).is_file()
    run_report = json.loads(
        (tmp_path / "bundle" / "run.report.json").read_text(encoding="utf-8")
    )
    harker_report_text = (
        tmp_path
        / "bundle"
        / "harker-main"
        / "figure-harker.report.json"
    ).read_text(encoding="utf-8")
    assert run_report["qa"]["all_tasks_completed"] is True
    assert run_report["qa"]["task_count"] == 3
    assert run_report["status"] == "review"
    assert '"data_min"' not in harker_report_text
    assert '"data_max"' not in harker_report_text
    assert "48.4986" not in harker_report_text
    assert "74.9823" not in harker_report_text


def test_provisional_tas_commits_outputs_but_returns_review(
    tmp_path: Path,
) -> None:
    recipe_path = prepare_major_multitask_recipe(tmp_path)
    recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    tas_task = recipe["tasks"][1]
    tas_task["parameters"]["composition_basis"] = "as-reported"
    tas_task["confirmations"]["provisional_classification_accepted"] = True
    recipe["tasks"] = [tas_task]
    recipe_path.write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    plan_path = tmp_path / "plan.json"

    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    result = execute_plan(recipe_path, plan_path)

    assert result["status"] == "review"
    assert (tmp_path / "bundle" / "tas-main" / "figure-tas.svg").is_file()
    run_report = json.loads(
        (tmp_path / "bundle" / "run.report.json").read_text(encoding="utf-8")
    )
    assert run_report["status"] == "review"
    assert run_report["review_required"] is True


def test_multitask_failure_preserves_previous_complete_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from geoskills_core import workflow

    recipe_path = prepare_recipe(tmp_path, tasks=2)
    plan_path = tmp_path / "plan.json"
    assert create_plan(recipe_path, plan_path)["status"] == "ready"
    assert execute_plan(recipe_path, plan_path)["status"] == "ready"
    target = tmp_path / "bundle"
    previous_figure = (
        target / "ree-1" / "figure-ree-1.svg"
    ).read_bytes()

    calls = 0
    real_run_task = workflow.run_task

    def fake_run_task(task, prepared, *, output_dir):
        nonlocal calls
        calls += 1
        if calls == 2:
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
        return real_run_task(
            task,
            prepared,
            output_dir=output_dir,
        )

    monkeypatch.setattr(workflow, "run_task", fake_run_task)

    result = execute_plan(recipe_path, plan_path, overwrite=True)

    assert result["status"] == "error"
    assert calls == 2
    assert (
        target / "ree-1" / "figure-ree-1.svg"
    ).read_bytes() == previous_figure
