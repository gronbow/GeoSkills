# Trace-element spider-diagram contract

## Figure purpose

Use one normalized multi-element pattern to compare relative enrichment, depletion, slopes, and visible anomalies among samples or groups. Treat the plot as comparative or discovery evidence, not as a stand-alone tectonic classifier.

## Accepted input

- One unambiguous sample identifier and an optional group column.
- At least five supported elements.
- Direct elemental concentrations explicitly identified as ppm.
- Optional `K2O`, `P2O5`, and `TiO2` values explicitly identified as wt%.
- Flat row-per-sample tables or unambiguous published-supplement tables with samples in columns and unit-labelled major/trace sections.

Preserve blanks and BDL states as gaps. Reject non-numeric values that are not recognized BDL markers, duplicate mappings, and finite zero or negative values.

## Reference compositions

The local assets reproduce Sun and McDonough (1989), Table 1:

- `PrimitiveMantle_SM89`: printed Primitive mantle column.
- `PrimitiveMantleModified_SM89`: the same column with only the footnote-b Cs and Pb substitutions.
- `NMORB_SM89`: printed N-type MORB column.

Both assets record ppm units, complete element order, citation, DOI, source-table location, a pinned pyrolite v0.3.7 cross-check, and verification date.

The printed primitive-mantle asset preserves `Cs=0.032 ppm` and `Pb=0.185 ppm`. The explicit modified asset uses the source footnote recommendations `Cs=0.0079 ppm` and `Pb=0.071 ppm`, with the other 34 values unchanged. Do not mix the variants or silently substitute values.

## Oxide conversion

Reference values are elemental ppm. Convert supported major oxides by:

```text
element_ppm = oxide_wt_percent × element_mass_fraction_in_oxide × 10000
```

Use CIAAW/IUPAC standard atomic weights:

```text
O = 15.999
P = 30.973761998
K = 39.0983
Ti = 47.867
```

The resulting factors are:

```text
K2O wt% × 8301.51302183966 = K ppm
P2O5 wt% × 4364.268173626792 = P ppm
TiO2 wt% × 5993.489012708947 = Ti ppm
```

Record every conversion in the run report. When both direct element ppm and its supported oxide are present, stop for user selection.

## Normalization and order

For every selected element:

```text
normalized_ratio = sample_element_ppm / reference_element_ppm
```

Use deterministic Python. Preserve the Sun and McDonough (1989) incompatibility order defined by the selected asset, including for user-selected subsets.

## Plot and export

- Use a logarithmic y-axis.
- Preserve missing values as line breaks.
- Derive limits from finite positive ratios and round to clean decimal bounds without clipping.
- Draw a dashed unity line only when it lies inside the data-led display range.
- Use a white background, restrained colourblind-aware colours, line-style redundancy, and sample symbols.
- Use 5–7 pt final-size text and a collision-checked legend.
- Export SVG, PDF, 600 dpi LZW TIFF, 600 dpi PNG, normalized source CSV, and JSON report from one Matplotlib figure.

## Interpretation boundary

Describe observed LILE/HFSE relationships and Nb-Ta, Pb, Sr, P, or Ti anomalies cautiously. Consider analytical limits, alteration, mobility, accessory-mineral control, and source/melting alternatives. Do not infer a unique magma source, melting degree, fractionating phase, tectonic setting, or alteration history from the spider diagram alone.
