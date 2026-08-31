import json
import os
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.export import (  # noqa: E402
    AtomicBundle,
    AtomicDirectory,
    BundleExportError,
    shareable_file_record,
    stage_figure_outputs,
)
from geoskills_core.plotting import (  # noqa: E402
    GROUP_COLORS,
    MARKERS,
    PUBLICATION_DOUBLE_COLUMN,
    PUBLICATION_SINGLE_COLUMN,
    REVIEW_PREVIEW,
    STYLE_PRESETS,
    group_style_map,
    publication_style,
    publication_styled,
)
from geoskills_core.reports import (  # noqa: E402
    REPORT_SCHEMA_VERSION,
    ReportError,
    build_report,
    render_qa_markdown,
    write_report_files,
)


def test_style_presets_are_local_and_deterministic() -> None:
    original_font_size = mpl.rcParams["font.size"]
    original_right_spine = mpl.rcParams["axes.spines.right"]

    with publication_style(PUBLICATION_DOUBLE_COLUMN):
        assert mpl.rcParams["font.size"] == 7.0
        assert mpl.rcParams["axes.spines.right"] is False
        with publication_style(REVIEW_PREVIEW, {"font.size": 10.0}):
            assert mpl.rcParams["font.size"] == 10.0
            assert mpl.rcParams["axes.spines.right"] is True
        assert mpl.rcParams["font.size"] == 7.0

    assert mpl.rcParams["font.size"] == original_font_size
    assert mpl.rcParams["axes.spines.right"] == original_right_spine
    assert set(STYLE_PRESETS) == {
        "publication-double-column",
        "publication-single-column",
        "review-preview",
    }
    styles = group_style_map(["Granite", "Basalt"])
    assert styles["Granite"]["color"] == GROUP_COLORS[0]
    assert styles["Basalt"]["marker"] == MARKERS[1]


def test_decorated_plotter_can_select_a_registered_preset() -> None:
    original_font_size = mpl.rcParams["font.size"]

    @publication_styled(preset_parameter="style_preset")
    def current_font_size(
        style_preset: str = PUBLICATION_DOUBLE_COLUMN,
    ) -> float:
        return float(mpl.rcParams["font.size"])

    assert current_font_size() == 7.0
    assert current_font_size(style_preset=PUBLICATION_SINGLE_COLUMN) == 7.0
    assert current_font_size(style_preset=REVIEW_PREVIEW) == 9.0
    assert mpl.rcParams["font.size"] == original_font_size


def test_shareable_file_record_never_exposes_absolute_path(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "bundle"
    output_dir.mkdir()
    output = output_dir / "figure.svg"
    output.write_text("<svg />", encoding="utf-8")

    record = shareable_file_record(
        output, bundle_root=output_dir, role="figure"
    )

    assert record["filename"] == "figure.svg"
    assert record["format"] == "svg"
    assert record["role"] == "figure"
    assert record["bytes"] == len(b"<svg />")
    assert len(record["sha256"]) == 64
    assert "path" not in record
    assert str(tmp_path) not in json.dumps(record)

    outside = tmp_path / "outside.svg"
    outside.write_text("<svg />", encoding="utf-8")
    with pytest.raises(BundleExportError, match="bundle_root"):
        shareable_file_record(outside, bundle_root=output_dir)


def test_atomic_bundle_commits_all_files_and_cleans_staging(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "outputs"
    with AtomicBundle(output_dir) as bundle:
        first = bundle.stage_path("figure.svg")
        second = bundle.stage_path("figure.report.json")
        staging_dir = bundle.staging_dir
        first.write_text("<svg />", encoding="utf-8")
        second.write_text("{}\n", encoding="utf-8")
        installed = bundle.commit()

    assert {path.name for path in installed} == {
        "figure.svg",
        "figure.report.json",
    }
    assert (output_dir / "figure.svg").read_text(encoding="utf-8") == "<svg />"
    assert not staging_dir.exists()
    assert not list(tmp_path.glob(".geoskills-*"))


def test_atomic_bundle_aborts_cleanly_after_writer_failure(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "outputs"
    staging_dir: Path | None = None

    with pytest.raises(RuntimeError, match="simulated"):
        with AtomicBundle(output_dir) as bundle:
            staged = bundle.stage_path("figure.svg")
            staging_dir = bundle.staging_dir
            staged.write_text("partial", encoding="utf-8")
            raise RuntimeError("simulated writer failure")

    assert not (output_dir / "figure.svg").exists()
    assert staging_dir is not None and not staging_dir.exists()
    assert not list(tmp_path.glob(".geoskills-*"))


def test_atomic_directory_commits_nested_outputs(tmp_path: Path) -> None:
    target = tmp_path / "complete_run"
    with AtomicDirectory(target) as transaction:
        task = transaction.staging_dir / "ree_main"
        task.mkdir()
        (task / "figure.svg").write_text("<svg/>", encoding="utf-8")
        committed = transaction.commit()

    assert committed == target.resolve()
    assert (target / "ree_main" / "figure.svg").read_text(encoding="utf-8") == (
        "<svg/>"
    )


def test_atomic_directory_keeps_old_bundle_after_writer_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "complete_run"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(RuntimeError, match="simulated"):
        with AtomicDirectory(target, overwrite=True) as transaction:
            (transaction.staging_dir / "new.txt").write_text(
                "new", encoding="utf-8"
            )
            raise RuntimeError("simulated task failure")

    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (target / "new.txt").exists()


def test_atomic_bundle_rolls_back_overwrite_after_partial_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from geoskills_core import export

    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    first_target = output_dir / "a.txt"
    second_target = output_dir / "b.txt"
    first_target.write_text("old-a", encoding="utf-8")
    second_target.write_text("old-b", encoding="utf-8")
    real_replace = os.replace

    with AtomicBundle(output_dir, overwrite=True) as bundle:
        bundle.stage_path("a.txt").write_text("new-a", encoding="utf-8")
        bundle.stage_path("b.txt").write_text("new-b", encoding="utf-8")

        def fail_on_second_install(source: object, target: object) -> None:
            source_path = Path(source)
            target_path = Path(target)
            if (
                source_path.parent == bundle.staging_dir
                and target_path.name == "b.txt"
            ):
                raise OSError("simulated commit failure")
            real_replace(source, target)

        monkeypatch.setattr(export.os, "replace", fail_on_second_install)
        with pytest.raises(BundleExportError, match="已尝试恢复"):
            bundle.commit()

    assert first_target.read_text(encoding="utf-8") == "old-a"
    assert second_target.read_text(encoding="utf-8") == "old-b"
    assert not list(tmp_path.glob(".geoskills-*"))


def test_atomic_bundle_preserves_backup_when_restore_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from geoskills_core import export

    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    target = output_dir / "a.txt"
    target.write_text("old-a", encoding="utf-8")
    real_replace = os.replace

    with pytest.raises(BundleExportError, match="恢复目录"):
        with AtomicBundle(output_dir, overwrite=True) as bundle:
            bundle.stage_path("a.txt").write_text(
                "new-a", encoding="utf-8"
            )

            def fail_install_and_restore(
                source: object,
                destination: object,
            ) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    source_path.parent == bundle.staging_dir
                    and destination_path == target
                ):
                    raise OSError("synthetic install failure")
                if (
                    source_path.parent.name.startswith(
                        ".geoskills-backup-"
                    )
                    and destination_path == target
                ):
                    raise OSError("synthetic restore failure")
                real_replace(source, destination)

            monkeypatch.setattr(
                export.os, "replace", fail_install_and_restore
            )
            bundle.commit()

    backups = list(tmp_path.glob(".geoskills-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "a.txt").read_text(encoding="utf-8") == "old-a"
    assert not target.exists()


def test_figure_and_reports_commit_as_one_shareable_bundle(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "outputs"
    figure, axis = plt.subplots(figsize=(2, 1.5))
    axis.plot([1, 2], [3, 4])

    try:
        with AtomicBundle(output_dir) as bundle:
            stage_figure_outputs(
                bundle,
                figure,
                "test_plot",
                formats=("svg", "png"),
                dpi=100,
            )
            report = build_report(
                operation="harker_plot",
                status="review",
                source={
                    "filename": "published_example.csv",
                    "format": "csv",
                    "row_count": 2,
                    "column_count": 2,
                },
                outputs=(),
                issues=[
                    {
                        "code": "R001",
                        "severity": "review",
                        "message": "请复核图例位置。",
                    }
                ],
                next_actions=["确认图例未遮挡数据。"],
                review_required=True,
            )
            write_report_files(bundle, "test_plot", report)
            bundle.commit()
    finally:
        plt.close(figure)

    assert (output_dir / "test_plot.svg").is_file()
    assert (output_dir / "test_plot.png").is_file()
    stored_report = json.loads(
        (output_dir / "test_plot.report.json").read_text(encoding="utf-8")
    )
    summary = (output_dir / "test_plot.qa.md").read_text(encoding="utf-8")
    assert stored_report["schema"]["version"] == REPORT_SCHEMA_VERSION
    assert stored_report["review_required"] is True
    assert stored_report["next_actions"] == ["确认图例未遮挡数据。"]
    assert "# GeoSkills 图件质量检查摘要" in summary
    assert "请复核图例位置" in summary
    assert "不包含本地绝对路径或源数据值" in summary
    assert str(tmp_path) not in summary


def test_tiff_export_is_rgb_lzw_and_preserves_requested_dpi(
    tmp_path: Path,
) -> None:
    from PIL import Image

    output_dir = tmp_path / "tiff-output"
    figure, axis = plt.subplots(figsize=(2, 1.5))
    axis.plot([1, 2], [3, 4])
    try:
        with AtomicBundle(output_dir) as bundle:
            stage_figure_outputs(
                bundle,
                figure,
                "test_plot",
                formats=("tiff",),
                dpi=180,
            )
            bundle.commit()
    finally:
        plt.close(figure)

    with Image.open(output_dir / "test_plot.tiff") as image:
        assert image.mode == "RGB"
        assert image.tag_v2.get(259) == 5
        assert image.info["dpi"] == (180.0, 180.0)


def test_ready_qa_wording_requires_final_visual_and_scientific_review() -> None:
    report = build_report(
        operation="ree_plot",
        status="ready",
        review_required=False,
    )

    summary = render_qa_markdown(report)

    assert "技术生成完成" in summary
    assert "最终尺寸" in summary
    assert "视觉与科学审核" in summary


def test_shareable_report_rejects_paths_and_source_values(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReportError, match="未经允许"):
        build_report(
            operation="tas_plot",
            status="ready",
            source={"path": str(tmp_path / "private.csv")},
        )

    with pytest.raises(ReportError, match="不能包含字段"):
        build_report(
            operation="tas_plot",
            status="ready",
            details={"values": [50.1, 3.2]},
        )


@pytest.mark.parametrize(
    "key",
    [
        "data_min",
        "data_max",
        "raw_min",
        "raw_max",
        "observed_min",
        "observed_max",
        "source_min",
        "source_max",
    ],
)
def test_shareable_report_rejects_exact_extrema_fields(key: str) -> None:
    with pytest.raises(ReportError):
        build_report(
            operation="harker_plot",
            status="ready",
            details={"plot_summary": {"x_limits": {key: 48.4986}}},
        )


def test_shareable_report_accepts_input_hash_and_size() -> None:
    report = build_report(
        operation="workflow_plan",
        status="ready",
        source={
            "filename": "published.csv",
            "file_sha256": "a" * 64,
            "size_bytes": 123,
            "format": ".csv",
        },
    )

    assert report["source"]["file_sha256"] == "a" * 64
    assert report["source"]["size_bytes"] == 123
    assert "filename" not in report["source"]


def test_shareable_report_omits_private_filename_and_sheet() -> None:
    report = build_report(
        operation="workflow_plan",
        status="ready",
        source={
            "filename": "PROJECT-ALPHA-sample-001.xlsx",
            "sheet": "PRIVATE-LOCALITY-X",
            "file_sha256": "b" * 64,
            "format": ".xlsx",
        },
    )

    encoded = json.dumps(report, ensure_ascii=False)
    assert "PROJECT-ALPHA" not in encoded
    assert "PRIVATE-LOCALITY-X" not in encoded


def test_markdown_escapes_table_control_characters() -> None:
    report = build_report(
        operation="test",
        status="ready",
        outputs=[
            {
                "filename": "a|b.svg",
                "format": "svg",
                "bytes": 10,
                "sha256": "a" * 64,
            }
        ],
    )

    markdown = render_qa_markdown(report)
    assert "a\\|b.svg" in markdown
