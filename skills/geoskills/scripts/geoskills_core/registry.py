"""Static diagram registry for the GeoSkills unified workflow.

Handler modules are imported only when a caller asks to resolve a handler, so
listing capabilities remains lightweight and cannot trigger plotting side
effects.  Every post-v0.3 diagram must pass its own scientific review before
registration.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


DIAGRAM_API_VERSION = "geoskills.diagram/v1"
BUILTIN_STYLE_PRESETS = (
    "publication-double-column",
    "publication-single-column",
    "review-preview",
)


class RegistryError(ValueError):
    """Raised when a diagram or handler is not part of the public registry."""


@dataclass(frozen=True)
class HandlerRef:
    """An import reference which stays dormant until ``resolve`` is called."""

    module: str
    attribute: str

    @property
    def reference(self) -> str:
        return f"{self.module}:{self.attribute}"

    def resolve(self) -> Any:
        try:
            module = importlib.import_module(self.module)
        except ImportError as exc:
            raise RegistryError(
                f"Handler module {self.module!r} could not be imported."
            ) from exc
        try:
            handler = getattr(module, self.attribute)
        except AttributeError as exc:
            raise RegistryError(
                f"Handler {self.reference!r} is not available."
            ) from exc
        if not callable(handler):
            raise RegistryError(
                f"Handler {self.reference!r} is not callable."
            )
        return handler


@dataclass(frozen=True)
class DiagramSpec:
    """One immutable, reviewed diagram capability."""

    id: str
    api_version: str
    display_name_zh: str
    display_name_en: str
    operation: str
    input_profile: str
    adapter: str
    inspector_handler: HandlerRef
    runner_handler: HandlerRef
    scientific_parameter_schema: Mapping[str, Any]
    style_parameter_schema: Mapping[str, Any]
    required_confirmations: tuple[str, ...]
    required_assets: tuple[str, ...]
    output_contract: Mapping[str, Any]
    privacy_contract: Mapping[str, Any]
    adapter_version: str

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic, JSON-serializable registry record."""

        return {
            "id": self.id,
            "api_version": self.api_version,
            "display_name_zh": self.display_name_zh,
            "display_name_en": self.display_name_en,
            "operation": self.operation,
            "input_profile": self.input_profile,
            "adapter": self.adapter,
            "inspector_handler": self.inspector_handler.reference,
            "runner_handler": self.runner_handler.reference,
            "scientific_parameter_schema": _plain(
                self.scientific_parameter_schema
            ),
            "style_parameter_schema": _plain(self.style_parameter_schema),
            "required_confirmations": list(self.required_confirmations),
            "required_assets": list(self.required_assets),
            "output_contract": _plain(self.output_contract),
            "privacy_contract": _plain(self.privacy_contract),
            "adapter_version": self.adapter_version,
        }


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    """Recursively freeze registry metadata exposed to callers."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


_STYLE_PARAMETER_SCHEMA = _freeze(
    {
        "allowed": ("width_mm", "height_mm", "dpi"),
        "width_mm": {"type": "number", "minimum": 30, "maximum": 500},
        "height_mm": {"type": "number", "minimum": 30, "maximum": 500},
        "dpi": {"type": "integer", "minimum": 72, "maximum": 1200},
        "additional_properties": False,
    }
)

_OUTPUT_CONTRACT = _freeze(
    {
        "atomic_bundle": True,
        "figure_formats": ("svg", "pdf", "tiff", "png"),
        "includes_source_data": True,
        "source_data_by_profile": {
            "shareable": False,
            "local-reproducible": True,
        },
        "includes_json_report": True,
        "includes_qa_summary": True,
    }
)

_PRIVACY_CONTRACT = _freeze(
    {
        "processing": "local-only",
        "shareable_report_absolute_paths": False,
        "shareable_report_source_values": False,
    }
)


def _spec(
    *,
    diagram_id: str,
    display_name_zh: str,
    display_name_en: str,
    operation: str,
    input_profile: str,
    inspector: tuple[str, str],
    runner: tuple[str, str],
    scientific_schema: Mapping[str, Any],
    confirmations: tuple[str, ...] = (),
    assets: tuple[str, ...] = (),
    adapter: str = "legacy-v0.3-function",
    adapter_version: str = "0.3.0",
) -> DiagramSpec:
    return DiagramSpec(
        id=diagram_id,
        api_version=DIAGRAM_API_VERSION,
        display_name_zh=display_name_zh,
        display_name_en=display_name_en,
        operation=operation,
        input_profile=input_profile,
        adapter=adapter,
        inspector_handler=HandlerRef(*inspector),
        runner_handler=HandlerRef(*runner),
        scientific_parameter_schema=_freeze(scientific_schema),
        style_parameter_schema=_STYLE_PARAMETER_SCHEMA,
        required_confirmations=confirmations,
        required_assets=assets,
        output_contract=_OUTPUT_CONTRACT,
        privacy_contract=_PRIVACY_CONTRACT,
        adapter_version=adapter_version,
    )


_DIAGRAMS = {
    "ree": _spec(
        diagram_id="ree",
        display_name_zh="稀土元素配分图",
        display_name_en="REE pattern",
        operation="ree_pattern_plot",
        input_profile="ree-ppm",
        inspector=("inspect_data", "inspect_path"),
        runner=("plot_ree", "plot_path"),
        scientific_schema={
            "required": ("reference", "elements"),
            "allowed": ("reference", "elements", "groups"),
            "reference": {"enum": ("chondrite-sm89",)},
            "elements": {"type": "array", "minimum_items": 3},
            "groups": {"type": "all-or-array"},
            "additional_properties": False,
        },
        assets=("assets/normalization/chondrite-sm89.json",),
    ),
    "spider": _spec(
        diagram_id="spider",
        display_name_zh="微量元素蛛网图",
        display_name_en="Trace-element spider diagram",
        operation="trace_element_spider_plot",
        input_profile="trace-elements-ppm",
        inspector=("inspect_spider_data", "inspect_spider_path"),
        runner=("plot_spider", "plot_spider_path"),
        scientific_schema={
            "required": ("reference", "elements"),
            "allowed": ("reference", "elements", "groups"),
            "reference": {
                "enum": ("pm-sm89", "pm-sm89-modified", "nmorb-sm89")
            },
            "elements": {"type": "array", "minimum_items": 5},
            "groups": {"type": "all-or-array"},
            "additional_properties": False,
        },
        assets=(
            "assets/normalization/primitive-mantle-sm89.json",
            "assets/normalization/primitive-mantle-modified-sm89.json",
            "assets/normalization/nmorb-sm89.json",
        ),
    ),
    "harker": _spec(
        diagram_id="harker",
        display_name_zh="哈克图解",
        display_name_en="Harker diagram",
        operation="harker_plot",
        input_profile="mapped-geochemistry",
        inspector=("inspect_major_data", "inspect_major_path"),
        runner=("plot_harker", "plot_harker_path"),
        scientific_schema={
            "required": ("x", "y"),
            "allowed": ("x", "y", "groups"),
            "x": {"type": "canonical-analyte"},
            "y": {"type": "canonical-analyte-or-array"},
            "groups": {"type": "all-or-array"},
            "additional_properties": False,
        },
    ),
    "tas": _spec(
        diagram_id="tas",
        display_name_zh="火山岩 TAS 分类图",
        display_name_en="Volcanic TAS classification",
        operation="tas_plot",
        input_profile="major-oxides-wt-percent",
        inspector=("inspect_major_data", "inspect_major_path"),
        runner=("plot_tas", "plot_tas_path"),
        scientific_schema={
            "required": ("composition_basis",),
            "allowed": ("composition_basis", "groups"),
            "composition_basis": {
                "enum": ("anhydrous-normalized", "as-reported")
            },
            "groups": {"type": "all-or-array"},
            "additional_properties": False,
        },
        confirmations=(
            "volcanic_samples",
            "composition_basis_reviewed",
        ),
        assets=("assets/classification/tas-lemaitre-2002.json",),
    ),
    "k2o-sio2": _spec(
        diagram_id="k2o-sio2",
        display_name_zh="K2O-SiO2 岩浆系列图",
        display_name_en="K2O-SiO2 magma-series diagram",
        operation="k2o_sio2_series_plot",
        input_profile="anhydrous-major-oxides-wt-percent",
        inspector=("inspect_major_data", "inspect_major_path"),
        runner=("plot_k2o_sio2", "plot_k2o_sio2_path"),
        scientific_schema={
            "required": ("composition_basis",),
            "allowed": ("composition_basis", "groups"),
            "composition_basis": {"enum": ("anhydrous-normalized",)},
            "groups": {"type": "all-or-array"},
            "additional_properties": False,
        },
        confirmations=(
            "volcanic_samples",
            "composition_basis_reviewed",
        ),
        assets=(
            "assets/classification/k2o-sio2-pt76-r89-original.json",
        ),
        adapter="classification-model-v1",
        adapter_version="0.6.0",
    ),
    "xy": _spec(
        diagram_id="xy",
        display_name_zh="通用二维坐标图",
        display_name_en="Generic bivariate plot",
        operation="generic_bivariate_plot",
        input_profile="mapped-geochemistry",
        inspector=("plot_xy", "inspect_xy_path"),
        runner=("plot_xy", "plot_xy_path"),
        scientific_schema={
            "required": ("x", "y"),
            "allowed": ("x", "y", "groups"),
            "x": {"type": "structured-axis-variable"},
            "y": {"type": "structured-axis-variable"},
            "groups": {"type": "all-or-array"},
            "additional_properties": False,
        },
        adapter="generic-bivariate-v1",
        adapter_version="0.7.0",
    ),
}

DIAGRAMS: Mapping[str, DiagramSpec] = MappingProxyType(_DIAGRAMS)


def diagram_ids() -> tuple[str, ...]:
    """Return the stable public diagram order."""

    return tuple(DIAGRAMS)


def get_diagram(diagram_id: str) -> DiagramSpec:
    """Return one reviewed diagram specification by exact ID."""

    try:
        return DIAGRAMS[diagram_id]
    except (KeyError, TypeError) as exc:
        available = ", ".join(diagram_ids())
        raise RegistryError(
            f"Unknown diagram {diagram_id!r}; available: {available}."
        ) from exc


def resolve_handler(diagram_id: str, kind: str) -> Any:
    """Resolve an inspector or runner only when execution is requested."""

    spec = get_diagram(diagram_id)
    if kind == "inspector":
        return spec.inspector_handler.resolve()
    if kind == "runner":
        return spec.runner_handler.resolve()
    raise RegistryError("Handler kind must be 'inspector' or 'runner'.")


def registry_snapshot() -> list[dict[str, Any]]:
    """Return all registry entries in stable, JSON-ready order."""

    return [DIAGRAMS[diagram_id].to_dict() for diagram_id in diagram_ids()]


__all__ = [
    "BUILTIN_STYLE_PRESETS",
    "DIAGRAMS",
    "DIAGRAM_API_VERSION",
    "DiagramSpec",
    "HandlerRef",
    "RegistryError",
    "diagram_ids",
    "get_diagram",
    "registry_snapshot",
    "resolve_handler",
]
