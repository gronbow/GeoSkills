"""Versioned, literature-gated foundations for geochemical classification plots."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .quality import coerce_geochemical_numeric


CLASSIFICATION_MODEL_SCHEMA_VERSION = "geoskills.classification-model/v1"
MAX_CLASSIFICATION_MODEL_BYTES = 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ClassificationModelError(ValueError):
    """A classification model is invalid, unreviewed, or changed."""


@dataclass(frozen=True)
class VariableDefinition:
    id: str
    operation: str
    source: str | None
    source_unit: str | None
    numerator: str | None
    denominator: str | None
    numerator_unit: str | None
    denominator_unit: str | None
    scale: float
    output_unit: str
    formula: str


@dataclass(frozen=True)
class AxisDefinition:
    variable: str
    label: str
    scale: str
    limits: tuple[float, float]


@dataclass(frozen=True)
class FieldDefinition:
    id: str
    label: str
    vertices: tuple[tuple[float, float], ...]
    label_position: tuple[float, float] | None


@dataclass(frozen=True)
class BoundaryLineDefinition:
    id: str
    vertices: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class ClassificationModel:
    id: str
    display_name: str
    version: str
    source: Mapping[str, str]
    scientific_review: Mapping[str, str]
    variables: tuple[VariableDefinition, ...]
    x_axis: AxisDefinition
    y_axis: AxisDefinition
    fields: tuple[FieldDefinition, ...]
    display_boundaries: tuple[BoundaryLineDefinition, ...]
    boundary_tolerance: float

    def to_dict(self) -> dict[str, Any]:
        def variable_record(item: VariableDefinition) -> dict[str, Any]:
            result = {
                "id": item.id,
                "operation": item.operation,
                "scale": item.scale,
                "output_unit": item.output_unit,
                "formula": item.formula,
            }
            for name in (
                "source",
                "source_unit",
                "numerator",
                "denominator",
                "numerator_unit",
                "denominator_unit",
            ):
                value = getattr(item, name)
                if value is not None:
                    result[name] = value
            return result

        result = {
            "schema_version": CLASSIFICATION_MODEL_SCHEMA_VERSION,
            "id": self.id,
            "display_name": self.display_name,
            "version": self.version,
            "source": dict(self.source),
            "scientific_review": dict(self.scientific_review),
            "variables": [variable_record(item) for item in self.variables],
            "axes": {
                "x": {
                    "variable": self.x_axis.variable,
                    "label": self.x_axis.label,
                    "scale": self.x_axis.scale,
                    "limits": list(self.x_axis.limits),
                },
                "y": {
                    "variable": self.y_axis.variable,
                    "label": self.y_axis.label,
                    "scale": self.y_axis.scale,
                    "limits": list(self.y_axis.limits),
                },
            },
            "fields": [
                {
                    "id": item.id,
                    "label": item.label,
                    "vertices": [list(point) for point in item.vertices],
                    **(
                        {"label_position": list(item.label_position)}
                        if item.label_position is not None
                        else {}
                    ),
                }
                for item in self.fields
            ],
            "boundary": {
                "tolerance": self.boundary_tolerance,
                "on_boundary": "review",
                "overlap": "review",
                "outside": "outside",
            },
        }
        if self.display_boundaries:
            result["display_boundaries"] = [
                {
                    "id": item.id,
                    "vertices": [list(point) for point in item.vertices],
                }
                for item in self.display_boundaries
            ]
        return result


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ClassificationModelError(f"{field} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _strict(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ClassificationModelError(f"{field} has unsupported fields")


def _text(value: Any, field: str, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClassificationModelError(f"{field} must be non-empty text")
    result = value.strip()
    if any(ord(character) < 32 for character in result):
        raise ClassificationModelError(f"{field} contains control text")
    if identifier and _IDENTIFIER.fullmatch(result) is None:
        raise ClassificationModelError(f"{field} is not a safe identifier")
    return result


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ClassificationModelError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ClassificationModelError(f"{field} must be finite")
    return result


def _variable(value: Any, index: int) -> VariableDefinition:
    field = f"variables[{index}]"
    raw = _mapping(value, field)
    common = {"id", "operation", "scale", "output_unit", "formula"}
    operation = _text(raw.get("operation"), f"{field}.operation")
    if operation == "direct":
        _strict(raw, common | {"source", "source_unit"}, field)
        source = _text(raw.get("source"), f"{field}.source", identifier=True)
        source_unit = _text(raw.get("source_unit"), f"{field}.source_unit")
        numerator = denominator = numerator_unit = denominator_unit = None
    elif operation == "ratio":
        _strict(
            raw,
            common
            | {
                "numerator",
                "denominator",
                "numerator_unit",
                "denominator_unit",
            },
            field,
        )
        numerator = _text(
            raw.get("numerator"), f"{field}.numerator", identifier=True
        )
        denominator = _text(
            raw.get("denominator"), f"{field}.denominator", identifier=True
        )
        if numerator == denominator:
            raise ClassificationModelError("ratio operands must differ")
        numerator_unit = _text(
            raw.get("numerator_unit"), f"{field}.numerator_unit"
        )
        denominator_unit = _text(
            raw.get("denominator_unit"), f"{field}.denominator_unit"
        )
        source = source_unit = None
    else:
        raise ClassificationModelError("unsupported variable operation")
    scale = _number(raw.get("scale"), f"{field}.scale", positive=True)
    expected_formula = (
        source
        if operation == "direct" and scale == 1.0
        else f"{source} * {scale:g}"
        if operation == "direct"
        else f"{numerator}/{denominator}"
        if scale == 1.0
        else f"({numerator}/{denominator}) * {scale:g}"
    )
    formula = _text(raw.get("formula"), f"{field}.formula")
    if formula != expected_formula:
        raise ClassificationModelError(
            f"{field}.formula does not match structured operations"
        )
    return VariableDefinition(
        id=_text(raw.get("id"), f"{field}.id", identifier=True),
        operation=operation,
        source=source,
        source_unit=source_unit,
        numerator=numerator,
        denominator=denominator,
        numerator_unit=numerator_unit,
        denominator_unit=denominator_unit,
        scale=scale,
        output_unit=_text(raw.get("output_unit"), f"{field}.output_unit"),
        formula=formula,
    )


def _axis(value: Any, name: str, variable_ids: set[str]) -> AxisDefinition:
    field = f"axes.{name}"
    raw = _mapping(value, field)
    _strict(raw, {"variable", "label", "scale", "limits"}, field)
    variable = _text(raw.get("variable"), f"{field}.variable", identifier=True)
    if variable not in variable_ids:
        raise ClassificationModelError("axis references unknown variable")
    scale = _text(raw.get("scale"), f"{field}.scale")
    if scale not in {"linear", "log10"}:
        raise ClassificationModelError("axis scale must be linear or log10")
    limits = raw.get("limits")
    if not isinstance(limits, list) or len(limits) != 2:
        raise ClassificationModelError("axis limits must contain two numbers")
    lower = _number(limits[0], f"{field}.limits[0]")
    upper = _number(limits[1], f"{field}.limits[1]")
    if lower >= upper or (scale == "log10" and lower <= 0):
        raise ClassificationModelError("axis limits are invalid")
    return AxisDefinition(
        variable=variable,
        label=_text(raw.get("label"), f"{field}.label"),
        scale=scale,
        limits=(lower, upper),
    )


def _coordinate(value: Any, field: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ClassificationModelError(f"{field} must be an x-y pair")
    return (_number(value[0], f"{field}[0]"), _number(value[1], f"{field}[1]"))


def validate_classification_model(
    document: Any,
    *,
    require_approved: bool = True,
) -> ClassificationModel:
    """Validate one strict model; approved review is required by default."""

    root = _mapping(document, "model")
    _strict(
        root,
        {
            "schema_version",
            "id",
            "display_name",
            "version",
            "source",
            "scientific_review",
            "variables",
            "axes",
            "fields",
            "display_boundaries",
            "boundary",
        },
        "model",
    )
    if root.get("schema_version") != CLASSIFICATION_MODEL_SCHEMA_VERSION:
        raise ClassificationModelError("unsupported model schema version")

    source = _mapping(root.get("source"), "source")
    _strict(
        source,
        {"citation", "doi", "geometry_doi", "geometry_reference"},
        "source",
    )
    source_record = {
        "citation": _text(source.get("citation"), "source.citation"),
        "geometry_reference": _text(
            source.get("geometry_reference"), "source.geometry_reference"
        ),
    }
    if source.get("doi") is not None:
        source_record["doi"] = _text(source["doi"], "source.doi")
    if source.get("geometry_doi") is not None:
        source_record["geometry_doi"] = _text(
            source["geometry_doi"], "source.geometry_doi"
        )

    review = _mapping(root.get("scientific_review"), "scientific_review")
    _strict(review, {"status", "reviewed_on", "notes"}, "scientific_review")
    review_status = _text(review.get("status"), "scientific_review.status")
    if review_status not in {"pending", "approved"}:
        raise ClassificationModelError("invalid scientific review status")
    if require_approved and review_status != "approved":
        raise ClassificationModelError("classification model is not approved")
    reviewed_on = _text(review.get("reviewed_on"), "scientific_review.reviewed_on")
    try:
        parsed_review_date = date.fromisoformat(reviewed_on)
    except ValueError as exc:
        raise ClassificationModelError("reviewed_on must use YYYY-MM-DD") from exc
    if _DATE.fullmatch(reviewed_on) is None or parsed_review_date.isoformat() != reviewed_on:
        raise ClassificationModelError("reviewed_on must use YYYY-MM-DD")
    review_record = {"status": review_status, "reviewed_on": reviewed_on}
    if review.get("notes") is not None:
        review_record["notes"] = _text(review["notes"], "scientific_review.notes")

    raw_variables = root.get("variables")
    if not isinstance(raw_variables, list) or len(raw_variables) < 2:
        raise ClassificationModelError("model needs at least two variables")
    variables = tuple(_variable(value, index) for index, value in enumerate(raw_variables))
    variable_ids = [item.id for item in variables]
    if len(variable_ids) != len({item.casefold() for item in variable_ids}):
        raise ClassificationModelError("variable IDs must be unique")

    axes = _mapping(root.get("axes"), "axes")
    _strict(axes, {"x", "y"}, "axes")
    x_axis = _axis(axes.get("x"), "x", set(variable_ids))
    y_axis = _axis(axes.get("y"), "y", set(variable_ids))
    if x_axis.variable == y_axis.variable:
        raise ClassificationModelError("axes must use different variables")

    raw_fields = root.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ClassificationModelError("model needs at least one field")
    fields: list[FieldDefinition] = []
    for index, value in enumerate(raw_fields):
        field_name = f"fields[{index}]"
        raw = _mapping(value, field_name)
        _strict(raw, {"id", "label", "vertices", "label_position"}, field_name)
        raw_vertices = raw.get("vertices")
        if not isinstance(raw_vertices, list) or len(raw_vertices) < 3:
            raise ClassificationModelError("field needs at least three vertices")
        vertices = tuple(
            _coordinate(point, f"{field_name}.vertices[{point_index}]")
            for point_index, point in enumerate(raw_vertices)
        )
        label_position = (
            None
            if raw.get("label_position") is None
            else _coordinate(raw["label_position"], f"{field_name}.label_position")
        )
        fields.append(
            FieldDefinition(
                id=_text(raw.get("id"), f"{field_name}.id", identifier=True),
                label=_text(raw.get("label"), f"{field_name}.label"),
                vertices=vertices,
                label_position=label_position,
            )
        )
    if len(fields) != len({item.id.casefold() for item in fields}):
        raise ClassificationModelError("field IDs must be unique")

    raw_display_boundaries = root.get("display_boundaries", [])
    if not isinstance(raw_display_boundaries, list):
        raise ClassificationModelError("display boundaries must be a list")
    display_boundaries: list[BoundaryLineDefinition] = []
    for index, value in enumerate(raw_display_boundaries):
        field_name = f"display_boundaries[{index}]"
        raw = _mapping(value, field_name)
        _strict(raw, {"id", "vertices"}, field_name)
        raw_vertices = raw.get("vertices")
        if not isinstance(raw_vertices, list) or len(raw_vertices) < 2:
            raise ClassificationModelError(
                "display boundary needs at least two vertices"
            )
        vertices = tuple(
            _coordinate(point, f"{field_name}.vertices[{point_index}]")
            for point_index, point in enumerate(raw_vertices)
        )
        if any(
            vertices[position] == vertices[position - 1]
            for position in range(1, len(vertices))
        ):
            raise ClassificationModelError(
                "display boundary has repeated adjacent vertices"
            )
        display_boundaries.append(
            BoundaryLineDefinition(
                id=_text(raw.get("id"), f"{field_name}.id", identifier=True),
                vertices=vertices,
            )
        )
    if len(display_boundaries) != len(
        {item.id.casefold() for item in display_boundaries}
    ):
        raise ClassificationModelError("display boundary IDs must be unique")

    boundary = _mapping(root.get("boundary"), "boundary")
    _strict(boundary, {"tolerance", "on_boundary", "overlap", "outside"}, "boundary")
    if (
        boundary.get("on_boundary") != "review"
        or boundary.get("overlap") != "review"
        or boundary.get("outside") != "outside"
    ):
        raise ClassificationModelError("boundary policies are fixed")
    tolerance = _number(boundary.get("tolerance"), "boundary.tolerance", positive=True)

    model = ClassificationModel(
        id=_text(root.get("id"), "id", identifier=True),
        display_name=_text(root.get("display_name"), "display_name"),
        version=_text(root.get("version"), "version"),
        source=source_record,
        scientific_review=review_record,
        variables=variables,
        x_axis=x_axis,
        y_axis=y_axis,
        fields=tuple(fields),
        display_boundaries=tuple(display_boundaries),
        boundary_tolerance=tolerance,
    )
    for field in model.fields:
        for x_value, y_value in (
            *field.vertices,
            *((field.label_position,) if field.label_position is not None else ()),
        ):
            if (model.x_axis.scale == "log10" and x_value <= 0) or (
                model.y_axis.scale == "log10" and y_value <= 0
            ):
                raise ClassificationModelError("log-axis geometry must be positive")
        transformed = tuple(_normalise_point(point, model) for point in field.vertices)
        if len(set(transformed)) != len(transformed):
            raise ClassificationModelError("field vertices must be unique")
        for first in range(len(transformed)):
            first_next = (first + 1) % len(transformed)
            for second in range(first + 1, len(transformed)):
                second_next = (second + 1) % len(transformed)
                if first in {second, second_next} or first_next in {second, second_next}:
                    continue
                if _segments_intersect(
                    transformed[first],
                    transformed[first_next],
                    transformed[second],
                    transformed[second_next],
                ):
                    raise ClassificationModelError("field polygon self-intersects")
        twice_area = sum(
            transformed[index][0] * transformed[(index + 1) % len(transformed)][1]
            - transformed[(index + 1) % len(transformed)][0] * transformed[index][1]
            for index in range(len(transformed))
        )
        if abs(twice_area) <= 1e-12:
            raise ClassificationModelError("field polygon has zero area")
    for boundary_line in model.display_boundaries:
        for x_value, y_value in boundary_line.vertices:
            if (model.x_axis.scale == "log10" and x_value <= 0) or (
                model.y_axis.scale == "log10" and y_value <= 0
            ):
                raise ClassificationModelError(
                    "log-axis display boundary must be positive"
                )
            if not (
                model.x_axis.limits[0] <= x_value <= model.x_axis.limits[1]
                and model.y_axis.limits[0] <= y_value <= model.y_axis.limits[1]
            ):
                raise ClassificationModelError(
                    "display boundary must lie within fixed axis limits"
                )
    json.dumps(model.to_dict(), ensure_ascii=False, allow_nan=False)
    return model


def load_classification_model(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    require_approved: bool = True,
) -> ClassificationModel:
    model_path = Path(path)
    if not model_path.is_file():
        raise ClassificationModelError("classification model file is unavailable or too large")
    try:
        with model_path.open("rb") as handle:
            payload = handle.read(MAX_CLASSIFICATION_MODEL_BYTES + 1)
    except OSError as exc:
        raise ClassificationModelError(
            "classification model file is unavailable or too large"
        ) from exc
    if len(payload) > MAX_CLASSIFICATION_MODEL_BYTES:
        raise ClassificationModelError("classification model file is unavailable or too large")
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ClassificationModelError("classification model hash changed")
    try:
        document = json.loads(
            payload.decode("utf-8-sig"), object_pairs_hook=_unique_json_object
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClassificationModelError("classification model must be UTF-8 JSON") from exc
    return validate_classification_model(document, require_approved=require_approved)


def evaluate_variable(
    frame: pd.DataFrame,
    definition: VariableDefinition,
    *,
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
) -> pd.Series:
    """Evaluate one trusted model variable without parsing expression text."""

    if definition.operation == "direct":
        assert definition.source is not None and definition.source_unit is not None
        if analyte_units.get(definition.source) != definition.source_unit:
            raise ClassificationModelError("direct variable unit mismatch")
        column = analyte_columns.get(definition.source)
        if column is None or column not in frame.columns:
            raise ClassificationModelError("direct variable source is missing")
        parsed = coerce_geochemical_numeric(frame[column]).values
        result = parsed * definition.scale
    else:
        assert definition.numerator is not None and definition.denominator is not None
        if (
            analyte_units.get(definition.numerator) != definition.numerator_unit
            or analyte_units.get(definition.denominator) != definition.denominator_unit
        ):
            raise ClassificationModelError("ratio variable unit mismatch")
        numerator_column = analyte_columns.get(definition.numerator)
        denominator_column = analyte_columns.get(definition.denominator)
        if (
            numerator_column is None
            or denominator_column is None
            or numerator_column not in frame.columns
            or denominator_column not in frame.columns
        ):
            raise ClassificationModelError("ratio variable source is missing")
        numerator = coerce_geochemical_numeric(frame[numerator_column]).values
        denominator = coerce_geochemical_numeric(frame[denominator_column]).values
        valid = numerator.gt(0) & denominator.gt(0)
        result = pd.Series(np.nan, index=frame.index, dtype="float64")
        result.loc[valid] = (
            numerator.loc[valid] / denominator.loc[valid] * definition.scale
        )
    return result.where(np.isfinite(result), np.nan).astype("float64")


def evaluate_model_axes(
    frame: pd.DataFrame,
    model: ClassificationModel,
    *,
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
) -> tuple[pd.Series, pd.Series, dict[str, int]]:
    definitions = {item.id: item for item in model.variables}
    x_values = evaluate_variable(
        frame,
        definitions[model.x_axis.variable],
        analyte_columns=analyte_columns,
        analyte_units=analyte_units,
    )
    y_values = evaluate_variable(
        frame,
        definitions[model.y_axis.variable],
        analyte_columns=analyte_columns,
        analyte_units=analyte_units,
    )
    valid = x_values.notna() & y_values.notna()
    if model.x_axis.scale == "log10":
        valid &= x_values.gt(0)
    if model.y_axis.scale == "log10":
        valid &= y_values.gt(0)
    x_values = x_values.where(valid)
    y_values = y_values.where(valid)
    return x_values, y_values, {
        "row_count": int(frame.shape[0]),
        "valid_coordinate_count": int(valid.sum()),
        "invalid_coordinate_count": int((~valid).sum()),
    }


def _transform(value: float, scale: str) -> float:
    if scale == "log10":
        if value <= 0:
            raise ValueError("nonpositive log coordinate")
        return math.log10(value)
    return value


def _unique_json_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClassificationModelError("classification model has duplicate JSON keys")
        result[key] = value
    return result


def _normalise_axis(value: float, axis: AxisDefinition) -> float:
    transformed = _transform(value, axis.scale)
    lower = _transform(axis.limits[0], axis.scale)
    upper = _transform(axis.limits[1], axis.scale)
    return (transformed - lower) / (upper - lower)


def _normalise_point(
    point: tuple[float, float], model: ClassificationModel
) -> tuple[float, float]:
    return (
        _normalise_axis(point[0], model.x_axis),
        _normalise_axis(point[1], model.y_axis),
    )


def _orientation(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    first_a = _orientation(first_start, first_end, second_start)
    first_b = _orientation(first_start, first_end, second_end)
    second_a = _orientation(second_start, second_end, first_start)
    second_b = _orientation(second_start, second_end, first_end)
    epsilon = 1e-12
    proper = (
        (first_a > epsilon and first_b < -epsilon)
        or (first_a < -epsilon and first_b > epsilon)
    ) and (
        (second_a > epsilon and second_b < -epsilon)
        or (second_a < -epsilon and second_b > epsilon)
    )
    if proper:
        return True

    def on_segment(
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        return (
            min(start[0], end[0]) - epsilon
            <= point[0]
            <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon
            <= point[1]
            <= max(start[1], end[1]) + epsilon
        )

    return (
        abs(first_a) <= epsilon and on_segment(second_start, first_start, first_end)
    ) or (
        abs(first_b) <= epsilon and on_segment(second_end, first_start, first_end)
    ) or (
        abs(second_a) <= epsilon and on_segment(first_start, second_start, second_end)
    ) or (
        abs(second_b) <= epsilon and on_segment(first_end, second_start, second_end)
    )


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    tolerance: float,
) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - ax, py - ay) <= tolerance
    fraction = ((px - ax) * dx + (py - ay) * dy) / length_squared
    fraction = min(1.0, max(0.0, fraction))
    nearest = (ax + fraction * dx, ay + fraction * dy)
    return math.hypot(px - nearest[0], py - nearest[1]) <= tolerance


def _inside_polygon(point: tuple[float, float], polygon: Sequence[tuple[float, float]]) -> bool:
    x_value, y_value = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        crosses = (y1 > y_value) != (y2 > y_value)
        if crosses:
            boundary_x = (x2 - x1) * (y_value - y1) / (y2 - y1) + x1
            if x_value < boundary_x:
                inside = not inside
        previous = current
    return inside


def classify_coordinates(
    x_values: Sequence[float],
    y_values: Sequence[float],
    model: ClassificationModel,
) -> list[dict[str, str | None]]:
    if len(x_values) != len(y_values):
        raise ClassificationModelError("coordinate lengths differ")
    transformed_fields = []
    for field in model.fields:
        polygon = tuple(_normalise_point(point, model) for point in field.vertices)
        transformed_fields.append((field.id, polygon))

    records: list[dict[str, str | None]] = []
    for raw_x, raw_y in zip(x_values, y_values):
        try:
            x_value = float(raw_x)
            y_value = float(raw_y)
            if not math.isfinite(x_value) or not math.isfinite(y_value):
                raise ValueError("nonfinite")
            point = _normalise_point((x_value, y_value), model)
        except (TypeError, ValueError):
            records.append({"status": "invalid", "field_id": None})
            continue
        boundary = any(
            _point_on_segment(
                point,
                polygon[index],
                polygon[(index + 1) % len(polygon)],
                model.boundary_tolerance,
            )
            for _, polygon in transformed_fields
            for index in range(len(polygon))
        )
        if boundary:
            records.append({"status": "review_boundary", "field_id": None})
            continue
        matches = [
            field_id
            for field_id, polygon in transformed_fields
            if _inside_polygon(point, polygon)
        ]
        if len(matches) == 1:
            records.append({"status": "classified", "field_id": matches[0]})
        elif len(matches) > 1:
            records.append({"status": "review_overlap", "field_id": None})
        else:
            records.append({"status": "outside", "field_id": None})
    return records


def summarize_classifications(
    records: Sequence[Mapping[str, str | None]],
) -> dict[str, dict[str, int]]:
    status_counts: dict[str, int] = {}
    field_counts: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        field_id = record.get("field_id")
        if field_id is not None:
            key = str(field_id)
            field_counts[key] = field_counts.get(key, 0) + 1
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "field_counts": dict(sorted(field_counts.items())),
    }


def add_classification_background(
    axes: Any,
    model: ClassificationModel,
    *,
    add_labels: bool = True,
) -> Any:
    """Draw reviewed field geometry without plotting or interpreting samples."""

    lines = (
        [item.vertices for item in model.display_boundaries]
        if model.display_boundaries
        else [[*field.vertices, field.vertices[0]] for field in model.fields]
    )
    for vertices in lines:
        axes.plot(
            [point[0] for point in vertices],
            [point[1] for point in vertices],
            color="#333333",
            linewidth=0.8,
            zorder=1,
        )
    for field in model.fields:
        if add_labels and field.label_position is not None:
            axes.text(
                field.label_position[0],
                field.label_position[1],
                field.label,
                ha="center",
                va="center",
                fontsize=7,
                zorder=1,
            )
    axes.set_xscale("log" if model.x_axis.scale == "log10" else "linear")
    axes.set_yscale("log" if model.y_axis.scale == "log10" else "linear")
    axes.set_xlim(*model.x_axis.limits)
    axes.set_ylim(*model.y_axis.limits)
    axes.set_xlabel(model.x_axis.label)
    axes.set_ylabel(model.y_axis.label)
    return axes


__all__ = [
    "CLASSIFICATION_MODEL_SCHEMA_VERSION",
    "MAX_CLASSIFICATION_MODEL_BYTES",
    "AxisDefinition",
    "BoundaryLineDefinition",
    "ClassificationModel",
    "ClassificationModelError",
    "FieldDefinition",
    "VariableDefinition",
    "add_classification_background",
    "classify_coordinates",
    "evaluate_model_axes",
    "evaluate_variable",
    "load_classification_model",
    "summarize_classifications",
    "validate_classification_model",
]
