# Changelog

This file records the user-visible changes in each public GeoSkills release.

## v0.4.0 — Unreleased

- Added one provider-neutral `geoskills.py` entry point with version, environment self-check, review-only plan, and guarded run commands.
- Added strict `geoskills.recipe/v1` YAML recipes for explicit local input, worksheet, layout, canonical column mapping, units, output profile, style preset, confirmations, and up to 32 tasks.
- Added a fixed registry for the four already reviewed diagram families; this release does not add a new scientific diagram.
- Added content-addressed plans covering the recipe, input file, selected tasks, styles, tool/interface versions, and versioned scientific assets. Changed inputs or references invalidate old plans.
- Added shareable JSON reports and Chinese QA summaries without absolute paths or source values, plus an opt-in local-reproducible profile for sensitive plotted-data CSV files.
- Added whole-directory atomic multi-task output: every task succeeds before the new result replaces an existing complete bundle.
- Added shared table I/O, analyte mapping, validation, plotting style, export, error, and report modules while retaining the v0.3 command-line contracts.
- Preserved the reviewed K2O→K, P2O5→P, and TiO2→Ti spider conversions without allowing other implicit conversions.
- Added a beginner-oriented Harker + TAS multi-task recipe and workflow documentation.
- Added strict unit/header identity checks, group-subset validation, finite X–Y pair handling, and protected overwrite/recovery rules.
- Added adaptive in-frame REE/spider legends and verified SVG/PDF plus 600 dpi PNG/TIFF publication artifacts.
- Added Chinese missing-input guidance and refined TAS field-label placement for clearer beginner and visual review.
- Removed exact source-data extrema from shareable reports and added report-level safeguards against future extrema leakage.
- Validated the local candidate with 196 automated tests plus synthetic and published-data regression runs; GitHub publication remains gated on user review.

## v0.3.0 — 2026-07-30

The reviewed v0.2.0 spider-diagram milestone was not tagged separately; it is first published as part of this complete v0.3.0 release.

- Added validated primitive-mantle and N-MORB normalized trace-element spider diagrams.
- Added customizable multi-panel Harker variation diagrams with clean outward-rounded axes and shared group legends.
- Added guarded volcanic TAS classification with versioned Le Maitre/Le Bas boundaries, explicit composition-basis declarations, and boundary-review states.
- Added flat and unambiguous transposed CSV, TXT, and XLSX inspection for the new workflows.
- Added editable SVG/PDF, 600 dpi PNG/TIFF, plotted-data CSV, and machine-readable JSON export bundles.
- Preserved below-detection-limit values as missing and kept private inputs and generated outputs outside Git.
- Validated the complete release with 69 automated tests and Ubuntu/Windows CI on Python 3.11 and 3.12.

## v0.1.0 — 2026-07-28

- Published the first GeoSkills release for Sun and McDonough (1989) C1 chondrite-normalized REE patterns.
- Added local table inspection, deterministic normalization, submission-oriented exports, and scientific/privacy safeguards.
