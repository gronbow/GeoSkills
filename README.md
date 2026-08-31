# GeoSkills

GeoSkills 是一个面向地质学与地球化学研究的本地 Agent Skill。

当前正式版本仍为 [v0.6.0](https://github.com/gronbow/GeoSkills/releases/tag/v0.6.0)。本分支是尚未发布的 v0.7.0 候选版：增加通用二维坐标图、安全输入预算和更严格的可分享图件隐私保护。

## 三步开始（普通用户）

1. 在 Codex 中说明“使用 GeoSkills”，并提供本地 CSV、TXT 或 XLSX 文件。
2. 说明想画的图；二维散点图还需说明 X、Y 变量以及是否使用线性或对数轴。
3. 先审核 GeoSkills 给出的数据映射和计划，确认无误后再批准出图。

默认的 `shareable` 输出不会保留绘图数据 CSV，也不会把样品编号写进 REE、蛛网图或通用二维图。所有运算都在本地完成。

## 当前可以做什么

- 读取 `.csv`、逗号或制表符分隔的 `.txt`、以及 `.xlsx`；
- 识别常见的“每行一个样品”表格；
- 在结构明确时，自动转换论文补充材料常见的“样品在列、元素在行”表格；
- 检查样品编号、ppm 单位、缺失值、低于检出限、非数字、零和负数；
- 在可分享计划和报告中用计数汇总空白/重复编号、缺失、检出限、非数字、无穷和非正值，不暴露问题样品或具体测值；
- 按用户明确给出的氧化物列表、范围和数据基础执行可选主量总量检查；
- 在不覆盖原始列的内部副本中，按用户明确确认的氧化物列表换算无水100%组成基准；
- 计算 `Nb/Y`、`K2O/Na2O` 等同单位固定比值，不执行任意公式或静默混合单位；
- 使用 Sun & McDonough（1989）C1 球粒陨石值标准化 La–Lu；
- 使用 Sun & McDonough（1989）原始地幔、脚注明确修改的原始地幔或 N-MORB 值生成微量元素蛛网图；
- 对明确标为 wt% 的 `K2O`、`P2O5`、`TiO2` 作可追溯的元素 ppm 换算；
- 以 SiO2 或用户指定变量为横轴，一次生成一幅或多幅 Harker 变化图；
- 使用 SiO2 与 Na2O + K2O 绘制火山岩 TAS 图，并输出逐样品分类与边界复核状态；
- 使用 Rickwood（1989）核对并更正的 Peccerillo–Taylor（1976）原始边界绘制 K2O-SiO2 图，边界不外推；
- 生成投稿尺寸的 REE、蛛网图、Harker、TAS 或 K2O-SiO2 图件，并输出 SVG、PDF、600 dpi TIFF、600 dpi PNG；
- 用已映射分析物或经审核的同单位比值绘制坐标型通用二维图；X/Y 可独立选择线性或对数轴，但不自动添加分类边界；
- 用一个 YAML 配方明确记录数据文件、列映射、单位、科学参数和人工确认项；
- 在出图前生成不含源数据值的计划，数据或参考文件变化后旧计划自动失效；
- 用一个配方从同一数据表运行一个或多个图件任务，所有任务成功后才提交完整输出；
- 在出图前检查表格、像素、数据点、分组和独立绘图对象的固定资源上限；超限时完整拒绝，不静默抽样或合并；
- 输出机器可读的 JSON 报告和中文 QA 摘要；
- 可在 `local-reproducible` 模式保留实际绘图数据 CSV，或在 `shareable` 模式省略该敏感文件；
- 统一工作流默认使用完整四边框，并自动安排图例以尽量避免遮挡数据或超出图幅；
- 全程在本地处理数据，绘图脚本不请求网络服务。

## 安装到 Codex

公开仓库的默认分支 `main` 包含经过审核和自动测试的正式 v0.6.0：

```text
https://github.com/gronbow/GeoSkills
```

也可以手动把 `skills/geoskills` 文件夹复制到 Codex 的个人 Skill 目录：

```text
%USERPROFILE%\.codex\skills\geoskills
```

如果设置了 `CODEX_HOME`，则复制到 `%CODEX_HOME%\skills\geoskills`。复制完成后，重新开启一个 Codex 任务即可使用。

### 普通用户：直接在 Codex 中使用

如果只想用自己的数据出图，不需要手动输入后文的开发命令。重新开启一个 Codex 任务，上传或指定本地数据文件，然后说明希望使用 GeoSkills 绘制哪类图。GeoSkills 会先检查本地环境和数据，再起草配方与计划供你审核；它不会替你把尚未核对的科学确认项设为 `true`。

如果环境检查提示缺少依赖，可以让 Codex 解释缺少什么，并在你同意后完成本地安装。

## 开发者：Windows 本地命令测试

以下命令用于开发、审核或手动复现工作流，均应在完整的 GeoSkills 仓库根目录运行。需要 Python 3.11 或 3.12。先运行 `python --version` 确认版本，然后在 PowerShell 中创建独立环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

如果系统只提供 Python Launcher，可以把第一条命令改为 `py -3.12 -m venv .venv`。

## v0.7 统一工作流候选版

可以把“配方”理解为一张实验记录表，把“计划”理解为正式运行前的核对清单：

```text
数据 + 配方 → plan（只检查，不出图）→ 人工审核 → run（一次性生成完整结果）
```

若要用命令行复现流程，先检查环境：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\geoskills.py self-check
```

仓库提供四个可以直接配合合成数据运行的示例配方，以及一个所有确认项均关闭的安全模板：

| 配方 | 任务 |
|---|---|
| `geoskills_ree_workflow.yaml` | REE 配分图 |
| `geoskills_spider_workflow.yaml` | 微量元素蛛网图 |
| `geoskills_major_workflow.yaml` | 同时生成 Harker、TAS 和 K2O-SiO2 |
| `geoskills_xy_workflow.yaml` | 通用二维坐标图 |
| `user_recipe_template.yaml` | 自有数据起点；需替换占位字段并逐项审核 |

例如，先为主量元素三任务配方生成计划：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\geoskills.py plan skills\geoskills\examples\geoskills_major_workflow.yaml --output outputs\major-plan.json
```

此命令不会生成图件。终端只显示状态、计划编号、计划文件名和问题摘要；完整的任务、列映射、单位、参考文件、图件尺寸和输出模式保存在 `outputs\major-plan.json`。请让 Codex 打开并概括该文件，或用文本编辑器查看。状态为 `ready` 且内容经人工核对后，再运行：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\geoskills.py run skills\geoskills\examples\geoskills_major_workflow.yaml --plan outputs\major-plan.json
```

`--plan outputs\major-plan.json` 只指定计划文件的位置。图件位置由配方中的 `output.directory` 决定，并相对于配方文件所在目录解析。因此，本示例的图件位于 `skills\geoskills\examples\generated\geoskills-major-workflow\`，而不在 `outputs\`。

如果 `run` 返回 `review`，图件已经生成，但存在边界样品等必须人工复核的科学状态。`blocked` 或 `needs_confirmation` 则表示安全检查尚未通过，不会提交新的最终图件。

默认 `shareable` 模式不保留逐样品绘图数据 CSV，便于分享图件与报告；需要完全本地复现时，可在配方中改为 `local-reproducible`。该模式会保留敏感 CSV，不应直接上传公开仓库。将 `plotted_data_export_reviewed` 设为 `true`，只表示已经核对这种导出后果，不表示允许把数据上传到模型或第三方服务。

可分享计划和报告还会省略原始文件名、工作表名、源列名，并把明确选择的分组值替换为数量与摘要哈希。图件仍会保留分组图例，因为分组是科研图的可见语义；若分组名包含地点、项目代号或其他敏感信息，应先在本地副本中改为可公开名称，再确认 `plotted_data_export_reviewed`。

示例配方中的确认项只适用于仓库内已审核的合成数据。自己的数据应从 `user_recipe_template.yaml` 开始；该模板不会预先替你作出任何确认。

配方字段、质控/组成基准/派生比值、六类任务示例、返回状态和常见错误见 [配方与安全运行流程](skills/geoskills/references/workflow-and-recipe.md)、[数据质控、组成基准与派生比值](skills/geoskills/references/data-quality-and-derived-variables.md) 和 [K2O-SiO2 科学合同](skills/geoskills/references/k2o-sio2-method.md)。对于旧项目或高级排错，下列 v0.3 单脚本命令仍保持兼容。

## v0.3 单脚本兼容命令

先检查示例数据：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\inspect_data.py skills\geoskills\examples\synthetic_ree_data.csv
```

生成标准化数据：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\normalize_ree.py skills\geoskills\examples\synthetic_ree_data.csv --output outputs\synthetic_ree_normalized.csv
```

生成完整四边框和自动避让图例的投稿图件：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\plot_ree.py skills\geoskills\examples\synthetic_ree_data.csv --output-dir outputs\ree_figure --axes-frame full --legend-layout inside-auto
```

检查蛛网图示例数据：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\inspect_spider_data.py skills\geoskills\examples\synthetic_spider_data.csv
```

生成原始地幔标准化蛛网图：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\plot_spider.py skills\geoskills\examples\synthetic_spider_data.csv --reference pm-sm89-modified --output-dir outputs\spider_figure
```

默认方案为原文脚注推荐的 `pm-sm89-modified`；也可以明确选择 Table 1 印刷版 `pm-sm89` 或 `nmorb-sm89`。程序不会根据曲线形状替用户猜测标准化方案。

检查 Harker/TAS 所需的主量元素数据：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\inspect_major_data.py skills\geoskills\examples\synthetic_major_element_data.csv
```

生成默认八面板 Harker 图：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\plot_harker.py skills\geoskills\examples\synthetic_major_element_data.csv --x SiO2 --y TiO2,Al2O3,Fe2O3T,MgO,CaO,Na2O,K2O,P2O5 --output-dir outputs\harker_figure
```

`--x` 和 `--y` 都可以按数据列自定义。程序默认不画回归线，也不会把相关性直接解释为分离结晶或岩浆混合。
默认八面板会自动排成紧凑的 4 × 2 网格，并共用一个横轴标题；较长的分组图例会自动换行，避免超出图幅。

生成火山岩 TAS 图：

```powershell
.\.venv\Scripts\python.exe skills\geoskills\scripts\plot_tas.py skills\geoskills\examples\synthetic_major_element_data.csv --confirm-volcanic --composition-basis anhydrous-normalized --output-dir outputs\tas_figure
```

TAS 命令要求明确确认样品属于火山岩，并声明数据是无水归一化值还是原始报告值。程序不会把侵入岩、碳酸岩或其他不适用样品静默套入火山岩名称。

程序不会修改原始表格。重复使用同一输出名称时，只有显式加入 `--overwrite` 才会替换已有结果。

## 项目结构

```text
GeoSkills/
├── README.md
├── CHANGELOG.md
├── AGENTS.md
├── requirements-dev.txt
├── skills/
│   └── geoskills/
│       ├── SKILL.md
│       ├── agents/openai.yaml
│       ├── assets/
│       │   ├── normalization/
│       │   └── classification/
│       ├── examples/
│       ├── references/
│       └── scripts/
│           ├── geoskills.py
│           └── geoskills_core/
└── tests/
```

## 科学与隐私边界

- 直接元素浓度必须明确为 ppm；只有 `K2O`、`P2O5`、`TiO2` 可在明确为 wt% 时换算。
- 缺失值和低于检出限状态保留为曲线断点；零和负数会阻止对数坐标绘图。
- 标准化表包含文献、DOI、表格位置、版本和核对记录。
- 原始地幔表保留文献 Table 1 的 Cs、Pb 数值，并明确提示原文脚注中的 modified 版本；程序不会静默混用。
- Harker 图只展示变量间的协变关系；默认不添加拟合线，也不从相关性单独推断岩浆过程。
- TAS 边界使用带文献与版本信息的本地资产。恰好位于边界上的样品标为 `review_required`，不会静默选择一侧。
- TAS 仅用于明确确认的火山岩；`as-reported` 结果标为初步分类，不能替代无水归一化后的专业判断，并且必须由用户明确设置 `provisional_classification_accepted: true`。
- K2O-SiO2 只接受明确的无水100%基准和火山岩适用性确认；边界不外推，完整四分区范围为 SiO2 48–63 wt%，范围外样品不强制分类。
- 图形可以展示富集程度、斜率和平行性，但不能单独证明岩浆源区、部分熔融、分离结晶或构造环境。
- 统一计划和可分享报告默认不含绝对路径、样品编号或源数据值。
- 配方、数据、工具版本或内置参考文件发生变化时，必须重新生成计划。
- 主量总量阈值和 `composition_basis` 必须由用户或专业人员明确给出；程序不会自行发明通用合格范围。
- 普通派生比值只接受相同已声明单位，逐样品结果不会进入可分享报告。
- 通用分类底座只接受带文献来源、审核状态和可固定哈希的严格本地模型；除已审核的 K2O-SiO2 资产外，不宣称支持其他未经复核的分类图。
- Zr/TiO2-Nb/Y 在 v0.6 只验证坐标计算能力，没有注册边界或分类图；取得可靠原始数值边界并再次专业复核前不会开放。
- 多任务结果以完整目录为单位提交；中途失败不会留下半套新输出，也不会破坏原有完整目录。
- 覆盖运行只替换带有效 GeoSkills 运行报告的旧结果目录；普通同名文件夹会被保护。
- `local_data/` 和 `outputs/` 已排除在 Git 之外；不要提交私人或未发表数据。

## 当前状态

GeoSkills v0.6.0 已于 2026-08-10 正式发布。该版本加入无水100%组成基准、K2O-SiO2 正式图解，以及未注册边界的 Zr/TiO2-Nb/Y 坐标计算测试底座；发布验收包含 231 项自动测试、Skill 结构验证、合成多任务工作流、可分享产物隐私扫描，以及 Ubuntu/Windows 上 Python 3.11 和 3.12 的持续集成测试。版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## 许可

代码以 [MIT License](LICENSE) 开源。
