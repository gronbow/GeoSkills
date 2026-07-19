---
name: plot-ree-patterns
description: Inspect whole-rock geochemical tables and create validated chondrite-normalized rare-earth-element pattern plots from CSV, TXT, or Excel data. Use when an agent needs to identify La-Lu columns, check ppm units and invalid values, group samples, generate REE diagrams, export PNG/SVG/PDF files, or explain why a geochemical table cannot yet be plotted safely.
---

# Plot REE Patterns

Create reproducible REE pattern plots through a deterministic local Python workflow. Keep data processing and normalization in scripts; do not ask a language model to calculate normalized values directly.

## Development status

Treat this Skill as a functional first beta. The environment checker, read-only table inspector, confirmed `Chondrite_SM89` reference, normalization command, plotting command, and automated export tests exist. Continue to report caveats and inspect every generated figure visually before using it in research output.

## Workflow

1. Run `scripts/check_environment.py` with the Python interpreter that will execute the plotting workflow.
2. Run `scripts/inspect_data.py INPUT` to inspect the input file without modifying it. For a multi-sheet workbook, rerun it with `--sheet SHEET_NAME` after the user chooses a sheet.
3. Identify the worksheet, sample identifier, optional group column, REE columns, and units.
4. Stop and request clarification when units or column mappings are ambiguous.
5. Validate missing, non-numeric, zero, and negative values before logarithmic plotting.
6. Run `scripts/normalize_ree.py INPUT --output OUTPUT.csv` only after inspection passes. Use the named, versioned reference composition stored in `assets/`; do not copy values into prompts or recalculate them manually.
7. Run `scripts/plot_ree.py INPUT --output-dir OUTPUT_DIR` to generate PNG, SVG, PDF, and a JSON run report from the same figure object.
8. Return the figures with a configuration record, validation report, and concise scientific caveats.

## Scientific guardrails

- Use the REE order `La, Ce, Pr, Nd, Sm, Eu, Gd, Tb, Dy, Ho, Er, Tm, Yb, Lu`; do not require Pm.
- Require concentration units to be known before normalization. The first release targets ppm input.
- Preserve missing values as gaps unless the user explicitly selects and records another policy.
- Reject zero and negative concentrations on a logarithmic axis; report affected samples and elements.
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
