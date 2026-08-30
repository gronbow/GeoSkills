#!/usr/bin/env python3
"""Shared deterministic helpers for publication geochemical scatter figures."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from geoskills_core.errors import PlottingError
from geoskills_core.export import save_figure_files
from geoskills_core.plotting import (
    FORMATS,
    GROUP_COLORS,
    MARKERS,
)
from geoskills_core.style_contract import validate_style_contract


def chemical_formula_label(analyte: str) -> str:
    """Return editable MathText chemistry without fragile Unicode glyphs."""

    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z]+|\d+|[+-]|.", str(analyte)):
        if token.isdigit():
            tokens.append(f"_{{{token}}}")
        elif token in {"+", "-"}:
            tokens.append(f"^{{{token}}}")
        elif token == "*":
            tokens.append(r"\ast")
        else:
            tokens.append(token)
    return r"$\mathrm{" + "".join(tokens) + "}$"


def analyte_label(analyte: str, unit: str) -> str:
    """Return a compact final-size axis label with editable subscripts."""

    return f"{chemical_formula_label(analyte)} ({unit})"


def clean_linear_limits(
    values: np.ndarray | pd.Series,
    margin_fraction: float = 0.06,
    nonnegative: bool = True,
) -> dict[str, float | str]:
    """Return clean outward-rounded linear limits without clipping data."""
    if not 0.0 <= margin_fraction <= 0.25:
        raise PlottingError("线性坐标边距必须在 0–0.25 之间。")
    numeric = np.asarray(values, dtype=float).ravel()
    valid = numeric[np.isfinite(numeric)]
    if valid.size == 0:
        raise PlottingError("没有可用于坐标范围计算的有限数值。")
    data_min = float(valid.min())
    data_max = float(valid.max())
    if nonnegative and data_min < 0:
        raise PlottingError("检测到负浓度，不能安全生成地球化学散点图。")

    raw_span = data_max - data_min
    reference = max(abs(data_min), abs(data_max), 1.0)
    span = raw_span if raw_span > 0 else reference * 0.1
    padded_min = data_min - span * margin_fraction
    padded_max = data_max + span * margin_fraction
    target_step = max((padded_max - padded_min) / 5.0, np.finfo(float).eps)
    exponent = float(np.floor(np.log10(target_step)))
    fraction = target_step / (10.0**exponent)
    if fraction <= 1.0:
        nice_fraction = 1.0
    elif fraction <= 2.0:
        nice_fraction = 2.0
    elif fraction <= 2.5:
        nice_fraction = 2.5
    elif fraction <= 5.0:
        nice_fraction = 5.0
    else:
        nice_fraction = 10.0
    step = float(nice_fraction * (10.0**exponent))

    lower = float(np.floor(padded_min / step) * step)
    upper = float(np.ceil(padded_max / step) * step)
    if nonnegative and lower < 0:
        lower = 0.0
    if np.isclose(lower, upper):
        upper = lower + step
    if lower > data_min or upper < data_max:
        raise PlottingError("整洁坐标范围会裁切数据，已停止绘图。")
    if np.isclose(lower, 0.0):
        lower = 0.0
    if np.isclose(upper, 0.0):
        upper = 0.0
    return {
        "lower": lower,
        "upper": upper,
        "step": step,
        "data_min": data_min,
        "data_max": data_max,
        "margin_fraction": margin_fraction,
        "policy": "adaptive_linear_clean_outward_bounds",
    }


def resolve_analyte_selection(
    value: str,
    available: list[str],
    option_name: str,
) -> str:
    """Resolve one case-insensitive canonical analyte selection."""
    canonical = {item.casefold(): item for item in available}
    selected = canonical.get(value.strip().casefold())
    if selected is None:
        raise PlottingError(
            f"{option_name} 变量未在已验证输入中出现：{value}。"
        )
    return selected


def resolve_analyte_list(
    value: str | None,
    available: list[str],
    option_name: str,
) -> list[str]:
    """Resolve a comma-separated case-insensitive analyte list."""
    if value is None:
        return []
    requested = [item.strip() for item in value.split(",") if item.strip()]
    if not requested:
        raise PlottingError(f"{option_name} 不能为空。")
    canonical = {item.casefold(): item for item in available}
    selected: list[str] = []
    for item in requested:
        resolved = canonical.get(item.casefold())
        if resolved is None:
            raise PlottingError(
                f"{option_name} 变量未在已验证输入中出现：{item}。"
            )
        selected.append(resolved)
    if len(set(selected)) != len(selected):
        raise PlottingError(f"{option_name} 中不能重复同一变量。")
    return selected


def filter_requested_groups(
    frame: pd.DataFrame,
    group_column: str | None,
    selection: str | None,
) -> tuple[pd.DataFrame, list[str]]:
    """Filter explicit groups without silently guessing category names."""
    if group_column is None:
        if selection:
            raise PlottingError("输入没有已验证分组列，不能使用 --groups。")
        return frame.copy(), []
    working = frame.copy()
    group_text = (
        working[group_column]
        .astype("string")
        .str.strip()
        .fillna("Unspecified")
        .replace("", "Unspecified")
    )
    working[group_column] = group_text
    available = [
        str(value)
        for value in group_text.dropna().drop_duplicates().tolist()
        if str(value)
    ]
    if selection is None:
        selected = available
    else:
        requested = [
            item.strip() for item in selection.split(",") if item.strip()
        ]
        missing = [item for item in requested if item not in available]
        if missing:
            raise PlottingError(
                "所选分组未在输入中出现：" + ", ".join(missing) + "。"
            )
        selected = requested
    filtered = working.loc[group_text.isin(selected)].copy()
    if filtered.empty:
        raise PlottingError("分组筛选后没有可绘制样品。")
    return filtered, selected


def group_style_map(groups: list[str]) -> dict[str, dict[str, Any]]:
    """Return deterministic colour-plus-marker styles for groups."""
    return {
        group: {
            "color": GROUP_COLORS[index % len(GROUP_COLORS)],
            "marker": MARKERS[index % len(MARKERS)],
        }
        for index, group in enumerate(groups)
    }


def validate_export_parameters(
    width_mm: float,
    height_mm: float,
    dpi: int,
) -> None:
    """Validate final-size and raster export parameters."""
    try:
        validate_style_contract(width_mm, height_mm, dpi)
    except (TypeError, ValueError) as exc:
        raise PlottingError(
            "图件尺寸、DPI 或栅格像素总量超过 GeoSkills 固定安全预算。"
        ) from exc


def output_targets(
    output_dir: Path,
    stem: str,
) -> tuple[list[Path], Path, Path]:
    """Resolve a complete figure bundle without accepting path-like stems."""
    if not stem or Path(stem).name != stem or Path(stem).suffix:
        raise PlottingError("输出名称必须是不含路径和扩展名的文件名。")
    figures = [
        output_dir / f"{stem}.{extension}" for extension in FORMATS
    ]
    source_data = output_dir / f"{stem}.source_data.csv"
    report = output_dir / f"{stem}.report.json"
    return figures, source_data, report


def ensure_outputs_available(
    targets: list[Path],
    overwrite: bool,
) -> None:
    """Require an explicit overwrite decision for a complete bundle."""
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise PlottingError(
            "输出文件已经存在；如需替换，请显式使用 --overwrite。"
        )


def save_figure_bundle(
    figure: Any,
    paths: list[Path],
    dpi: int,
) -> None:
    """Save vector and raster outputs from the same Matplotlib figure."""
    save_figure_files(figure, paths, dpi=dpi)


def shareable_file_record(path: Path) -> dict[str, Any]:
    """Describe an output without exposing its local directory."""
    return {
        "format": path.suffix.lower().lstrip("."),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
