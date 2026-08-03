# GeoSkills development rules

- Explain each development step in plain Chinese for a beginner before introducing jargon.
- Keep the portable skill independent of any specific model provider or cloud API.
- Do not invent, infer, average, or silently change geochemical reference values.
- Record the source, version, units, element order, and citation for every normalization table.
- Never commit private research data, unpublished user data, credentials, or locally downloaded GEOROC records.
- Keep scripts cross-platform for Windows and Linux; resolve resource paths relative to the script or skill directory.
- Write machine-readable results to standard output and concise diagnostics to standard error where practical.
- Add tests for numerical rules, invalid input, missing values, non-positive values, and exported files.
- Do not claim the skill is research-ready until scientific fixtures and end-to-end tests pass.
- Preserve the published v0.3.0 REE, spider, Harker, and volcanic TAS workflows.
- Keep the v0.4 unified entry point, recipe, plan, report, and fixed diagram registry backward compatible within their versioned schemas.
- Never set a recipe confirmation to `true` without an explicit human confirmation.
- Keep default plans and reports free of absolute paths, sample identifiers, and source values.
- Invalidate saved plans whenever the recipe, input content, tool/interface version, selected task, style, or scientific asset changes.
- Commit multi-task outputs only as a complete directory; a failed task must not leave a partial replacement.
- Add post-v0.3.0 diagram families only through separate scientific review and validation; defer isotope and tectonic-discrimination diagrams until those workflows are explicitly reviewed.
- Require explicit volcanic applicability and composition-basis declarations before TAS plotting; never silently classify intrusive or otherwise out-of-scope samples.
