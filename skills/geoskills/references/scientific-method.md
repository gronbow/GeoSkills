# REE scientific method contract

## Normalization

For sample concentration `C_sample` and reference concentration `C_reference`, calculate:

```text
C_normalized = C_sample / C_reference
```

Perform the division in deterministic Python code. Do not ask a language model to calculate the values.

## Reference composition requirements

Do not add a normalization table until all of the following are recorded:

- short identifier and version;
- full reference name;
- element values and units;
- element order;
- complete citation and DOI where available;
- date added and independent verification status.

The first selected table is `Chondrite_SM89`, stored in `assets/normalization/chondrite-sm89.json`. It contains the C1 chondrite column from Sun & McDonough (1989), Table 1, in ppm. Its DOI is `10.1144/GSL.SP.1989.042.01.19`.

The source-selection decision, transcription cross-check, and project-owner domain confirmation are recorded in the asset.

## Plot requirements

- Use the conventional La-to-Lu order without Pm.
- Use a logarithmic normalized-concentration axis.
- Derive the y-axis range from the finite, positive normalized values. Use an 8% default margin in log space, with at least an 8% proportional margin for narrow ranges. Use clean integer display bounds at or above unity and clean decimal bounds below unity. Use the actual data minimum as a safety check so the rounded lower bound never clips a point, and record both adaptive and final limits in the run report.
- Draw a unity reference line at `y = 1` only when it lies inside the adaptive display range. When it is outside the range, retain the normalization source in the figure note and do not add an empty decade solely to show the line.
- Show the normalization identifier in the axis label or figure note.
- Preserve gaps caused by missing data; do not connect across multiple missing elements.
- Export SVG, PDF, 600 dpi TIFF, and 600 dpi PNG from the same figure object.
- Export the exact normalized ratios used by the figure as a source-data CSV.
- Use Python/matplotlib with an `Agg` backend for reproducible headless export.
- Keep SVG text editable and embed TrueType text in PDF.
- Use group colour plus group line style and a unique sample symbol so colour is not the only identifier.
- Use a white background, restrained colourblind-aware palette, thin axes, no background grid by default, and 5–7 pt text at final publication size. Permit sparse major-grid guidance only as an explicit option.
- Keep long rock-type names separate from sample IDs so the data panel is not compressed by a repetitive legend. When an in-axes key is requested, use a light boxed key only after checking that it does not intersect plotted paths or symbols.
- Allow an optional full four-sided axes frame without adding redundant top or right tick labels. Fall back to a separate right-side legend if no clear in-axes region exists, and warn when more than 15 samples may cause overplotting.
- Include only plotted samples in the sample legend. When more than 12 plotted samples require repeated symbols, record the repetition and warn instead of claiming every symbol is unique.

## Interpretation boundary

The automated summary may describe visible enrichment, depletion, slope, and anomalies as observations. It must not claim a unique mantle source, melting process, fractionating mineral, tectonic setting, or alteration history from an REE pattern alone.
