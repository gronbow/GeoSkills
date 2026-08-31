# Changelog

This file records the user-visible changes in each public GeoSkills release.

## v0.7.0-rc1 — unreleased candidate

- Added a coordinate-only generic bivariate diagram using direct mapped analytes or previously reviewed same-unit ratios, with independent linear/log10 axes and grouped styling.
- Kept Zr/TiO2-Nb/Y classification boundaries out of scope; no unreviewed scientific field geometry is bundled or implied.
- Prevented shareable REE and spider figures from rendering sample identifiers while retaining group-level visual encoding.
- Removed source filenames, worksheet names, source-column labels, and selected-group values from shareable plans and reports while preserving deterministic stale-plan detection.
- Rejected duplicate YAML keys so a later key cannot silently override a scientific confirmation.
- Added fixed CSV/TXT/XLSX table budgets and pre-parse XLSX ZIP/XML defenses against resource-exhaustion input.
- Added a fixed raster-pixel budget so unsafe dimension/DPI combinations fail during recipe validation.
- Added pre-plot limits for data points, groups, and independent vector artists; over-budget tasks fail closed instead of being silently sampled or merged.
- Added a machine-readable `capabilities` command and disabled abbreviated CLI options.
- Added a runnable XY demo and a user recipe template whose confirmation gates all start disabled.
- Unified figure fonts, improved dense spider tick labels, exported RGB LZW TIFF files, and clarified that automated QA is not final scientific or visual approval.
- Pinned GitHub Actions to reviewed commit SHAs and added Dependabot configuration.
- This candidate has not been merged, tagged, or released.

## v0.6.0 — 2026-08-10

- Added an explicit, non-destructive anhydrous 100% data-basis layer. The selected oxide list is user-reviewed, source columns remain unchanged, volatile/LOI/Total columns are excluded, and invalid rows remain missing.
- Added the scientifically reviewed K2O-SiO2 magma-series diagram using the original Peccerillo and Taylor (1976) boundary extents, Rickwood's (1989) corrected `(52, 1.5)` point, and no extrapolation.
- Restricted complete four-field K2O-SiO2 classification to SiO2 48-63 wt%; visible points outside that domain remain unclassified and trigger review.
- Added versioned boundary provenance, fixed-asset hashing, publication exports, group legends, count-only reports, and end-to-end recipe support for the new diagram.
- Verified the structured `Nb/Y` and scaled `Zr(ppm)/TiO2(wt%) x 0.0001` coordinate calculations without registering Winchester-Floyd boundaries or claiming a supported diagram.
- Preserved the v0.5 QA, derived-ratio, privacy, stale-plan, atomic-output, and four existing diagram contracts.
- Validated the release with 231 automated tests, Skill structure validation, a synthetic three-task workflow, scoped shareable-artifact privacy scanning, and Ubuntu/Windows CI on Python 3.11 and 3.12.

## v0.5.0 — 2026-08-09

- Added privacy-safe table-wide QA summaries for blank or duplicate sample identifiers, missing values, below-detection-limit states, non-numeric or non-finite cells, and nonpositive values.
- Added an optional, explicitly configured major-oxide total check. GeoSkills does not invent a total range or composition basis.
- Added deterministic same-unit ratios such as `Nb/Y` or `K2O/Na2O`; arbitrary formula strings, code evaluation, and silent mixed-unit conversion remain unsupported.
- Added a versioned generic classification-model foundation with literature provenance, scientific-review state, SHA-256 pinning, strict geometry validation, log-axis handling, boundary review, and overlap review.
- Kept the public diagram registry at REE, spider, Harker, and TAS. No new scientific classification boundary is registered in this release.
- Added QA and derived-variable settings and count-only summaries to plan fingerprints and shareable reports without sample identifiers or source values.
- Validated the release with 217 automated tests, Ubuntu/Windows CI on Python 3.11 and 3.12, synthetic end-to-end plan/run checks, and scoped shareable-artifact privacy scans.

## v0.4.0 — 2026-08-08

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
- Validated the release with 196 automated tests plus synthetic and published-data regression runs.

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
