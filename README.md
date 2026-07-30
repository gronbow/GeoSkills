# GeoSkills

GeoSkills 是一个面向地质学与地球化学研究的本地 Agent Skill。

公开的 v0.1.0 只提供球粒陨石标准化 REE 配分图。
`feature/spider-diagram-v0.2` 分支是已完成人工审核的 v0.2.0 发布候选版：保留 REE，并新增原始地幔或 N-MORB 标准化微量元素蛛网图。TAS、Harker 和其他图解仍不在本版本范围内。

## 当前可以做什么

- 读取 `.csv`、逗号或制表符分隔的 `.txt`、以及 `.xlsx`；
- 识别常见的“每行一个样品”表格；
- 在结构明确时，自动转换论文补充材料常见的“样品在列、元素在行”表格；
- 检查样品编号、ppm 单位、缺失值、低于检出限、非数字、零和负数；
- 使用 Sun & McDonough（1989）C1 球粒陨石值标准化 La–Lu；
- 使用 Sun & McDonough（1989）原始地幔、脚注明确修改的原始地幔或 N-MORB 值生成微量元素蛛网图；
- 对明确标为 wt% 的 `K2O`、`P2O5`、`TiO2` 作可追溯的元素 ppm 换算；
- 生成投稿尺寸的 REE 配分图或蛛网图，并输出 SVG、PDF、600 dpi TIFF、600 dpi PNG；
- 同步输出实际绘图数据 CSV 和机器可读的 JSON 运行报告；
- 可选择完整四边框，以及经过碰撞检查的图内图例；
- 全程在本地处理数据，绘图脚本不请求网络服务。

## 安装到 Codex

以下公开仓库的默认分支目前仍是经过审核的 v0.1.0 REE 版本；v0.2.0 蛛网图发布候选版通过功能分支和 Pull Request 接受合并检查：

```text
https://github.com/gronbow/GeoSkills
```

也可以手动把 `skills/geoskills` 文件夹复制到个人 Skill 目录：

```text
%USERPROFILE%\.agents\skills\geoskills
```

## Windows 快速开始

在 PowerShell 中进入项目目录，安装依赖：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

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

程序不会修改原始表格。重复使用同一输出名称时，只有显式加入 `--overwrite` 才会替换已有结果。

## 项目结构

```text
GeoSkills/
├── README.md
├── AGENTS.md
├── requirements-dev.txt
├── skills/
│   └── geoskills/
│       ├── SKILL.md
│       ├── agents/openai.yaml
│       ├── assets/normalization/
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
- 图形可以展示富集程度、斜率和平行性，但不能单独证明岩浆源区、部分熔融、分离结晶或构造环境。
- `local_data/` 和 `outputs/` 已排除在 Git 之外；不要提交私人或未发表数据。

## 当前状态

GeoSkills v0.1.0 是仅包含 REE 配分图的公开测试版。v0.2.0 蛛网图发布候选版已通过全部 41 项自动测试、真实数据测试、导出审计和人工图形复核；远端 CI 与 Pull Request 合并完成后再作为稳定版本发布。

## 许可

代码以 [MIT License](LICENSE) 开源。
