---
name: geoskills
description: "Create validated, submission-oriented geochemical figures from local CSV, TXT, or Excel tables. Use GeoSkills for privacy-safe data QA, deterministic same-unit ratios, Sun and McDonough (1989) chondrite-normalized REE patterns, primitive-mantle or N-MORB-normalized trace-element spider diagrams, customizable Harker diagrams, and guarded volcanic TAS classification; for explicit column/unit mapping; for a reviewable multi-task plotting recipe; or for editable SVG/PDF plus high-resolution TIFF/PNG and privacy-safe QA reports. Do not use it for isotope or tectonic-discrimination diagrams."
---

# GeoSkills v0.5 development workflow

Use deterministic local Python for all table reading, normalization, classification, plotting, and export. The language model may guide choices and explain results, but must not calculate normalized ratios, convert oxides, or classify TAS fields manually.

## Default workflow

Prefer the unified `scripts/geoskills.py` workflow:

1. Run `self-check`.
2. Inspect the user's table locally.
3. Draft a versioned YAML recipe with explicit input layout, column mappings, units, optional QA policy, optional same-unit ratios, output profile, tasks, and confirmations.
4. Keep every unverified confirmation as `false`. Never mark a scientific or data confirmation `true` merely to make the workflow continue.
5. Run `plan`. This checks the recipe, input, count-only QA summary, derived-variable summary, selected analytes, scientific assets, and expected outputs without creating figures.
6. Explain any `blocked` or `needs_confirmation` issue in plain language. Revise only after the user supplies the missing information.
7. Show the ready plan's diagram types, reference choices, dimensions, output profile, and plan ID. Obtain the user's approval before `run`.
8. Run the approved, unchanged plan.
9. Inspect final-size PNG/TIFF output, JSON reports, and Chinese QA summaries before returning the bundle.

Read [references/workflow-and-recipe.md](references/workflow-and-recipe.md) when creating or explaining a recipe.
Read [references/data-quality-and-derived-variables.md](references/data-quality-and-derived-variables.md) before configuring QA thresholds or ratios.

## Route each task

- `ree`: chondrite-normalized La–Lu patterns.
- `spider`: multi-element patterns normalized to `pm-sm89`, `pm-sm89-modified`, or `nmorb-sm89`.
- `harker`: one validated X analyte against one or more validated Y analytes.
- `tas`: volcanic-rock classification using SiO2 and Na2O + K2O.

Stop if the requested diagram is outside this fixed registry. Do not imply support for isotope, tectonic-discrimination, or other diagram families.

The generic classification-model code is a development foundation, not a fifth registered diagram. Read [references/classification-model-contract.md](references/classification-model-contract.md) before adding or reviewing any future classification asset.

## Scientific confirmation gates

Require the user or a qualified reviewer to confirm:

- input structure and worksheet;
- sample and optional group columns;
- canonical-to-source column mappings;
- wt% for major oxides and ppm for direct elemental concentrations;
- whether plotted source data may be retained;
- any user-selected main-oxide total range, composition basis, and QA review state;
- for TAS, that the samples are volcanic and whether the basis is `anhydrous-normalized` or `as-reported`.

Never infer TAS applicability from sample names or values. Do not apply volcanic TAS fields to plutonic rocks, carbonatites, kimberlites, lamproites, or strongly altered compositions. Treat `as-reported` TAS results as provisional and boundary cases as requiring review.

## Data and value safeguards

- Preserve blanks and below-detection-limit states as missing. Never replace them with zero or an invented detection limit.
- Keep QA summaries count-only in shareable plans and reports; never expose affected sample IDs, cells, or exact source extrema.
- Allow public recipe ratios only when numerator and denominator have identical declared units. Never execute formula strings or silently convert mixed units.
- Reject negative concentrations and duplicate analyte mappings.
- Permit true zero only on linear Harker or TAS axes.
- Reject finite zero and negative values on logarithmic REE or spider axes.
- Convert only explicit `K2O`, `P2O5`, and `TiO2` wt% columns to K, P, and Ti ppm, using the reviewed deterministic conversion and recording its provenance.
- Preserve the Sun and McDonough (1989) element order even for a subset.
- Do not select a normalization reference from the apparent curve shape.
- Keep the printed and footnote-modified primitive-mantle variants separate.
- Round Harker and logarithmic limits outward without clipping data. Keep TAS at the model's fixed limits.

## Figure and interpretation safeguards

- Use colour plus marker or line style so colour is not the only identifier.
- Keep editable text in SVG/PDF and export TIFF/PNG from the same figure.
- Use full borders and collision-checked in-axes legends in the unified workflow.
- Describe only visible enrichment, depletion, slope, anomaly, clustering, scatter, and covariation.
- Do not assign a unique source, melting process, mineral control, alteration history, fractional-crystallization path, or tectonic setting from one diagram.
- Treat Harker correlation as covariation, not proof of a petrogenetic process.

Read the relevant method file before explaining a scientific result:

- REE: [references/scientific-method.md](references/scientific-method.md)
- Spider: [references/spider-method.md](references/spider-method.md)
- Harker/TAS: [references/major-elements-and-tas.md](references/major-elements-and-tas.md)

## Output and privacy

Use `shareable` unless the user explicitly needs the exact plotted-data CSV:

- `shareable` returns SVG, PDF, TIFF, PNG, JSON, and QA Markdown without the plotted-data CSV.
- `local-reproducible` also retains the plotted-data CSV and marks it sensitive.

Reports must not expose absolute paths, sample identifiers, or source values. Keep all processing local; do not send user tables to a model, analytics service, or third-party server. Clearly disclose any future remote processing before it occurs.

The workflow commits a multi-task output directory only after every task succeeds. Do not bypass stale-plan checks or overwrite an existing bundle unless the user explicitly approves replacement.

## Legacy compatibility

The reviewed v0.3 scripts remain available for regression checks and advanced one-off debugging:

- `inspect_data.py`, `normalize_ree.py`, `plot_ree.py`
- `inspect_spider_data.py`, `normalize_spider.py`, `plot_spider.py`
- `inspect_major_data.py`, `plot_harker.py`, `plot_tas.py`

Prefer the unified recipe workflow for ordinary use because it adds explicit mapping, plan review, privacy profiles, and all-or-nothing multi-task output. Do not silently mix unified and legacy outputs in one result bundle.
