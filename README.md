# GeoSkills

GeoSkills 是一个面向地质学与地球化学研究的本地 Agent Skill。

当前正式版本为 [v0.3.0](https://github.com/gronbow/GeoSkills/releases/tag/v0.3.0)，包含球粒陨石标准化 REE 配分图、微量元素蛛网图、Harker 变化图，以及带适用性保护的火山岩 TAS 分类图。

## 当前可以做什么

- 读取 `.csv`、逗号或制表符分隔的 `.txt`、以及 `.xlsx`；
- 识别常见的“每行一个样品”表格；
- 在结构明确时，自动转换论文补充材料常见的“样品在列、元素在行”表格；
- 检查样品编号、ppm 单位、缺失值、低于检出限、非数字、零和负数；
- 使用 Sun & McDonough（1989）C1 球粒陨石值标准化 La–Lu；
- 使用 Sun & McDonough（1989）原始地幔、脚注明确修改的原始地幔或 N-MORB 值生成微量元素蛛网图；
- 对明确标为 wt% 的 `K2O`、`P2O5`、`TiO2` 作可追溯的元素 ppm 换算；
- 以 SiO2 或用户指定变量为横轴，一次生成一幅或多幅 Harker 变化图；
- 使用 SiO2 与 Na2O + K2O 绘制火山岩 TAS 图，并输出逐样品分类与边界复核状态；
- 生成投稿尺寸的 REE、蛛网图、Harker 或 TAS 图件，并输出 SVG、PDF、600 dpi TIFF、600 dpi PNG；
- 同步输出实际绘图数据 CSV 和机器可读的 JSON 运行报告；
- 可选择完整四边框，以及经过碰撞检查的图内图例；
- 全程在本地处理数据，绘图脚本不请求网络服务。

## 安装到 Codex

公开仓库的默认分支 `main` 包含经过审核和自动测试的正式 v0.3.0：

```text
https://github.com/gronbow/GeoSkills
```

也可以手动把 `skills/geoskills` 文件夹复制到 Codex 的个人 Skill 目录：

```text
%USERPROFILE%\.codex\skills\geoskills
```

如果设置了 `CODEX_HOME`，则复制到 `%CODEX_HOME%\skills\geoskills`。复制完成后，重新开启一个 Codex 任务即可使用。

## Windows 快速开始

需要 Python 3.11 或 3.12。先运行 `python --version` 确认版本，然后在 PowerShell 中进入项目目录并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

如果系统只提供 Python Launcher，可以把第一条命令改为 `py -3.12 -m venv .venv`。

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
└── tests/
```

## 科学与隐私边界

- 直接元素浓度必须明确为 ppm；只有 `K2O`、`P2O5`、`TiO2` 可在明确为 wt% 时换算。
- 缺失值和低于检出限状态保留为曲线断点；零和负数会阻止对数坐标绘图。
- 标准化表包含文献、DOI、表格位置、版本和核对记录。
- 原始地幔表保留文献 Table 1 的 Cs、Pb 数值，并明确提示原文脚注中的 modified 版本；程序不会静默混用。
- Harker 图只展示变量间的协变关系；默认不添加拟合线，也不从相关性单独推断岩浆过程。
- TAS 边界使用带文献与版本信息的本地资产。恰好位于边界上的样品标为 `review_required`，不会静默选择一侧。
- TAS 仅用于明确确认的火山岩；`as-reported` 结果标为初步分类，不能替代无水归一化后的专业判断。
- 图形可以展示富集程度、斜率和平行性，但不能单独证明岩浆源区、部分熔融、分离结晶或构造环境。
- `local_data/` 和 `outputs/` 已排除在 Git 之外；不要提交私人或未发表数据。

## 当前状态

GeoSkills v0.3.0 是当前正式版本。它整合了 v0.1.0 的 REE 工作流、经过审核的微量元素蛛网图，以及新增的 Harker 和火山岩 TAS 工作流。完整版本通过了 69 项自动测试、已发表数据的 Harker 验证、合成火山岩 TAS 验证、导出审计、人工图面复核，以及 Ubuntu/Windows 上 Python 3.11/3.12 的 GitHub Actions 检查。版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## 许可

代码以 [MIT License](LICENSE) 开源。
