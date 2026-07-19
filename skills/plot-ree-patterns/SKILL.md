---
name: plot-ree-patterns
description: Inspect whole-rock geochemical tables and create validated chondrite-normalized rare-earth-element pattern plots from CSV, TXT, or Excel data. Use when an agent needs to identify La-Lu columns, check ppm units and invalid values, group samples, generate REE diagrams, export PNG/SVG/PDF files, or explain why a geochemical table cannot yet be plotted safely.
---

# Plot REE Patterns

Create reproducible REE pattern plots through a deterministic local Python workflow. Keep data processing and normalization in scripts; do not ask a language model to calculate normalized values directly.

## Development status

Treat this Skill as an early development scaffold. The environment checker exists, but the data reader, approved normalization registry, plotting command, and scientific tests are not yet implemented. Do not claim that a research-ready figure has been generated until those components exist and pass validation.

## Workflow

1. Run `scripts/check_environment.py` with the Python interpreter that will execute the plotting workflow.
2. Inspect the input file without modifying it.
3. Identify the worksheet, sample identifier, optional group column, REE columns, and units.
4. Stop and request clarification when units or column mappings are ambiguous.
5. Validate missing, non-numeric, zero, and negative values before logarithmic plotting.
6. Normalize only with a named, versioned reference composition stored in `assets/`.
7. Generate PNG, SVG, and PDF from the same figure object.
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
| [references/data-contract.md](references/data-contract.md) | Inspect columns, identifiers, units, missing values, and input errors |
| [references/scientific-method.md](references/scientific-method.md) | Implement or audit normalization, element order, axes, and interpretation limits |
