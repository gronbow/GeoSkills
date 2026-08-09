# GeoSkills v0.6 配方与安全运行流程

本页解释统一工作流。v0.6 保留 REE、蛛网图、Harker 和 TAS，并加入显式无水100%数据基准与经复核的 K2O-SiO2 图；所有图仍在同一套可检查、可重复流程中运行。

## 先理解三个词

- **配方（recipe）**：类似实验记录表。它写明数据文件、列名、单位、图解参数、输出位置和人工确认项。
- **计划（plan）**：GeoSkills 检查配方和数据后生成的“运行前清单”。此阶段不出图。
- **运行（run）**：只有计划状态为 `ready`，且配方、数据和内置参考都没有改变时，才生成图件。

计划含有输入文件和科学参考文件的 SHA-256 校验值。任何内容变化都会产生新的计划编号，因此旧计划不能静默用于新数据。

## 推荐流程

### 普通 Codex 用户

上传或指定本地数据文件后，直接要求 Codex 使用 GeoSkills 检查数据并起草配方。GeoSkills 应先运行 `self-check`，再生成计划供你审核；普通用户不需要手动输入下面的开发命令。任何科学或数据确认项都必须由人实际核对，不能由模型为了继续运行而代填为 `true`。

### 开发者或手动复现

以下命令都从完整的 GeoSkills 仓库根目录运行。Windows PowerShell 使用仓库内的独立 Python 环境：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\geoskills.py self-check
.\.venv\Scripts\python.exe skills\geoskills\scripts\geoskills.py plan my-work\recipe.yaml --output my-work\plan.json
.\.venv\Scripts\python.exe skills\geoskills\scripts\geoskills.py run my-work\recipe.yaml --plan my-work\plan.json
```

macOS 或 Linux 也从仓库根目录运行：

```bash
python3 skills/geoskills/scripts/geoskills.py self-check
python3 skills/geoskills/scripts/geoskills.py plan my-work/recipe.yaml --output my-work/plan.json
python3 skills/geoskills/scripts/geoskills.py run my-work/recipe.yaml --plan my-work/plan.json
```

终端中的 `plan` 结果只提供状态、计划编号、计划文件名和问题摘要。任务、列映射、单位、科学参考、样式和预期输出保存在 `--output` 指定的计划 JSON 中；请让 Codex 打开并概括该文件，或用文本编辑器查看。不要手工修改计划 JSON，也不要为了让程序继续运行而直接把确认项改成 `true`；只有在人确实核对过对应内容后才能修改配方、重新生成计划。

`examples/` 中的确认项只针对随仓库发布的合成数据。复制示例给自己的数据时，应先把确认项重置为 `false`。

## 命令与返回状态

统一命令只在标准输出写一条 JSON，方便 Codex、DeepSeek 或其他本地 Agent 稳定读取：

- `version`：显示工具版本和图解接口版本；
- `self-check`：检查运行依赖；默认不显示本地可执行文件路径；
- `self-check --dev`：额外检查测试依赖；
- `self-check --include-paths`：仅在明确需要排错时显示本地 Python 路径；
- `plan RECIPE --output PLAN`：检查并保存计划，不生成图件；
- `plan ... --task TASK_ID`：只规划指定任务，可重复提供；
- `run RECIPE --plan PLAN`：复核计划后运行；
- `--overwrite-plan` 或 `--overwrite`：明确允许替换已有计划或完整输出目录。

退出码：

- `0`：`ready`；
- `1`：配置、环境或执行错误；
- `2`：`blocked`、`needs_confirmation` 或 `review`。

`review` 与阻断不同：如果 `run` 返回 `review`，完整图件已经生成并提交到输出目录，但存在边界样品等必须人工复核的科学状态。`blocked` 或 `needs_confirmation` 表示尚未通过安全门，不会提交新的最终图件。退出码 `2` 用于防止自动流程把这些状态误认为投稿就绪。

## 最小配方结构

```yaml
schema_version: geoskills.recipe/v1

input:
  file: data.csv
  sheet: null
  layout: row-per-sample

columns:
  sample_id: Sample
  group: Group
  mapping:
    La: La_ppm
    Ce: Ce_ppm
    Pr: Pr_ppm
    Nd: Nd_ppm
    Sm: Sm_ppm
  units:
    major_oxides: wt%
    trace_elements: ppm

quality:
  duplicate_sample_ids: error
  non_numeric_values: error
  major_oxide_total: null

derived_variables:
  - id: La_Ce
    operation: ratio
    numerator: La
    denominator: Ce
    input_unit: ppm

output:
  directory: geoskills-output
  report_profile: shareable

presets: {}

confirmations:
  input_structure_reviewed: true
  column_mapping_reviewed: true
  units_reviewed: true
  plotted_data_export_reviewed: true
  data_quality_reviewed: true

tasks:
  - id: ree-main
    diagram: ree
    stem: figure-ree
    preset: publication-double-column
    parameters:
      reference: chondrite-sm89
      elements: [La, Ce, Pr, Nd, Sm]
      groups: all
    confirmations: {}
```

`columns.mapping` 的方向固定为“标准分析物名称 → 原始表列名”。GeoSkills 不会用近似拼写猜测映射。

`plotted_data_export_reviewed: true` 只表示已经核对 `report_profile` 的导出后果：`shareable` 不保留逐样品 CSV，`local-reproducible` 会保留敏感 CSV。它不表示允许把数据上传到模型、分析服务或第三方服务器。

`quality`、`derived_variables` 和 `data_basis` 都是可选字段。省略 `quality` 时仍会采用保守默认值：重复样品编号和非数字/非有限内容作为错误，不开启主量总量范围检查。配置 `data_basis` 时必须明确提供 `data_basis_reviewed`；模型不能代替用户确认。完整规则见 [数据质控、组成基准与派生比值](data-quality-and-derived-variables.md)。

## 输入

- `input.file` 必须是配方目录内的 `.csv`、`.txt` 或 `.xlsx`；
- `input.sheet` 在多工作表 Excel 中必须明确填写；
- `input.layout` 可为 `row-per-sample`、`analyte-per-row` 或 `auto`；
- 路径必须是安全相对路径，不能使用网址、绝对路径、环境变量、通配符或 `..`；
- `output.directory` 必须是专用子目录，不能写成 `.`，也不能包含原始输入文件；
- 计划 JSON 不能覆盖配方或原始输入，也不能放在最终输出目录内；
- 一个配方最多 32 个任务，配方文件最大 256 KiB。

`input.file` 和 `output.directory` 都相对于配方文件所在目录解析；命令行中的 `--output` 和 `--plan` 则相对于当前命令目录解析。例如，配方位于 `my-work/recipe.yaml` 且写有 `output.directory: results` 时，图件会进入 `my-work/results/`。

论文补充材料常见的“分析物在行、样品在列”表可使用 `analyte-per-row`。只有结构唯一且可确认时才会自动转置。

## 单位与固定换算

- 主量氧化物必须明确为 `wt%`；
- 直接元素浓度必须明确为 `ppm`；
- K、P、Ti 若没有直接 ppm 列，可分别映射 `K2O`、`P2O5`、`TiO2` 的 wt% 列，蛛网图绘图器再使用已审核的固定化学计量换算；
- 不支持其他隐式单位换算。
- 配方中的普通派生比值只允许相同单位相除，例如 `Nb/Y` 或 `K2O/Na2O`；不支持任意公式字符串、代码执行或混合单位比值。

如果原始列名已经明确写出分析物或单位，例如 `La_ppb` 或 `Ce_ppm`，但配方把它声明为另一单位或另一分析物，计划会直接阻止运行。GeoSkills 不会把这种冲突当作“用户自定义映射”而静默改名；需要先回到原始数据和方法说明核对。

## 任务

每个任务需要唯一的 `id` 和 `stem`。

REE：

```yaml
diagram: ree
parameters:
  reference: chondrite-sm89
  elements: [La, Ce, Pr, Nd, Sm, Eu, Gd, Tb, Dy, Ho, Er, Tm, Yb, Lu]
  groups: all
```

蛛网图：

```yaml
diagram: spider
parameters:
  reference: pm-sm89-modified
  elements: [Rb, Ba, Th, U, Nb, Ta, K, La, Ce, Pb, Pr, Sr, P, Nd, Sm, Zr, Hf, Eu, Ti]
  groups: all
```

Harker：

```yaml
diagram: harker
parameters:
  x: SiO2
  y: [TiO2, Al2O3, Fe2O3T, MgO, CaO, Na2O, K2O, P2O5]
  groups: all
```

TAS：

```yaml
diagram: tas
parameters:
  composition_basis: anhydrous-normalized
  groups: all
confirmations:
  volcanic_samples: true
  composition_basis_reviewed: true
```

TAS 的两个专属确认项不能由模型根据文件名或数值自行推断。使用 `as-reported` 时还必须由用户明确接受其初步分类性质，并提供第三个确认项：

```yaml
diagram: tas
parameters:
  composition_basis: as-reported
  groups: all
confirmations:
  volcanic_samples: true
  composition_basis_reviewed: true
  provisional_classification_accepted: true
```

只有在用户理解并接受“该分类只是初步结果”后，才能将 `provisional_classification_accepted` 设为 `true`。

K2O-SiO2：

```yaml
data_basis:
  operation: normalize-to-100
  basis: anhydrous-100
  analytes: [SiO2, TiO2, Al2O3, Fe2O3T, MnO, MgO, CaO, Na2O, K2O, P2O5]

confirmations:
  data_basis_reviewed: true

tasks:
  - id: k2o-main
    diagram: k2o-sio2
    stem: figure-k2o-sio2
    preset: publication-double-column
    parameters:
      composition_basis: anhydrous-normalized
      groups: all
    confirmations:
      volcanic_samples: true
      composition_basis_reviewed: true
```

该任务还要求配方顶层存在经确认的 `data_basis`，且氧化物列表至少包含 `SiO2` 和 `K2O`。文献边界不外推；`SiO2 = 48–63 wt%` 之外的可见样品只绘点、不自动分类。

## 图件预设

内置预设：

- `publication-double-column`：183 × 120 mm，600 dpi；
- `review-preview`：150 × 100 mm，300 dpi，适合快速审核。

可以建立自定义预设，但只能继承上述预设并覆盖 `width_mm`、`height_mm` 和 `dpi`：

```yaml
presets:
  journal-main:
    extends: publication-double-column
    style:
      width_mm: 183
      height_mm: 120
      dpi: 600
```

统一工作流默认使用完整四边框，并自动安排图例以尽量避免遮挡数据或超出图幅。v0.4 配方中的自定义预设只负责图幅宽度、高度和 dpi。

## 输出与隐私

`shareable`：

- 输出 SVG、PDF、TIFF、PNG、JSON 报告和中文 QA 摘要；
- 不保留逐样品绘图数据 CSV；
- 报告不含绝对路径或源数据值。

`local-reproducible`：

- 额外保留 `*.source_data.csv`；
- CSV 被标记为敏感的绘图源数据，不应公开分享；
- JSON 和 QA 报告本身仍保持不含绝对路径和源数据值。

`output.directory` 是相对于配方目录的安全路径，不是相对于计划 JSON 的位置。计划文件和图件目录可以位于不同位置。

多任务运行先写入同一文件系统上的临时目录。只有全部任务成功，整个输出目录才一次性替换到最终位置。任一任务失败时，新结果全部取消，已有完整输出不会被半成品覆盖。

运行时会先在私有临时目录建立输入快照，再用同一快照完成校验和绘图。`--overwrite` 只允许替换带有有效 `run.report.json` 的 GeoSkills 完整输出；普通文件夹即使同名也会被保护并拒绝覆盖。

典型目录：

```text
geoskills-output/
├── run.report.json
├── run.qa.md
├── ree-main/
│   ├── figure-ree.svg
│   ├── figure-ree.pdf
│   ├── figure-ree.tiff
│   ├── figure-ree.png
│   ├── figure-ree.report.json
│   └── figure-ree.qa.md
└── harker-main/
    └── ...
```

## 常见非 `ready` 状态与停止原因

- `needs_confirmation`：配方中仍有 `false` 的人工确认项，或质控/派生摘要需要复核但尚未确认；
- `blocked`：输入结构、列映射、单位、数据质控错误、所需分析物或科学适用性未通过；
- `review`：图件已经生成，但边界样品或其他科学状态必须人工复核；
- 旧计划失效：配方、输入文件、任务参数、内置参考或工具版本发生变化；
- 输出已存在：需要先审核旧结果，再明确使用 `--overwrite`；
- 多工作表未选择：在 `input.sheet` 填写准确工作表名称。

错误不是“程序不听话”，而是可复现研究中的安全门。应修正原因并重新生成计划，不应绕过检查。
