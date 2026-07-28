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
- Keep GeoSkills v1 limited to REE pattern plots; do not add other geochemical diagram types before a versioned scope change.
