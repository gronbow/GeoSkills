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

The first approved table has not yet been selected. Until it is added to `assets/`, plotting must stop with a clear error rather than using guessed values.

## Plot requirements

- Use the conventional La-to-Lu order without Pm.
- Use a logarithmic normalized-concentration axis.
- Draw a unity reference line at `y = 1`.
- Show the normalization identifier in the axis label or figure note.
- Preserve gaps caused by missing data; do not connect across multiple missing elements.
- Export PNG, SVG, and PDF from the same figure object.

## Interpretation boundary

The automated summary may describe visible enrichment, depletion, slope, and anomalies as observations. It must not claim a unique mantle source, melting process, fractionating mineral, tectonic setting, or alteration history from an REE pattern alone.
