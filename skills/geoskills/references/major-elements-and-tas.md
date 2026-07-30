# Major-element, Harker, and TAS contract

## Harker purpose

Use Harker variation diagrams to show how selected oxides or elements covary with a declared differentiation index. Use `SiO2` as the conventional default x variable, but permit another validated analyte when the user explicitly selects it.

Treat the panels as comparative evidence. Do not infer fractional crystallization, magma mixing, assimilation, source variation, or alteration from correlation alone. Do not add regression lines by default.

## Accepted input

- One unambiguous sample identifier and an optional group column.
- At least two explicitly unit-labelled geochemical analytes.
- Major oxides in wt% and direct elemental concentrations in ppm.
- Flat row-per-sample tables or unambiguous published-supplement tables with samples in columns and unit-labelled major/trace sections.

Preserve blanks and below-detection-limit states as missing points. Reject non-numeric values, duplicate analyte mappings, and negative concentrations. Zero is permitted on linear axes.

## TAS applicability

TAS uses:

```text
x = SiO2 (wt%)
y = Na2O (wt%) + K2O (wt%)
```

Require an explicit confirmation that the samples are volcanic. Require the user to state whether the input is already on a volatile-free/anhydrous 100% basis or is being plotted as reported. The current version records that declaration but does not silently recalculate analyses.

Do not use volcanic TAS names as the IUGS classification of plutonic rocks, carbonatites, kimberlites, lamproites, or strongly altered compositions. Report an as-reported classification as provisional.

## TAS fields

Use the versioned `TAS_LeMaitre2002_Volcanic_CombinedT` asset. It records the volcanic field names recommended in Le Maitre et al. (2002), the boundary-construction paper by Le Bas et al. (1992), and a pinned pyrolite v0.3.7 cross-check.

Keep `Trachyte/Trachydacite` and `Tephrite/Basanite` unresolved because those distinctions need normative information not supplied by SiO2 and total alkalis alone. Mark an analysis exactly on a field boundary as `review_required`; do not choose a side silently.

## Plot and export

- Use a white background and full four-sided axes by default.
- Use colour plus marker shape for groups.
- Use one shared, width-checked legend and one common X-axis title for a Harker grid.
- Choose a compact Harker panel layout automatically while retaining an explicit column override.
- Place the TAS legend inside only when it does not overlap points or field labels; otherwise move it outside-right.
- Use clean outward-rounded linear limits for Harker panels without clipping data.
- Keep the TAS model at its fixed declared limits so field geometry is not visually distorted.
- Export SVG, PDF, 600 dpi LZW TIFF, 600 dpi PNG, exact source-data CSV, and a JSON report from the same Matplotlib figure.

## References

- Harker, A. (1909), *The Natural History of Igneous Rocks*.
- Le Bas, M.J., Le Maitre, R.W. and Woolley, A.R. (1992), *Mineralogy and Petrology* 46, 1–22. DOI: `10.1007/BF01160698`.
- Le Maitre, R.W. (ed.) et al. (2002), *Igneous Rocks: A Classification and Glossary of Terms*, 2nd ed. DOI: `10.1017/CBO9780511535581`.
