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

The source-selection decision and transcription cross-check are recorded in the asset. Its domain-level numerical review remains pending; do not describe the Skill as research-ready until that review and end-to-end figure tests are complete.

## Plot requirements

- Use the conventional La-to-Lu order without Pm.
- Use a logarithmic normalized-concentration axis.
- Draw a unity reference line at `y = 1`.
- Show the normalization identifier in the axis label or figure note.
- Preserve gaps caused by missing data; do not connect across multiple missing elements.
- Export PNG, SVG, and PDF from the same figure object.

## Interpretation boundary

The automated summary may describe visible enrichment, depletion, slope, and anomalies as observations. It must not claim a unique mantle source, melting process, fractionating mineral, tectonic setting, or alteration history from an REE pattern alone.
