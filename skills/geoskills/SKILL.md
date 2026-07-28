---
name: geoskills
description: "Inspect whole-rock geochemical tables and create validated, submission-ready chondrite-normalized rare-earth-element pattern plots from CSV, TXT, or Excel data. Use GeoSkills v1 only for REE pattern workflows: identify La-Lu columns, check ppm units and invalid values, group samples, generate publication REE diagrams, export editable SVG/PDF plus 600 dpi TIFF/PNG and source data, or explain why a geochemical table cannot yet be plotted safely. Do not use v1 for spider diagrams, TAS, Harker diagrams, or other geochemical plots."
---

# GeoSkills v1: REE Patterns

Create reproducible REE pattern plots through a deterministic local Python workflow. Keep data processing and normalization in scripts; do not ask a language model to calculate normalized values directly.

## Development status

Treat GeoSkills v1 as an REE-only functional beta with a publication-oriented export workflow. Do not add or imply spider diagrams, TAS, Harker diagrams, or other plot types in v1. The environment checker, read-only table inspector, confirmed `Chondrite_SM89` reference, normalization command, plotting command, and automated export tests exist. Both flat tables and unambiguous transposed paper supplements are supported. Continue to report caveats and inspect every generated figure visually at its final physical size before submission.

## Workflow

1. Run `scripts/check_environment.py` with the Python interpreter that will execute the plotting workflow.
2. Run `scripts/inspect_data.py INPUT` to inspect the input file without modifying it. Allow the inspector to adapt an unambiguous elements-by-row paper supplement in memory. For a multi-sheet workbook, rerun it with `--sheet SHEET_NAME` after the user chooses a sheet.
3. Identify the worksheet, sample identifier, optional group column, REE columns, and units.
4. Stop and request clarification when units or column mappings are ambiguous.
5. Validate missing, non-numeric, zero, and negative values before logarithmic plotting.
6. Run `scripts/normalize_ree.py INPUT --output OUTPUT.csv` only after inspection passes. Use the named, versioned reference composition stored in `assets/`; do not copy values into prompts or recalculate them manually.
7. Run `scripts/plot_ree.py INPUT --output-dir OUTPUT_DIR` to generate editable SVG/PDF, 600 dpi LZW-compressed TIFF, 600 dpi PNG, normalized source-data CSV, and a JSON run report from the same figure object. The default `--y-margin 0.08` sets compact, data-led log-axis limits, then rounds them to clean powers or decimal boundaries without clipping data below or above unity. The publication default omits background gridlines; use `--grid-style major` only when a target journal or comparison needs them. Use `--axes-frame full --legend-layout inside-auto` when a four-sided plot frame and a boxed in-axes legend are required; the plotter checks for overlap and safely uses the right-side legend when no clear in-axes position exists.
8. Inspect the PNG or TIFF visually at the declared final size. Confirm readable text, unobstructed data, interpretable grayscale/symbol encoding, correct legend mapping, and that no empty log-scale decade has been retained only for a reference line.
9. Return the publication bundle with its configuration record, validation report, source data, and concise scientific caveats.

## Scientific guardrails

- Use the REE order `La, Ce, Pr, Nd, Sm, Eu, Gd, Tb, Dy, Ho, Er, Tm, Yb, Lu`; do not require Pm.
- Require concentration units to be known before normalization. The first release targets ppm input.
- Preserve missing values as gaps unless the user explicitly selects and records another policy.
- Reject zero and negative concentrations on a logarithmic axis; report affected samples and elements.
- Set log-axis limits from the finite positive normalized values, with an 8% default visual margin; use clean integer bounds at or above unity and clean decimal bounds below unity, never clip data, and do not retain an empty decade merely to display `y = 1`.
- Keep v1 limited to chondrite-normalized REE patterns. Route requests for other geochemical diagrams to a future version instead of fabricating unsupported boundaries or reference arrays.
- When a full axes frame or in-axes legend is requested, preserve the data hierarchy: show top and right spines without redundant ticks, place the legend only in a collision-free region, and fall back to a separate right-side key rather than cover data.
- Do not invent or silently substitute reference values.
- Describe visible patterns conservatively. Do not infer petrogenesis from an REE plot alone.
- Keep user data local by default and do not make network requests during plotting.

## Related resources

| Resource | Use it when |
|---|---|
| [scripts/check_environment.py](scripts/check_environment.py) | Check whether the selected Python environment contains the required packages |
| [scripts/inspect_data.py](scripts/inspect_data.py) | Read CSV, TXT, or Excel input and produce a structured validation report |
| [scripts/normalize_ree.py](scripts/normalize_ree.py) | Normalize validated ppm concentrations and create a new ratio table |
| [scripts/plot_ree.py](scripts/plot_ree.py) | Generate the validated REE figure bundle and machine-readable run report |
| [assets/normalization/chondrite-sm89.json](assets/normalization/chondrite-sm89.json) | Audit the exact `Chondrite_SM89` values, source, units, and verification record |
| [references/data-contract.md](references/data-contract.md) | Inspect columns, identifiers, units, missing values, and input errors |
| [references/scientific-method.md](references/scientific-method.md) | Implement or audit normalization, element order, axes, and interpretation limits |
