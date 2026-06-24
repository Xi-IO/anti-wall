# wall

`wall` 是一个本地 Counter-Strike 2 demo 解析与播放工具。

它可以把 `.dem` 文件解析成结构化表格，在 pygame 2D viewer 中播放，并支持预计算可见性分析，用于复盘游戏中的信息流。

## 功能

* 使用 `demoparser2` 解析 CS2 `.dem` 文件
* 将回合、tick、事件表导出为 parquet
* 打开本地 pygame demo viewer
* 显示玩家、武器、死亡、开火、投掷物、烟雾和时间轴
* 基于 FOV + 地图几何 LOS 生成可见性表
* 显示 visibility feed：谁在什么时候看见了谁
* 支持按选中玩家过滤 visibility feed
* 本地优先，不依赖云端上传

## 安装

推荐使用 Python 3.11。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .[dev]
```

也可以在已有 conda 环境中安装：

```powershell
conda activate wall
pip install -e .[dev]
```

## 快速开始

直接打开 demo：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem
```

如果对应的解析数据集已经存在，`wall` 会直接复用。  
强制重新生成：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem --renew
```

打开已有数据集：

```powershell
wall outputs\match730_003825715054175584453_1941916173_129
```

## 可见性分析

生成 visibility 数据：

```powershell
wall visibility outputs\match730_003825715054175584453_1941916173_129
```

默认行为：

* 输出类型：`pair`
* tick step：`8`
* 格式：`parquet`
* 所有回合合并为一张表
* 跳过 freeze time
* jobs：`4`

viewer 会消费已经预计算好的 `visibility.parquet`。  
普通 viewer 启动时不会现场构建 Awpy geometry。

## 地图资产

viewer 地图资产默认缓存到：

```text
.awpy-assets/
```

准备 viewer 所需资产：

```powershell
wall assets init --feature viewer --yes
```

准备 analysis 所需资产：

```powershell
wall assets init --feature analysis --yes
```

检查资产状态：

```powershell
wall assets check --feature analysis
```

## 常用命令

```powershell
wall --help
wall assets check --feature viewer
wall assets init --feature viewer --yes
wall catalog outputs\match730_003825715054175584453_1941916173_129
wall visibility outputs\match730_003825715054175584453_1941916173_129
```

## 文档

更详细的设计说明放在 `docs/`：

* `docs/technical-roadmap.md`
* `docs/architecture.md`
* `docs/readme-details.md`

`docs/readme-details.md` 里保留了更细的 CLI、dataset、viewer 和 visibility 补充说明。

## 状态

这是一个仍在快速迭代的工程 / 研究项目。当前重点是 demo 播放、可见性分析和信息流复盘。
