---
name: geoskills
description: "Inspect whole-rock geochemical tables and create validated, submission-oriented normalized element-pattern figures from CSV, TXT, or Excel data. Use GeoSkills for chondrite-normalized rare-earth-element patterns or primitive-mantle/N-MORB-normalized trace-element spider diagrams: identify sample, group, element, and supported oxide columns; verify units and invalid values; apply versioned Sun and McDonough (1989) references; export editable SVG/PDF plus 600 dpi TIFF/PNG and source data; or explain why a table cannot yet be plotted safely. Do not use the current version for TAS, Harker, isotope, discrimination, or other geochemical diagrams."
---

# GeoSkills v0.2.0 release candidate

Create reproducible REE patterns and trace-element spider diagrams through deterministic local Python scripts. Use the language model to select and explain the workflow, never to calculate normalized ratios manually.

## Development status

Treat v0.1.0 REE plotting as the stable published baseline. The v0.2.0 spider workflow is a reviewed release candidate: its scientific fixtures, real-data output, export QA, Skill validation, and user review have passed. Do not imply support for TAS, Harker, isotope, or discrimination diagrams.

## Route the request

- For chondrite-normalized La–Lu patterns, use the REE workflow.
- For multi-element primitive-mantle or N-MORB-normalized patterns, use the spider workflow.
- Stop and clarify when the requested diagram, unit, reference composition, sample column, or group column is ambiguous.

## REE workflow

1. Run `scripts/check_environment.py`.
2. Run `scripts/inspect_data.py INPUT`.
3. Confirm the worksheet, sample identifier, optional group, ppm units, and REE mapping.
4. Run `scripts/normalize_ree.py INPUT --output OUTPUT.csv`.
5. Run `scripts/plot_ree.py INPUT --output-dir OUTPUT_DIR`.
6. Inspect the final-size PNG/TIFF and return the complete figure bundle.

Use `--axes-frame full --legend-layout inside-auto` when a four-sided frame and collision-checked in-axes legend are requested. The plotter safely falls back to an outside-right legend.

## Spider workflow

1. Run `scripts/check_environment.py`.
2. Run `scripts/inspect_spider_data.py INPUT`.
3. Confirm the worksheet, sample identifier, optional group, direct elemental ppm columns, and any supported oxide columns.
4. Choose `pm-sm89`, `pm-sm89-modified`, or `nmorb-sm89`; do not select a reference from the apparent shape of the data.
5. Run `scripts/normalize_spider.py INPUT --reference pm-sm89-modified --output OUTPUT.csv`.
6. Run `scripts/plot_spider.py INPUT --reference pm-sm89-modified --output-dir OUTPUT_DIR`.
7. Inspect the final-size PNG/TIFF, the normalized source-data CSV, conversion records, warnings, and JSON report.

The spider plot defaults to a full frame, no background grid, and `inside-auto` legend placement. It exports editable SVG/PDF, 600 dpi LZW TIFF, 600 dpi PNG, exact normalized source data, and a machine-readable report from the same figure object.

## Scientific guardrails

- Require confirmed ppm units for direct element concentrations.
- Convert only explicit `K2O`, `P2O5`, and `TiO2` wt% columns to K, P, and Ti ppm. Record the CIAAW/IUPAC atomic weights, formula, and factor used.
- Preserve blanks and below-detection-limit states as gaps. Never replace them with zero or an invented detection limit.
- Reject finite zero and negative values on logarithmic axes.
- Preserve the cited Sun and McDonough (1989) incompatibility order even when the user selects a subset.
- Use only the versioned local assets `PrimitiveMantle_SM89`, `PrimitiveMantleModified_SM89`, and `NMORB_SM89` for the spider draft.
- Use the source footnote's modified primitive mantle as the spider default. Keep the printed and modified variants separate; do not silently replace Cs or Pb, and warn when an affected element is plotted with the printed variant.
- Set log limits from finite positive ratios, add a declared margin, round to clean decimal bounds without clipping, and show unity only when it lies inside the range.
- Use colour plus line style for groups and sample symbols so colour is not the sole identifier.
- Keep user data local; plotting scripts must not make network requests.
- Describe enrichment, depletion, slopes, and visible anomalies conservatively. Do not assign a unique source, melting process, mineral control, alteration history, or tectonic setting from one normalized pattern.

## Related resources

| Resource | Use it when |
|---|---|
| [scripts/inspect_data.py](scripts/inspect_data.py) | Inspect REE input |
| [scripts/normalize_ree.py](scripts/normalize_ree.py) | Normalize REE to C1 chondrite |
| [scripts/plot_ree.py](scripts/plot_ree.py) | Create the REE figure bundle |
| [scripts/inspect_spider_data.py](scripts/inspect_spider_data.py) | Inspect trace elements, units, BDL states, and supported oxides |
| [scripts/normalize_spider.py](scripts/normalize_spider.py) | Normalize trace elements to primitive mantle or N-MORB |
| [scripts/plot_spider.py](scripts/plot_spider.py) | Create the spider-diagram figure bundle |
| [assets/normalization/primitive-mantle-sm89.json](assets/normalization/primitive-mantle-sm89.json) | Audit primitive-mantle values and the Cs/Pb footnote |
| [assets/normalization/primitive-mantle-modified-sm89.json](assets/normalization/primitive-mantle-modified-sm89.json) | Audit the explicit footnote-modified Cs/Pb variant |
| [assets/normalization/nmorb-sm89.json](assets/normalization/nmorb-sm89.json) | Audit N-MORB values |
| [references/data-contract.md](references/data-contract.md) | Audit the REE input contract |
| [references/scientific-method.md](references/scientific-method.md) | Audit the REE method |
| [references/spider-method.md](references/spider-method.md) | Audit spider input, normalization, conversion, plotting, and interpretation rules |
