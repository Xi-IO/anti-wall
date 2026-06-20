# wall

`wall` 当前定位为一个面向 Counter-Strike 2 的 demo 解析与播放工具。

目前项目已经完成这几件核心工作：

- 用 `demoparser2` 解析 `.dem` 文件
- 导出 `ticks`、`player_death`、推断回合表
- 从 demo header 中提取地图等基础信息并落盘
- 使用 Awpy 官方地图数据作为回合渲染背景
- 提供本地 pygame GUI 播放器
- 提供统一 CLI：`wall <demo或数据集目录>` 和 `wall catalog`

## 当前目录

当前正式实现位于：

- [`src/wall/`](./src/wall)
  - `cli.py`：统一命令入口
  - `io/`：解析、表读写、DuckDB catalog
  - `render/`：渲染逻辑与 pygame 效果
  - `viewer/`：pygame 播放器

兼容策略、技术路线和后续改造方向单独整理在：

- [`docs/technical-roadmap.md`](./docs/technical-roadmap.md)

示例 demo 位于：

- [`demo/`](./demo)

## 环境配置

项目本身不要求 `conda`。  
只要你使用的是 `Python 3.11`，推荐直接在普通虚拟环境里安装：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .[dev]
```

如果你平时使用 `conda`，也可以在任意 `Python 3.11` 的 conda 环境里执行同样的安装命令：

```powershell
pip install -e .[dev]
```

安装完成后可以直接使用：

```powershell
wall --help
```

### 4. 安装 Awpy 地图数据

第一次使用地图背景前，需要拉取 Awpy 官方地图资源：

```powershell
awpy get maps
```

当前项目已经验证可用的地图背景来自：

- `C:\Users\26759\.awpy\maps\`

## CLI

主入口是：

```powershell
wall --help
```

当前日常使用只需要一个入口：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem
```

行为规则：

- 传 `.dem` 文件：
  - 如果对应数据集目录不存在，就先解析
  - 如果对应数据集目录已经存在，就直接用现有数据集打开
- 传 `outputs\xxx` 这种数据集目录：
  - 直接打开 viewer
- 如果想强制更新中间数据：
  - 使用 `--renew`

例如：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem --renew
wall outputs\match730_003825715054175584453_1941916173_129
```

保留的显式辅助命令只有：

- `wall catalog <dataset_dir>`：为数据集构建 DuckDB catalog

## 解析 demo

解析脚本会：

- 读取 demo header
- 解析 `player_death`
- 解析 tick 级玩家状态
- 根据“多人同步位置跳变”推断回合边界
- 生成元数据文件

如果你只是想“打开并看 demo”，优先直接使用：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem
```

底层行为仍然是“解析 demo -> 生成数据集目录 -> 打开 viewer”。

如果你只是想单独触发解析并更新中间数据，也可以直接用：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem --renew
```

默认会优先把所有表写成 `parquet`；如果你确实需要旧格式，也可以显式指定：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem --renew --table-format csv
```

默认输出到：

- [`outputs/`](./outputs)

以当前示例 demo 为例，生成目录是：

- [`outputs/match730_003825715054175584453_1941916173_129/`](./outputs/match730_003825715054175584453_1941916173_129)

其中包含：

- [`ticks.parquet`](./outputs/match730_003825715054175584453_1941916173_129/ticks.parquet)
- [`player_death.parquet`](./outputs/match730_003825715054175584453_1941916173_129/player_death.parquet)
- [`inferred_rounds.parquet`](./outputs/match730_003825715054175584453_1941916173_129/inferred_rounds.parquet)
- [`metadata.json`](./outputs/match730_003825715054175584453_1941916173_129/metadata.json)

读取端会自动优先读 `parquet`，不存在时再回退到 `csv`，所以旧输出目录仍然兼容。

### metadata.json 当前包含的信息

- demo 文件名、路径、大小
- `demoparser2.parse_header()` 返回的 header
- 地图名、服务端名、patch 版本等派生信息
- `ticks` / `player_death` / `inferred_rounds` 的表结构摘要
- 回合推断参数
- 推断回合 id 与起始 tick
- 玩家名单

当前示例 demo 已确认：

- `map_name = de_dust2`

## GUI 播放器

启动本地 pygame GUI：

```powershell
wall outputs\match730_003825715054175584453_1941916173_129
```

指定初始回合：

```powershell
wall outputs\match730_003825715054175584453_1941916173_129 --round 1
```

当前 viewer 支持：

- 选择推断回合
- 播放 / 暂停
- 拖动时间帧
- 选择播放倍速
- 地图内显示固定 HUD 编号和玩家 ID
- 掉血闪红、死亡叉、枪口火光和 tracer
- 基于 Awpy 地图底图显示玩家移动

## DuckDB

解析后的表可以注册进一个本地 DuckDB catalog：

```powershell
wall catalog outputs\match730_003825715054175584453_1941916173_129
```

默认会生成：

- [`tables.duckdb`](./outputs/match730_003825715054175584453_1941916173_129/tables.duckdb)

库里会创建 `wall` schema，并把每张表注册成同名 view，例如：

- `wall.ticks`
- `wall.player_death`
- `wall.grenades`
- `wall.inferred_rounds`

同时还会生成一张注册表：

- `wall.table_registry`

按当前配置，`duckdb` 会随项目依赖一起安装，不需要再单独补装。

## 回合推断逻辑

当前不直接依赖 demo 原始回合号做主分段，而是使用全局位置跳变推断回合边界：

- 对每个玩家计算相邻 tick 的 XY 位移
- 对每个 tick 统计发生“大跳变”的玩家数量
- 当同一 tick 内跳变玩家数超过阈值时，将其视为候选回合边界
- 再用 `min_gap_ticks` 去除过密候选点

当前默认参数：

- `jump_threshold = 800`
- `min_jump_players = 6`
- `min_gap_ticks = 1000`

这套规则主要是为了切掉：

- 热身结束
- 回合重置
- 出生点切换
- freeze/live 之间的大跳变

## 更多设计说明

关于这些内容的详细设计说明，见：

- [`docs/technical-roadmap.md`](./docs/technical-roadmap.md)
  - 兼容策略
  - 包结构与 CLI 路线
  - dataset / parquet / DuckDB 路线
  - 声音可视化与玩家信息面板
  - 可见性计算分阶段方案
  - 小模型 / 大模型的使用建议
