# wall

`wall` 当前定位为一个面向 Counter-Strike 2 的 demo 解析与播放工具。

目前项目已经完成这几件核心工作：

- 用 `demoparser2` 解析 `.dem` 文件
- 导出 `ticks`、`player_death`、推断回合表
- 从 demo header 中提取地图等基础信息并落盘
- 使用 Awpy 官方地图数据作为回合渲染背景
- 提供本地 pygame GUI 播放器
- 提供可见性导出：FOV + 地图几何 LOS
- 提供统一 CLI：`wall <demo或数据集目录>`、`wall catalog`、`wall assets`、`wall visibility`

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

如果你跟当前仓库里的测试和 viewer 工作流保持一致，推荐直接使用现有的 `wall` conda 环境：

```powershell
conda activate wall
pip install -e .[dev]
```

安装完成后可以直接使用：

```powershell
wall --help
```

### Awpy 地图资产

`wall` 运行时会使用 Awpy 官方地图资产，但不会再依赖 `C:\Users\...\ .awpy`。

当前约定：

- 资产默认缓存在仓库根目录的 [`.awpy-assets/`](./.awpy-assets)
- 按类型分成：
  - `maps/`
  - `navs/`
  - `tris/`
- 这些目录只用于本地运行，不应提交进 git

如果你想提前准备资产，可以显式执行：

```powershell
wall assets init --feature analysis --yes
```

如果你只需要 viewer 地图背景：

```powershell
wall assets init --feature viewer --yes
```

查看当前缺什么：

```powershell
wall assets check --feature analysis
```

如果已经有 dataset，也可以让 `wall` 从 `metadata.json` 里自动推断地图名：

```powershell
wall assets init --feature viewer --dataset outputs\match_xxx
```

另外，直接打开 viewer 时，`wall` 也会先检查当前地图需要的 `maps` 资产；如果缺失，会先做 `y/n` 询问，再下载。

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
- `wall assets check ...`：检查 Awpy 地图资产
- `wall assets init ...`：下载缺失的 Awpy 地图资产
- `wall visibility <dataset_dir>`：导出可见性表

## 可见性导出

当前 `wall visibility` 已支持按推断回合导出玩家可见性判断。

当前语义：

- 先做敌我、存活和位置有效性过滤
- 再做大约 `90°` 的 FOV 判断
- 对 FOV 内目标调用 Awpy `VisibilityChecker` 做地图几何 LOS 判断
- 输出 `pair` 或 `summary` 表

当前默认行为：

- 默认输出 `pair`
- 默认 `tick-step = 8`
- 默认格式优先 `parquet`
- 多回合默认合并成一张总表
- 默认跳过 freeze time
- 默认 `jobs = 4`，但实际 worker 数不会超过回合数

普通 viewer 当前只消费 dataset 中已经落盘的 `visibility.parquet`：

- 如果存在 `visibility.parquet`
  - viewer 会在启动时预加载 all-round visibility feed
  - sidebar 直接显示 spotted events
- 如果不存在 `visibility.parquet`
  - viewer 仍然可以正常打开
  - 只是 visibility feed 为空

普通 viewer 不会在启动时现场创建 Awpy `VisibilityChecker` 或重建 geometry visibility。

最常用命令：

```powershell
wall visibility outputs\match730_003825715054175584453_1941916173_129
```

默认会生成类似：

- `visibility_all_rounds_step_8_post_freeze.parquet`

如果要导出 `summary`：

```powershell
wall visibility outputs\match730_003825715054175584453_1941916173_129 --output-kind summary
```

如果要恢复“每回合一张表”：

```powershell
wall visibility outputs\match730_003825715054175584453_1941916173_129 --split-rounds
```

如果想看详细耗时：

```powershell
wall visibility outputs\match730_003825715054175584453_1941916173_129 --profile-visibility
```

当前 `pair` 输出保留字段：

- `tick`
- `round_id`
- `observer`
- `target`
- `distance`
- `relative_yaw_deg`
- `in_fov`
- `has_los`
- `is_visible`

当前 `summary` 输出按 `tick + observer` 聚合，包含：

- `pair_count`
- `fov_count`
- `visible_count`
- `fov_targets`
- `visible_targets`

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
- 右侧 `Players` 列表支持点击选中 / 取消选中玩家
- sidebar 下半部分显示 `Visibility Feed`
- 当未选中玩家时，feed 显示当前 tick 之前的全部 spotted events
- 当选中一个或多个玩家时，feed 只显示与这些玩家有关的事件
- info feed 默认自动跟随最新事件；只有手动把滚动条拉上去时才停止自动跟随

当前 visibility feed 文本格式类似：

```text
80.30s  playerA spotted playerB
```

`Players` 列表的内部选择 key 当前优先使用 Steam64；如果现有 `visibility.parquet` 里还没有 `observer_steamid / target_steamid`，viewer 会自动回退到 display name alias 做过滤匹配，因此 UI 里仍然只显示游戏内名字，不显示 Steam64。

如果当前地图的 `maps` 资产缺失，viewer 启动前会先提示是否下载。

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
