# GeoSKILLS

GeoSKILLS 是一个面向地质学与地球化学工作的开放 Agent Skills 项目。

第一个 Skill 是 `plot-ree-patterns`：读取地球化学表格，检查稀土元素数据，并生成球粒陨石标准化 REE 配分图。

## 当前进度

项目目前处于“标准化计算完成”阶段：

- 已创建独立项目目录；
- 已创建第一个 Skill 的标准目录；
- 已启用 Git 本地版本记录；
- 已加入环境检查程序；
- 已声明运行和测试所需的 Python 组件；
- 已加入第一个自动测试；
- 已加入只读数据检查器，可检查 CSV、TXT 和 Excel；
- 已加入完全虚构的 REE 示例数据；
- 已加入 Sun & McDonough（1989）C1 球粒陨石标准化值和来源记录；
- 已加入标准化计算程序；
- 尚未加入绘图程序；
- 尚未上传 GitHub。

在通过数值测试和科学复核前，不把该项目描述为可用于正式科研分析的稳定版本。

## 文件夹说明

```text
GeoSKILLS/
├── README.md                         项目说明，主要给人阅读
├── AGENTS.md                         告诉不同 AI 如何安全地协作开发
└── skills/
    └── plot-ree-patterns/
        ├── SKILL.md                  告诉智能体何时、如何使用这个 Skill
        ├── agents/openai.yaml        可选的 Codex/OpenAI 界面信息，不影响核心功能
        ├── scripts/                  可重复执行的 Python 程序
        ├── references/               数据规则和科学方法说明
        ├── examples/                 可公开使用的合成示例数据
        └── assets/                   带来源和版本信息的标准化值
```

## 初学者词汇

- **项目（project）**：为完成同一个目标而组织在一起的一组文件。
- **代码（code）**：写给计算机执行的明确步骤。
- **脚本（script）**：通常可以直接运行的小程序。
- **Git**：记录文件每次变化的版本管理工具，类似可恢复历史版本的实验记录本。
- **GitHub**：存放和分享 Git 项目的网络平台。Git 可以离线使用，GitHub 需要联网。
- **测试（test）**：用已知输入检查程序是否得到预期结果。
- **断言（assertion）**：测试中必须成立的条件；条件不成立时，测试失败。
- **虚拟环境（virtual environment）**：只属于当前项目的独立 Python 工具箱，避免不同项目的组件互相影响。
- **JSON**：一种结构清楚、既方便人读也方便程序读的文本报告格式。
- **退出码（exit code）**：程序结束时给系统的简短信号；本项目用 0 表示通过、1 表示错误、2 表示需要人工确认。

## 运行第一个真实功能

在 PowerShell 中进入项目目录后运行：

```powershell
.\.venv\Scripts\python.exe skills\plot-ree-patterns\scripts\inspect_data.py skills\plot-ree-patterns\examples\synthetic_ree_data.csv
```

程序只读取表格，并在屏幕上输出 JSON 检查报告。

通过检查后，可以生成一个新的标准化结果文件：

```powershell
.\.venv\Scripts\python.exe skills\plot-ree-patterns\scripts\normalize_ree.py skills\plot-ree-patterns\examples\synthetic_ree_data.csv --output outputs\synthetic_ree_normalized.csv
```

原始表格不会被修改。标准化结果是无量纲比值；程序目前仍不会绘图。

## 开发原则

1. 先保证科学数值正确，再改善外观。
2. 标准化值和分类边界必须有明确来源和版本。
3. 不提交用户的未发表数据或本地 GEOROC 下载文件。
4. 每增加一个功能，同时增加成功和失败测试。
5. 核心脚本不依赖某一家大模型或云端 API。
