"""Privacy-safe and failure-clean output helpers for GeoSkills.

``AtomicBundle`` stages every requested file beside the destination directory.
Each final file is installed with ``os.replace`` (atomic for that file on the
same filesystem).  A multi-file bundle cannot be made one filesystem operation,
so the class also keeps temporary backups and rolls back a partial commit if an
installation fails.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image

from .plotting import publication_style


class BundleExportError(RuntimeError):
    """Raised when a complete output bundle cannot be exported safely."""


DEFAULT_FIGURE_FORMATS = ("svg", "pdf", "tiff", "png")
_SUPPORTED_FIGURE_FORMATS = frozenset(DEFAULT_FIGURE_FORMATS)


def _safe_filename(filename: str) -> str:
    """Validate one flat bundle filename."""

    name = str(filename).strip()
    candidate = Path(name)
    if (
        not name
        or name in {".", ".."}
        or candidate.name != name
        or candidate.is_absolute()
    ):
        raise BundleExportError(
            "输出文件名必须是不含目录、盘符或上级路径的单个文件名。"
        )
    return name


def _safe_stem(stem: str) -> str:
    name = _safe_filename(stem)
    if Path(name).suffix:
        raise BundleExportError("输出名称不能包含扩展名。")
    return name


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a file digest without loading a large raster into memory."""

    if chunk_size <= 0:
        raise BundleExportError("校验分块大小必须大于 0。")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shareable_file_record(
    path: Path,
    *,
    bundle_root: Path | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Describe one output without exposing its absolute local path.

    If ``bundle_root`` is supplied, the file must be inside that directory.  A
    portable POSIX-style relative path is then included for nested bundles.
    """

    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise BundleExportError(f"输出记录对象不是普通文件：{resolved.name}。")

    relative = Path(resolved.name)
    if bundle_root is not None:
        root = Path(bundle_root).resolve(strict=True)
        if not root.is_dir():
            raise BundleExportError("bundle_root 必须是已存在的目录。")
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise BundleExportError("输出文件不在指定的 bundle_root 内。") from exc

    record: dict[str, Any] = {
        "filename": resolved.name,
        "format": resolved.suffix.lower().lstrip("."),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }
    if relative != Path(resolved.name):
        record["relative_path"] = relative.as_posix()
    if role is not None:
        cleaned_role = str(role).strip()
        if not cleaned_role:
            raise BundleExportError("输出文件角色不能为空。")
        record["role"] = cleaned_role
    return record


class AtomicBundle:
    """Stage and transactionally install a flat collection of output files."""

    def __init__(self, output_dir: Path, *, overwrite: bool = False) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.overwrite = bool(overwrite)
        self._staging_dir: Path | None = None
        self._staged: dict[str, Path] = {}
        self._entered = False
        self._committed = False

    @property
    def staging_dir(self) -> Path:
        """Return the active private staging directory."""

        if self._staging_dir is None:
            raise BundleExportError("输出暂存区尚未启动或已经关闭。")
        return self._staging_dir

    def __enter__(self) -> "AtomicBundle":
        if self._entered:
            raise BundleExportError("同一个 AtomicBundle 不能重复进入。")
        parent = self.output_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        self._staging_dir = Path(
            tempfile.mkdtemp(prefix=".geoskills-stage-", dir=parent)
        ).resolve()
        self._entered = True
        return self

    def stage_path(self, filename: str) -> Path:
        """Reserve and return one path inside the private staging directory."""

        self._require_active()
        name = _safe_filename(filename)
        if name not in self._staged:
            self._staged[name] = self.staging_dir / name
        return self._staged[name]

    def commit(self) -> list[Path]:
        """Install every staged file, restoring old files after any failure."""

        self._require_active()
        if not self._staged:
            raise BundleExportError("输出包中没有已登记的文件。")

        missing = [name for name, path in self._staged.items() if not path.is_file()]
        if missing:
            raise BundleExportError(
                "以下暂存文件尚未成功写入：" + ", ".join(sorted(missing)) + "。"
            )

        targets = {
            name: self.output_dir / name for name in sorted(self._staged)
        }
        directory_targets = [
            target.name for target in targets.values() if target.is_dir()
        ]
        if directory_targets:
            raise BundleExportError(
                "目标位置存在同名目录，不能安全覆盖："
                + ", ".join(directory_targets)
                + "。"
            )
        existing = [target for target in targets.values() if target.exists()]
        if existing and not self.overwrite:
            raise BundleExportError(
                "输出文件已经存在；如需替换，请明确启用 overwrite："
                + ", ".join(path.name for path in existing)
                + "。"
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(
            tempfile.mkdtemp(
                prefix=".geoskills-backup-", dir=self.output_dir.parent
            )
        ).resolve()
        backups: list[tuple[Path, Path]] = []
        installed: list[Path] = []
        commit_succeeded = False
        rollback_incomplete = False
        try:
            for name, target in targets.items():
                if target.exists():
                    backup = backup_dir / name
                    os.replace(target, backup)
                    backups.append((backup, target))

            for name, target in targets.items():
                os.replace(self._staged[name], target)
                installed.append(target)
            commit_succeeded = True
        except Exception as exc:
            rollback_errors: list[str] = []
            for target in reversed(installed):
                try:
                    if target.exists():
                        target.unlink()
                except OSError as rollback_exc:
                    rollback_errors.append(f"删除 {target.name} 失败：{rollback_exc}")
            for backup, target in reversed(backups):
                try:
                    if backup.exists():
                        os.replace(backup, target)
                except OSError as rollback_exc:
                    rollback_errors.append(f"恢复 {target.name} 失败：{rollback_exc}")

            message = "输出包提交失败，已尝试恢复提交前状态。"
            if rollback_errors:
                rollback_incomplete = True
                message += " 回滚异常：" + "；".join(rollback_errors)
                message += (
                    f" 未恢复的旧文件保留在恢复目录 {backup_dir.name} 中。"
                )
            raise BundleExportError(message) from exc
        finally:
            if backup_dir.exists() and (
                commit_succeeded or not rollback_incomplete
            ):
                self._remove_private_directory(
                    backup_dir, ".geoskills-backup-"
                )

        self._committed = True
        installed_paths = list(targets.values())
        self._cleanup_staging()
        return installed_paths

    def abort(self) -> None:
        """Discard all temporary files without changing final outputs."""

        self._require_active()
        self._cleanup_staging()

    def _require_active(self) -> None:
        if (
            not self._entered
            or self._committed
            or self._staging_dir is None
        ):
            raise BundleExportError("输出包当前不处于可写状态。")

    def _cleanup_staging(self) -> None:
        if self._staging_dir is not None:
            self._remove_private_directory(
                self._staging_dir, ".geoskills-stage-"
            )
            self._staging_dir = None
        self._staged.clear()

    def _remove_private_directory(self, path: Path, prefix: str) -> None:
        """Remove only a verified temporary directory created beside output."""

        resolved = path.resolve()
        expected_parent = self.output_dir.parent.resolve()
        if (
            resolved.parent != expected_parent
            or not resolved.name.startswith(prefix)
        ):
            raise BundleExportError("拒绝清理未经验证的临时目录。")
        if resolved.exists():
            shutil.rmtree(resolved)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self._staging_dir is not None:
            self._cleanup_staging()
        return False


class AtomicDirectory:
    """Stage a nested run directory and replace the final directory as one unit."""

    def __init__(self, output_dir: Path, *, overwrite: bool = False) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.overwrite = bool(overwrite)
        self._staging_dir: Path | None = None
        self._entered = False
        self._committed = False

    @property
    def staging_dir(self) -> Path:
        if self._staging_dir is None:
            raise BundleExportError("输出目录暂存区尚未启动或已经关闭。")
        return self._staging_dir

    def __enter__(self) -> "AtomicDirectory":
        if self._entered:
            raise BundleExportError("同一个 AtomicDirectory 不能重复进入。")
        parent = self.output_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        self._staging_dir = Path(
            tempfile.mkdtemp(prefix=".geoskills-run-stage-", dir=parent)
        ).resolve()
        self._entered = True
        return self

    def commit(self) -> Path:
        """Promote the staged directory and restore an old bundle after failure."""

        if not self._entered or self._committed or self._staging_dir is None:
            raise BundleExportError("输出目录当前不处于可提交状态。")
        if not any(self._staging_dir.iterdir()):
            raise BundleExportError("输出目录暂存区为空。")
        if self.output_dir.exists() and not self.output_dir.is_dir():
            raise BundleExportError("最终输出位置存在同名文件，不能安全替换。")
        if self.output_dir.exists() and not self.overwrite:
            raise BundleExportError(
                "完整输出目录已经存在；如需替换，请明确启用 overwrite。"
            )

        backup = Path(
            tempfile.mkdtemp(
                prefix=".geoskills-run-backup-",
                dir=self.output_dir.parent,
            )
        ).resolve()
        backup.rmdir()
        moved_old = False
        commit_succeeded = False
        recovery_preserved = False
        try:
            if self.output_dir.exists():
                os.replace(self.output_dir, backup)
                moved_old = True
            os.replace(self._staging_dir, self.output_dir)
            commit_succeeded = True
        except Exception as exc:
            if moved_old and backup.exists() and not self.output_dir.exists():
                try:
                    os.replace(backup, self.output_dir)
                except OSError:
                    recovery_preserved = True
            elif moved_old and backup.exists():
                recovery_preserved = True
            message = "完整输出目录提交失败，已尝试恢复原输出。"
            if recovery_preserved:
                message += (
                    f" 原输出保留在恢复目录 {backup.name} 中，请勿删除。"
                )
            raise BundleExportError(
                message
            ) from exc
        finally:
            if backup.exists() and commit_succeeded:
                self._remove_private_directory(
                    backup, ".geoskills-run-backup-"
                )

        self._staging_dir = None
        self._committed = True
        return self.output_dir

    def abort(self) -> None:
        if not self._entered or self._committed or self._staging_dir is None:
            raise BundleExportError("输出目录当前不处于可清理状态。")
        self._remove_private_directory(
            self._staging_dir, ".geoskills-run-stage-"
        )
        self._staging_dir = None

    def _remove_private_directory(self, path: Path, prefix: str) -> None:
        resolved = path.resolve()
        if (
            resolved.parent != self.output_dir.parent.resolve()
            or not resolved.name.startswith(prefix)
        ):
            raise BundleExportError("拒绝清理未经验证的目录暂存区。")
        if resolved.exists():
            shutil.rmtree(resolved)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self._staging_dir is not None:
            self._remove_private_directory(
                self._staging_dir, ".geoskills-run-stage-"
            )
            self._staging_dir = None
        return False


def stage_figure_outputs(
    bundle: AtomicBundle,
    figure: Any,
    stem: str,
    *,
    formats: Sequence[str] = DEFAULT_FIGURE_FORMATS,
    dpi: int = 600,
) -> list[Path]:
    """Render vector and raster files from the same figure into a bundle."""

    clean_stem = _safe_stem(stem)
    if not 72 <= int(dpi) <= 1200:
        raise BundleExportError("PNG/TIFF 分辨率必须在 72–1200 dpi 之间。")

    normalised_formats = [str(item).lower().lstrip(".") for item in formats]
    if not normalised_formats or len(set(normalised_formats)) != len(
        normalised_formats
    ):
        raise BundleExportError("图件格式不能为空或重复。")
    unsupported = [
        item for item in normalised_formats if item not in _SUPPORTED_FIGURE_FORMATS
    ]
    if unsupported:
        raise BundleExportError(
            "不支持以下图件格式：" + ", ".join(unsupported) + "。"
        )

    paths = [
        bundle.stage_path(f"{clean_stem}.{extension}")
        for extension in normalised_formats
    ]
    save_figure_files(figure, paths, dpi=int(dpi))
    return paths


def _convert_tiff_to_rgb(path: Path, dpi: int) -> None:
    """Rewrite one rendered TIFF as RGB with explicit LZW and DPI metadata."""

    try:
        with Image.open(path) as source:
            rgb = source.convert("RGB")
        rgb.save(
            path,
            format="TIFF",
            compression="tiff_lzw",
            dpi=(float(dpi), float(dpi)),
        )
    except (OSError, ValueError) as exc:
        raise BundleExportError(
            f"无法将 TIFF 输出转换为 RGB/LZW：{path.name}。"
        ) from exc


def save_figure_files(
    figure: Any,
    paths: Sequence[Path],
    dpi: int = 600,
) -> None:
    """Save one Matplotlib figure with the shared font and raster contract.

    SVG and PDF retain editable text. PNG preserves the requested DPI. TIFF is
    explicitly rewritten as RGB with LZW compression because Matplotlib's
    direct TIFF output is commonly RGBA, which some journal portals reject.
    """

    if not 72 <= int(dpi) <= 1200:
        raise BundleExportError("PNG/TIFF 分辨率必须在 72–1200 dpi 之间。")
    output_paths = [Path(path) for path in paths]
    if not output_paths:
        raise BundleExportError("至少需要一个图件输出路径。")
    extensions = [path.suffix.lower().lstrip(".") for path in output_paths]
    unsupported = [
        extension
        for extension in extensions
        if extension not in _SUPPORTED_FIGURE_FORMATS
    ]
    if unsupported:
        raise BundleExportError(
            "不支持以下图件格式：" + ", ".join(sorted(set(unsupported))) + "。"
        )

    with publication_style():
        for path, extension in zip(output_paths, extensions):
            options: dict[str, Any] = {"facecolor": "white"}
            if extension in {"png", "tiff"}:
                options["dpi"] = int(dpi)
            if extension == "tiff":
                options["pil_kwargs"] = {"compression": "tiff_lzw"}
            figure.savefig(path, **options)
            if extension == "tiff":
                _convert_tiff_to_rgb(path, int(dpi))


def shareable_records(
    paths: Iterable[Path],
    *,
    bundle_root: Path | None = None,
    role: str | None = None,
) -> list[dict[str, Any]]:
    """Create privacy-safe records for several committed output files."""

    return [
        shareable_file_record(path, bundle_root=bundle_root, role=role)
        for path in paths
    ]
