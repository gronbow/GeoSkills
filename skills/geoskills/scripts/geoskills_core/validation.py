"""Reusable validation issues and explicit geochemical column mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

import pandas as pd

from .analytes import (
    DEFAULT_ANALYTE_REGISTRY,
    AnalyteRegistry,
    normalize_unit,
)


class Severity(str, Enum):
    """Stable issue severities used in JSON reports."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Issue:
    """One machine-readable problem or review notice."""

    code: str
    severity: Severity | str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", Severity(self.severity))
        object.__setattr__(self, "details", dict(self.details))

    @property
    def blocks(self) -> bool:
        return self.severity is Severity.ERROR

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = dict(self.details)
        return result


def issue(
    code: str,
    severity: Severity | str,
    message: str,
    **details: Any,
) -> Issue:
    """Build an issue with the same compact call style as legacy inspectors."""
    return Issue(code, severity, message, details)


def status_from_issues(
    issues: Iterable[Issue],
    *,
    ready: str = "ready",
    blocked: str = "needs_review",
) -> str:
    return blocked if any(item.blocks for item in issues) else ready


@dataclass(frozen=True)
class ColumnMapping:
    """One explicit source-column to canonical-analyte assignment."""

    source_column: str
    canonical_analyte: str
    unit: str
    origin: str = "explicit"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_column", str(self.source_column))
        object.__setattr__(
            self,
            "canonical_analyte",
            str(self.canonical_analyte),
        )
        object.__setattr__(self, "unit", normalize_unit(self.unit))
        object.__setattr__(self, "origin", str(self.origin))

    def to_dict(self) -> dict[str, str]:
        return {
            "source_column": self.source_column,
            "canonical_analyte": self.canonical_analyte,
            "unit": self.unit,
            "origin": self.origin,
        }


def automatic_column_mappings(
    columns: Iterable[object],
    *,
    registry: AnalyteRegistry = DEFAULT_ANALYTE_REGISTRY,
) -> list[ColumnMapping]:
    """Map only exact registered headers; unknown columns remain untouched."""
    mappings: list[ColumnMapping] = []
    for column in columns:
        matched = registry.match(column)
        if matched is None:
            continue
        mappings.append(
            ColumnMapping(
                source_column=str(column),
                canonical_analyte=matched.canonical,
                unit=matched.explicit_unit,
                origin="header",
            )
        )
    return mappings


def validate_column_mappings(
    mappings: Iterable[ColumnMapping],
    *,
    available_columns: Iterable[object] | None = None,
    registry: AnalyteRegistry = DEFAULT_ANALYTE_REGISTRY,
) -> list[Issue]:
    """Reject ambiguous, duplicated, missing, or unitless mappings."""
    items = list(mappings)
    issues: list[Issue] = []
    available = (
        None
        if available_columns is None
        else {str(column) for column in available_columns}
    )

    source_counts: dict[str, int] = {}
    analyte_counts: dict[str, int] = {}
    for mapping in items:
        source_counts[mapping.source_column] = (
            source_counts.get(mapping.source_column, 0) + 1
        )
        analyte_counts[mapping.canonical_analyte] = (
            analyte_counts.get(mapping.canonical_analyte, 0) + 1
        )

    for source, count in source_counts.items():
        if count > 1:
            issues.append(
                issue(
                    "E221",
                    Severity.ERROR,
                    "One source column cannot be assigned more than once.",
                    source_column=source,
                    assignment_count=count,
                )
            )
    for analyte, count in analyte_counts.items():
        if count > 1:
            issues.append(
                issue(
                    "E222",
                    Severity.ERROR,
                    "Multiple source columns map to the same analyte.",
                    canonical_analyte=analyte,
                    source_columns=[
                        item.source_column
                        for item in items
                        if item.canonical_analyte == analyte
                    ],
                )
            )

    for mapping in items:
        if available is not None and mapping.source_column not in available:
            issues.append(
                issue(
                    "E220",
                    Severity.ERROR,
                    "Mapped source column is not present in the table.",
                    source_column=mapping.source_column,
                )
            )
        definition = registry.get(mapping.canonical_analyte)
        if definition is None:
            issues.append(
                issue(
                    "E223",
                    Severity.ERROR,
                    "Canonical analyte is not registered.",
                    source_column=mapping.source_column,
                    canonical_analyte=mapping.canonical_analyte,
                )
            )
            continue
        normalized_unit = normalize_unit(mapping.unit)
        if normalized_unit == "unknown":
            issues.append(
                issue(
                    "E224",
                    Severity.ERROR,
                    "The analyte unit must be stated explicitly.",
                    source_column=mapping.source_column,
                    canonical_analyte=mapping.canonical_analyte,
                    required_unit=definition.required_unit,
                )
            )
        elif normalized_unit != definition.required_unit:
            issues.append(
                issue(
                    "E225",
                    Severity.ERROR,
                    "The stated unit does not match the analyte data contract.",
                    source_column=mapping.source_column,
                    canonical_analyte=mapping.canonical_analyte,
                    stated_unit=normalized_unit,
                    required_unit=definition.required_unit,
                )
            )
    return issues


def inspect_column_mappings(
    columns: Iterable[object],
    *,
    mappings: Iterable[ColumnMapping] | None = None,
    registry: AnalyteRegistry = DEFAULT_ANALYTE_REGISTRY,
) -> tuple[list[ColumnMapping], list[Issue]]:
    """Create/validate mappings for a future guided column-mapping screen."""
    column_list = list(columns)
    selected = (
        automatic_column_mappings(column_list, registry=registry)
        if mappings is None
        else list(mappings)
    )
    return selected, validate_column_mappings(
        selected,
        available_columns=column_list,
        registry=registry,
    )


def validate_table_structure(frame: pd.DataFrame) -> list[Issue]:
    """Check only table-level properties shared by all diagram families."""
    issues: list[Issue] = []
    if frame.empty:
        issues.append(
            issue("E201", Severity.ERROR, "The input table contains no data rows.")
        )
    column_names = [str(column) for column in frame.columns]
    duplicates = sorted(
        {
            name
            for name in column_names
            if column_names.count(name) > 1
        }
    )
    if duplicates:
        issues.append(
            issue(
                "E202",
                Severity.ERROR,
                "Duplicate table headers must be resolved before mapping.",
                columns=duplicates,
            )
        )
    return issues


def problem_examples(
    frame: pd.DataFrame,
    mask: pd.Series,
    column: object,
    sample_column: object | None,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return short examples without exposing the source file path."""
    examples: list[dict[str, Any]] = []
    for index in frame.index[mask][:limit]:
        sample_value = (
            frame.at[index, sample_column]
            if sample_column is not None
            else None
        )
        value = frame.at[index, column]
        examples.append(
            {
                "spreadsheet_row": (
                    int(index) + 2 if isinstance(index, int) else str(index)
                ),
                "sample": (
                    None if pd.isna(sample_value) else str(sample_value)
                ),
                "value": None if pd.isna(value) else str(value),
            }
        )
    return examples
