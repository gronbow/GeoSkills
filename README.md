# GeoSkills

GeoSkills 是一个面向地质学与地球化学研究的本地 Agent Skill。

**v1 只做一件事：生成球粒陨石标准化的稀土元素（REE）配分图。**
蛛网图、TAS、Harker 图和其他地球化学图解不属于第一个版本。

## v1 可以做什么

- 读取 `.csv`、逗号或制表符分隔的 `.txt`、以及 `.xlsx`；
- 识别常见的“每行一个样品”表格；
- 在结构明确时，自动转换论文补充材料常见的“样品在列、元素在行”表格；
- 检查样品编号、ppm 单位、缺失值、低于检出限、非数字、零和负数；
- 使用 Sun & McDonough（1989）C1 球粒陨石值标准化 La–Lu；
- 生成投稿尺寸的 REE 配分图，并输出 SVG、PDF、600 dpi TIFF、600 dpi PNG；
- 同步输出实际绘图数据 CSV 和机器可读的 JSON 运行报告；
- 可选择完整四边框，以及经过碰撞检查的图内图例；
- 全程在本地处理数据，绘图脚本不请求网络服务。

## 安装到 Codex

可在 Codex 中让 `$skill-installer` 从以下仓库安装 `skills/geoskills`：

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

- 当前仅接受明确为 ppm 的 REE 浓度；不会静默换算 wt% 或 ppb。
- 缺失值保留为曲线断点；零和负数会阻止对数坐标绘图。
- 标准化表包含文献、DOI、表格位置、版本和核对记录。
- 图形可以展示富集程度、斜率和平行性，但不能单独证明岩浆源区、部分熔融、分离结晶或构造环境。
- `local_data/` 和 `outputs/` 已排除在 Git 之外；不要提交私人或未发表数据。

## 当前状态

GeoSkills v0.1.0 是仅包含 REE 配分图功能的公开测试版。当前版本已通过 23 项自动测试、真实论文数据端到端测试、投稿导出检查和 Git 历史隐私审计；正式投稿前仍应由研究者核对数据列、单位、标准化方案和最终图件。

## 许可

代码以 [MIT License](LICENSE) 开源。
