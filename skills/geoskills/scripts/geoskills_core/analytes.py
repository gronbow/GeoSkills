"""Canonical analyte and unit names shared by GeoSkills workflows."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


REE_ORDER = (
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
)

SPIDER_ELEMENT_ORDER = (
    "Cs",
    "Tl",
    "Rb",
    "Ba",
    "W",
    "Th",
    "U",
    "Nb",
    "Ta",
    "K",
    "La",
    "Ce",
    "Pb",
    "Pr",
    "Mo",
    "Sr",
    "P",
    "Nd",
    "F",
    "Sm",
    "Zr",
    "Hf",
    "Eu",
    "Sn",
    "Sb",
    "Ti",
    "Gd",
    "Tb",
    "Dy",
    "Li",
    "Y",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
)

MAJOR_OXIDE_ORDER = (
    "SiO2",
    "TiO2",
    "Al2O3",
    "Fe2O3T",
    "FeOT",
    "Fe2O3",
    "FeO",
    "MnO",
    "MgO",
    "CaO",
    "Na2O",
    "K2O",
    "P2O5",
    "Cr2O3",
    "NiO",
    "H2O",
    "H2O+",
    "H2O-",
    "CO2",
    "LOI",
    "Total",
)

EXTRA_TRACE_ELEMENTS = (
    "Sc",
    "V",
    "Cr",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Ag",
    "Cd",
    "In",
    "Te",
)

TRACE_ELEMENT_ORDER = tuple(
    dict.fromkeys((*EXTRA_TRACE_ELEMENTS, *SPIDER_ELEMENT_ORDER))
)

SAMPLE_NAME_ALIASES = frozenset(
    {
        "id",
        "sample",
        "samplecode",
        "sampleid",
        "samplename",
        "sampleno",
        "samplenumber",
        "specimen",
        "specimenid",
    }
)

GROUP_NAME_ALIASES = frozenset(
    {
        "area",
        "group",
        "lithology",
        "lithologicalgroup",
        "locality",
        "location",
        "region",
        "rocktype",
        "samplegroup",
        "suite",
    }
)


def clean_name(value: object) -> str:
    """Convert a label to a Unicode-normalized comparison key."""
    normalized = unicodedata.normalize("NFKC", str(value)).lower()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _analyte_key(value: object) -> str:
    """Normalize analytes while preserving the H2O +/- distinction."""
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = re.sub(r"h2o\s*\+", "h2oplus", normalized, flags=re.I)
    normalized = re.sub(r"h2o\s*[-−]\s*$", "h2ominus", normalized, flags=re.I)
    return clean_name(normalized)


_UNIT_SUFFIX_PATTERN = re.compile(
    r"[\s_\-\(\[]*(?:"
    r"ppm|mg\s*/\s*kg|"
    r"ppb|(?:u|µ|μ)g\s*/\s*kg|"
    r"wt\s*\.?\s*(?:%|pct|percent)|weight\s*percent"
    r")[\s\)\]]*\s*$",
    re.IGNORECASE,
)

_UNIT_PATTERNS = (
    (
        "ppm",
        re.compile(r"(?:^|[^a-z])(?:ppm|mg\s*/\s*kg)(?:$|[^a-z])", re.I),
    ),
    (
        "ppb",
        re.compile(
            r"(?:^|[^a-z])(?:ppb|(?:u|µ|μ)g\s*/\s*kg)(?:$|[^a-z])",
            re.I,
        ),
    ),
    (
        "wt%",
        re.compile(
            r"(?:^|[^a-z])(?:wt\s*\.?\s*(?:%|pct|percent)|"
            r"weight\s*percent)(?:$|[^a-z])",
            re.I,
        ),
    ),
)


def infer_unit(value: object) -> str:
    """Infer a unit only when the label contains an explicit unit marker."""
    normalized = unicodedata.normalize("NFKC", str(value))
    for unit, pattern in _UNIT_PATTERNS:
        if pattern.search(normalized):
            return unit
    return "unknown"


def normalize_unit(value: object) -> str:
    """Normalize one explicit unit token to ppm, ppb, wt%, or unknown."""
    normalized = unicodedata.normalize("NFKC", str(value)).strip().lower()
    if normalized in {"unknown", ""}:
        return "unknown"
    return infer_unit(f"({normalized})")


def strip_unit_suffix(value: object) -> str:
    """Remove one supported unit suffix while keeping the analyte label."""
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    return _UNIT_SUFFIX_PATTERN.sub("", normalized).strip()


@dataclass(frozen=True)
class AnalyteDefinition:
    """One canonical analyte and its accepted exact aliases."""

    canonical: str
    kind: str
    required_unit: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnalyteMatch:
    """The deterministic result of matching one table label."""

    canonical: str
    kind: str
    required_unit: str
    source_label: str
    explicit_unit: str

    def to_dict(self) -> dict[str, str]:
        return {
            "analyte": self.canonical,
            "kind": self.kind,
            "required_unit": self.required_unit,
            "source_label": self.source_label,
            "explicit_unit": self.explicit_unit,
        }


class AnalyteRegistry:
    """Exact-alias registry; it never guesses from partial label matches."""

    def __init__(self, definitions: Iterable[AnalyteDefinition]) -> None:
        self._definitions: dict[str, AnalyteDefinition] = {}
        self._aliases: dict[str, str] = {}
        for definition in definitions:
            if definition.canonical in self._definitions:
                raise ValueError(
                    f"Duplicate analyte definition: {definition.canonical}"
                )
            self._definitions[definition.canonical] = definition
            for alias in (definition.canonical, *definition.aliases):
                key = _analyte_key(alias)
                previous = self._aliases.get(key)
                if previous is not None and previous != definition.canonical:
                    raise ValueError(
                        f"Alias {alias!r} maps to both {previous} and "
                        f"{definition.canonical}"
                    )
                self._aliases[key] = definition.canonical

    @property
    def canonical_names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def get(self, canonical: str) -> AnalyteDefinition | None:
        """Return a definition by its exact canonical name."""
        return self._definitions.get(canonical)

    def match(self, value: object) -> AnalyteMatch | None:
        source_label = unicodedata.normalize("NFKC", str(value)).strip()
        canonical = self._aliases.get(
            _analyte_key(strip_unit_suffix(source_label))
        )
        if canonical is None:
            return None
        definition = self._definitions[canonical]
        return AnalyteMatch(
            canonical=definition.canonical,
            kind=definition.kind,
            required_unit=definition.required_unit,
            source_label=source_label,
            explicit_unit=infer_unit(source_label),
        )


_MAJOR_ALIASES = {
    "SiO2": ("silica",),
    "Fe2O3T": ("TFe2O3", "Fe2O3 total", "Fe2O3 tot"),
    "FeOT": ("TFeO", "FeO total", "FeO tot"),
    "LOI": ("loss on ignition",),
}


def _default_definitions() -> tuple[AnalyteDefinition, ...]:
    definitions: list[AnalyteDefinition] = []
    for analyte in MAJOR_OXIDE_ORDER:
        definitions.append(
            AnalyteDefinition(
                canonical=analyte,
                kind="major_oxide",
                required_unit="wt%",
                aliases=_MAJOR_ALIASES.get(analyte, ()),
            )
        )
    major_names = set(MAJOR_OXIDE_ORDER)
    for analyte in TRACE_ELEMENT_ORDER:
        if analyte not in major_names:
            definitions.append(
                AnalyteDefinition(
                    canonical=analyte,
                    kind="trace_element",
                    required_unit="ppm",
                )
            )
    return tuple(definitions)


DEFAULT_ANALYTE_REGISTRY = AnalyteRegistry(_default_definitions())


def match_analyte(value: object) -> AnalyteMatch | None:
    """Match a column/row label with the default GeoSkills registry."""
    return DEFAULT_ANALYTE_REGISTRY.match(value)
