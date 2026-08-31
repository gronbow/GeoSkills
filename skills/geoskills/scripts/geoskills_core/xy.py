"""Deterministic grouped bivariate plotting from already-resolved series."""

from __future__ import annotations

from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from plot_geochem_common import clean_linear_limits

from .errors import PlottingError
from .plotting import group_style_map, mm_to_inches, publication_style


def build_xy_figure(
    frame: pd.DataFrame,
    *,
    x_values: pd.Series,
    y_values: pd.Series,
    valid_mask: pd.Series,
    x_label: str,
    y_label: str,
    x_scale: str,
    y_scale: str,
    group_column: str | None,
    width_mm: float,
    height_mm: float,
    title: str | None = None,
    style_preset: str = "publication-double-column",
) -> tuple[Any, dict[str, Any]]:
    """Build one coordinate-only scatter without sample text labels."""

    selected = frame.loc[valid_mask].copy()
    selected["__x"] = x_values.loc[valid_mask].astype(float)
    selected["__y"] = y_values.loc[valid_mask].astype(float)
    if selected.empty:
        raise PlottingError("没有同时满足 X/Y 坐标要求的记录。")
    if group_column is None:
        selected["__group"] = "All data"
        plot_group = "__group"
    else:
        selected[group_column] = (
            selected[group_column]
            .astype("string")
            .str.strip()
            .fillna("Unspecified")
            .replace("", "Unspecified")
        )
        plot_group = group_column
    groups = [str(value) for value in selected[plot_group].drop_duplicates()]
    styles = group_style_map(groups)

    with publication_style(style_preset):
        figure, axis = plt.subplots(
            figsize=(mm_to_inches(width_mm), mm_to_inches(height_mm))
        )
        for group in groups:
            subset = selected.loc[selected[plot_group].eq(group)]
            style = styles[group]
            axis.scatter(
                subset["__x"],
                subset["__y"],
                s=23,
                marker=style["marker"],
                facecolor=style["color"],
                edgecolor="white",
                linewidth=0.45,
                alpha=0.9,
                label=group,
                zorder=3,
            )
        axis.set_xscale("log" if x_scale == "log10" else "linear")
        axis.set_yscale("log" if y_scale == "log10" else "linear")
        if x_scale == "linear":
            limits = clean_linear_limits(
                selected["__x"].to_numpy(), nonnegative=False
            )
            axis.set_xlim(float(limits["lower"]), float(limits["upper"]))
        if y_scale == "linear":
            limits = clean_linear_limits(
                selected["__y"].to_numpy(), nonnegative=False
            )
            axis.set_ylim(float(limits["lower"]), float(limits["upper"]))
        axis.set_xlabel(x_label)
        axis.set_ylabel(y_label)
        if title:
            axis.set_title(title)
        for spine in axis.spines.values():
            spine.set_visible(True)
        axis.tick_params(direction="out", top=False, right=False)
        legend = axis.legend(
            loc="best",
            title="Group" if group_column is not None else None,
            frameon=True,
            borderpad=0.45,
            handletextpad=0.4,
        )
        legend.get_frame().set_facecolor("white")
        legend.get_frame().set_alpha(0.92)
        figure.tight_layout(pad=0.8)

    return figure, {
        "joint_valid_count": int(valid_mask.sum()),
        "group_count": len(groups),
        "sample_labels_rendered": False,
        "x_scale": x_scale,
        "y_scale": y_scale,
        "axes_frame": "full",
        "legend_position": "inside-best",
        "palette_repeated": len(groups) > 8,
        "marker_repeated": len(groups) > 12,
    }


__all__ = ["build_xy_figure"]
