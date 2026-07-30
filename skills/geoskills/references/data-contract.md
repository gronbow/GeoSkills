# REE input data contract

This file records the REE input rules introduced in GeoSkills v0.1.0 and retained in v0.3.0.

## Required information

- One sample identifier column with a non-empty value for every row.
- REE concentration columns selected from `La, Ce, Pr, Nd, Sm, Eu, Gd, Tb, Dy, Ho, Er, Tm, Yb, Lu`.
- A confirmed concentration unit. Direct REE concentrations are accepted in ppm.

## Optional information

- One group column for color and legend assignment.
- A user-selected subset of samples.
- A preferred sample order.

## Column handling

- Preserve original column names and record every mapping to a canonical element name.
- Accept case and Unicode-subscript variants only when the mapping is unambiguous.
- Do not treat `Sample`, `Sample ID`, or another column as the identifier without recording the choice.
- Do not convert wt% to ppm silently.
- Accept both a flat table with one sample per row and a published-supplement layout with one sample per column when the sample row, element-label column, and ppm section are unambiguous.
- For an automatically transposed table, record the original sample-header row, group row, element-label column, inferred unit, and transformation method in the run report.
- Do not rewrite the published source workbook; construct the row-per-sample representation only in memory.

## Invalid or incomplete data

- Report non-numeric cells with their sample and column.
- Preserve blank cells as missing values.
- Treat strings such as `<0.01`, `BDL`, and `n.d.` as detection-limit states, not as zero.
- Reject zero and negative values for logarithmic REE plots.
- Do not interpolate missing REE concentrations.

## File handling

- Accept `.csv`, tab- or comma-delimited `.txt`, and `.xlsx`.
- Ask the user to select a worksheet when an Excel file contains more than one plausible data sheet.
- Read the source without modifying it.
- Record filename, worksheet, delimiter, selected columns, and processing warnings in the run report.
