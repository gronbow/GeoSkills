# REE input data contract

This file records the first-release rules for data accepted by `plot-ree-patterns`.

## Required information

- One sample identifier column with a non-empty value for every row.
- REE concentration columns selected from `La, Ce, Pr, Nd, Sm, Eu, Gd, Tb, Dy, Ho, Er, Tm, Yb, Lu`.
- A confirmed concentration unit. The first release accepts ppm.

## Optional information

- One group column for color and legend assignment.
- A user-selected subset of samples.
- A preferred sample order.

## Column handling

- Preserve original column names and record every mapping to a canonical element name.
- Accept case and Unicode-subscript variants only when the mapping is unambiguous.
- Do not treat `Sample`, `Sample ID`, or another column as the identifier without recording the choice.
- Do not convert wt% to ppm silently.

## Invalid or incomplete data

- Report non-numeric cells with their sample and column.
- Preserve blank cells as missing values.
- Treat strings such as `<0.01`, `BDL`, and `n.d.` as detection-limit states, not as zero.
- Reject zero and negative values for logarithmic REE plots.
- Do not interpolate missing REE concentrations in the first release.

## File handling

- Accept `.csv`, tab- or comma-delimited `.txt`, and `.xlsx`.
- Ask the user to select a worksheet when an Excel file contains more than one plausible data sheet.
- Read the source without modifying it.
- Record filename, worksheet, delimiter, selected columns, and processing warnings in the run report.
