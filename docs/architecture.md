# Architecture

这份文档描述 `wall` 当前的正式架构边界，以及各层之间应该如何协作。

## Overview

当前主链路已经不再只是一条 Viewer 中心路径，而是几条可以顺序执行的并行 pipeline：

```text
demo file
  -> parse / dataset build
  -> dataset boundary
  -> visibility artifact / reconstruction
  -> viewer orchestration
  -> analysis
```

项目当前阶段的重点不是“外挂判定”，而是把：

1. demo 解析做稳定
2. dataset 结构做统一
3. viewer 做成可维护的正式播放器

## Layer Model

### 1. CLI layer

入口：

- `src/wall/cli.py`
- `src/wall/viewer/cli.py`

职责：

- 解析命令行参数
- 判断输入是 demo 还是 dataset
- 串起 parse、默认 visibility artifact 生成和 viewer 启动流程
- 检查和初始化运行所需的 Awpy 地图资产

边界：

- 不保存长期状态
- 不承载 gameplay 语义判断
- 不直接做渲染细节

### 2. IO layer

目录：

- `src/wall/io/`

职责：

- 调用 demo parser
- 清洗并输出标准 dataset
- 维护表读写和 catalog 能力
- 对高频逐 tick 轨迹做压缩 artifact 生成

边界：

- 面向原始表和落盘格式
- 不承担 viewer UI 逻辑
- 只做必要的数据整理，不做播放器特化绘制

当前投掷物轨迹约定：

- parse 过程中可以短暂保留 parser 返回的 raw grenade trajectory DataFrame
- 这份 raw trajectory 主要用于生成 `grenade_trajectory_segments.parquet`，以及辅助构建 grenade bounce sound events
- 正式 dataset artifact 不再默认写出旧的 `grenades.parquet`
- viewer 不再依赖 raw grenade trajectory artifact

### 3. Domain layer

目录：

- `src/wall/domain/`

职责：

- 把原始表转成可查询的语义对象
- 提供 timeline / state 查询接口
- 封装 gameplay 规则和展示前的语义归纳

当前重点对象包括：

- `RoundPlayers`
- `PlayerTimeline`
- `BombTimeline`
- `UtilityTimeline`
- `SoundTimeline`
- `VisibilityTimeline`

边界：

- 负责“发生了什么”
- 不负责“画成什么样”

当前可见性相关语义也放在 domain 层：

- `VisibilityTimeline` 负责 observer/target 在某个 tick 的可见性查询
- FOV、敌我、存活、位置有效性等过滤在这一层完成
- LOS 调用语义在这一层被消费，但地图级 `VisibilityChecker` 初始化不再由这一层负责
- viewer、visibility reconstruction 和 export 都应消费 domain 结果，而不是各自重复做可见性判断

### 4. Visibility layer

目录：

- `src/wall/visibility/`

职责：

- 提供独立于 viewer 的可见性重建 pipeline
- 定义中立 dataset 输入边界，例如 `MatchDataset`
- 负责单 dataset 可见性导出 orchestration
- 统一 `VisibilityResultSet` 构造以及 interval / summary / optional raw-pair writer 协调
- 管理 `precomputed / unavailable / geometry` 三种可见性上下文模式

边界：

- 负责“如何重建并导出可见性结果”
- 不复制 FOV、敌我、存活、位置有效性等 gameplay 过滤
- 不把 `LoadedViewerData` 作为长期公开依赖

当前模式边界应保持为：

- `precomputed`
  - dataset 已有 `visibility.parquet`
  - viewer 和后续消费者优先读取已落盘 artifact
  - 不创建 `awpy.VisibilityChecker`
  - 不访问 `.awpy-assets/tris/*.tri`
- `unavailable`
  - dataset 暂无 `visibility.parquet`
  - viewer 仍可打开
  - visibility layer 标记为 unavailable
  - 不创建 `awpy.VisibilityChecker`
- `geometry`
  - 仅显式 visibility reconstruction / debug / on-demand LOS 路径使用
  - 允许初始化 `awpy.VisibilityChecker`
  - 允许构建 geometry cache

### 5. Viewer layer

目录：

- `src/wall/viewer/`

职责：

- 播放控制
- 回合切换
- 缓存当前帧
- 把 domain 查询结果组织成一帧画面
- 在主事件循环启动后分阶段加载 dataset 和首回合

当前拆分如下：

- `shell.py`
  - 主事件循环
  - staged startup / loading screen
  - 播放状态推进
  - sidebar / timeline 交互
  - Players 选中状态和 visibility feed 过滤协调
- `loading.py`
  - viewer 后台 dataset loading 协调
- `runtime.py`
  - round 切换
  - frame cache 生命周期
- `session.py`
  - round-scoped viewer data / HUD session helpers
- `state.py`
  - 播放状态和下拉状态
- `layout.py`
  - 下拉面板等布局计算
- `ui.py`
  - sidebar / bottom bar / 图标等 UI 绘制辅助
- `info_events.py`
  - 从 interval `visibility.parquet` 读取可见性区间
  - 校验 schema，旧 tick-level pair artifact 直接报错并提示重新生成
  - 从 VISIBLE intervals 构建 visibility spotted events
  - 提供按 tick / player filter 的 feed 辅助函数
- `renderer.py`
  - 一帧渲染总协调器
- `render_player.py`
  - 玩家相关纯绘制
- `player_palette.py`
  - 玩家 marker 数字颜色和 sidebar check mark 共享色板
- `render_sound.py`
  - 声音圈和标签绘制
- `render_bomb.py`
  - C4 / 下包 / 拆包绘制
- `render_utility.py`
  - 烟 / 火 / 闪 / HE 等投掷物效果绘制
- `render_config.py`
  - viewer 内部渲染常量
- `geometry.py`
  - 纯几何辅助函数
- `config.py`
  - viewer 启动和 UI 配置常量

边界：

- 负责“如何展示”
- `shell.py` 不应直接知道 `visibility.parquet` 路径、schema 或 pair-local 状态机细节
- `shell.py` 不处理旧 visibility schema 兼容逻辑
- `ui.py` 只接收已组织好的 lines / entries / state，不直接读取 parquet 或构建事件
- `info_events.py` 不 import `pygame`
- 不应该复制 domain 已经表达过的 gameplay 规则

### 6. Render support layer

目录：

- `src/wall/render/`

职责：

- 地图底图
- pygame 相关底层渲染能力
- viewer 会复用的一些视觉支持逻辑

边界：

- 提供底层绘制基础设施
- 不应重新成为新的“总控 app.py”

### 7. Asset support layer

目录：

- `src/wall/assets.py`
- `src/wall/paths.py`

职责：

- 统一 `wall` 本地 Awpy 资产目录
- 检查 `maps / navs / tris` 是否存在
- 在交互式 CLI 中询问是否下载缺失资产
- 为 viewer 和后续 visibility / nav 分析提供稳定路径

边界：

- 只负责本地资产发现与下载
- 不承载 gameplay 语义
- 不把第三方地图资产提交进仓库

## Runtime Flow

这些 pipeline 可以独立存在，也可以按顺序执行。常见顺序例如：

正常播放链路：

```text
wall <demo-or-dataset>
  -> wall.cli
  -> wall.viewer.cli
  -> viewer.shell.PygameRoundViewer
  -> DatasetIndex startup load
  -> viewer.runtime.RoundRuntime
  -> viewer.renderer.PygameRoundRenderer
  -> render helpers
```

如果输入是 demo：

```text
demo
  -> io parse
  -> outputs/<match_dataset>
  -> visibility.parquet (default interval artifact)
  -> viewer load dataset
```

如果输入已经是 dataset：

```text
dataset dir
  -> generate visibility.parquet if missing unless opted out
  -> cli checks required awpy assets
  -> viewer load directly
```

## Data Flow

当前推荐的数据流方向是：

```text
raw tables
  -> domain semantic objects
  -> pipeline-specific assembly
  -> viewer or analysis consumer
```

viewer 路径：

```text
dataset
  -> DatasetIndex
  -> round-scoped RoundData build
  -> all-round visibility info-event preload
  -> RoundData semantic viewer input
  -> renderer
```

viewer 投掷物轨迹路径：

```text
demo.parse_grenades() raw trajectory
  -> grenade_trajectory_segments.parquet
  -> DatasetIndex / MatchDataset
  -> RoundData.utility_timeline
  -> renderer grenade animation
```

viewer sidebar feed 路径：

```text
dataset
  -> visibility.parquet
  -> viewer.info_events.load_info_events_for_dataset(...)
  -> list[InfoEvent]
  -> shell selection / current_tick filter
  -> ui lines / scroll state
```

visibility reconstruction 路径：

```text
dataset
  -> MatchDataset
  -> MapVisibilityContext(mode=geometry)
  -> RoundData
  -> VisibilityTimeline
  -> VisibilityResultSet
  -> interval / summary / optional raw-pair writer
```

analysis 路径：

```text
dataset
  -> MatchDataset
  -> semantic/domain objects
  -> analysis-specific tables or episodes
```

viewer 当前应优先消费：

- `round_players`
- `bomb_timeline`
- `utility_timeline`
- `sound_timeline`
- `visibility_timeline`
- `frame_ticks`
- `round_start_tick`

而不是重新在 viewer 内部直接过滤原始表。

其中投掷物轨迹的正式 viewer 输入应为：

- `grenade_trajectory_segments.parquet`
- `UtilityTimeline` 基于 segment 做 tick 内插值
- viewer 不再回退到旧的 raw grenade trajectory artifact

但 sidebar 的 visibility feed 例外地直接消费 precomputed artifact：

- feed 数据来自 `visibility.parquet`
- `visibility.parquet` 的正式 schema 是 interval state table
- viewer 只支持新版 interval schema；旧 tick-level pair schema 应提示重新运行 `wall visibility <dataset_dir>`
- viewer 启动时一次性 preload all-round `InfoEvent`
- round 切换和 player selection 只过滤已加载事件
- 不重新读取 parquet
- 不重新 build spotted events

普通 viewer 打开 dataset 时：

- 若存在 `visibility.parquet`，应走 `MapVisibilityContext(mode=precomputed)`
- 若不存在 `visibility.parquet`，应走 `MapVisibilityContext(mode=unavailable)`
- 不应在默认启动路径里初始化 `awpy.VisibilityChecker` 或 geometry cache

## Assets Layout

当前资源按用途整理为：

```text
assets/
  effects/
    explosions/he/
    fire/
    flash/
    muzzle/
    smoke/
  icons/
    equipment/
  ui/
    icons/
```

第三方 Awpy 地图资产按运行时缓存整理为：

```text
.awpy-assets/
  maps/
  navs/
  tris/
```

原则：

- 特效纹理放 `effects/`
- 武器/装备 icon 放 `icons/equipment/`
- UI 控件 icon 放 `ui/icons/`
- Awpy 第三方地图资产放 `.awpy-assets/`
- `.awpy-assets/` 只作本地运行缓存，不提交进 git

## Architectural Rules

### Rule 1: parse produces stable data

parse 层负责把 demo 变成稳定 dataset，不把 viewer 的临时展示需求塞回原始表结构里。

### Rule 2: domain owns gameplay meaning

如果是“脚步声该不该合并”“投掷物碰撞声音怎么抑制”“bomb 当前是什么语义状态”这类问题，优先放在 domain。

### Rule 3: viewer owns presentation

如果只是：

- alpha
- 线宽
- 圈大小
- label 偏移
- 动画帧选择

这类纯表现问题，应留在 viewer。

### Rule 4: renderer should coordinate, not interpret everything

`viewer/renderer.py` 可以做总协调，但不应继续膨胀成旧版 `app.py` 那种“同时懂数据、懂规则、懂 UI、懂绘制”的混合体。

### Rule 5: prefer semantic expansion over raw-table reach-through

新功能如果需要更多信息，优先：

1. 扩展 domain timeline/query
2. 扩展 `RoundData`
3. 最后才让 viewer 使用

不要默认在 viewer 里直接重新查表。

### Rule 6: visibility logic stays unified

可见性判断应尽量只存在一条正式路径：

1. `RoundData`
2. `VisibilityTimeline`
3. `VisibilityResultSet`
4. `interval / summary / optional raw-pair` writer
   其中 canonical artifact 为 interval `visibility.parquet`，raw pair 只作为 debug optional output

不要让：

- viewer
- summary 导出
- interval 导出
- raw pair 导出
- 后续分析脚本

各自复制一套 FOV/LOS 判定逻辑。

补充：

- geometry-based LOS 重建不是 viewer 默认启动职责
- `visibility.parquet` 是 parse 之后的核心 dataset artifact
- `visibility.parquet` 默认表示 interval state table，而不是 tick-level pair dense table
- viewer 只消费 precomputed 或 unavailable 状态，不主动触发 geometry reconstruction

### Rule 7: third-party map assets stay local and explicit

Awpy 的 `maps / navs / tris` 视为运行时外部资产：

1. 默认缓存在仓库根目录 `.awpy-assets/`
2. 由 CLI 检测是否缺失
3. 由 `wall assets` 或 viewer 启动前的交互式确认触发下载

不要把这些第三方地图资产混进 `src/`、`assets/` 或 git 历史。

## Current Status

当前已完成的主要收敛：

- `viewer/app.py` 已退役
- viewer 已拆成 shell / runtime / renderer / render helpers
- viewer 启动主路径已切到 `DatasetIndex -> round-scoped RoundData`
- viewer 已采用 staged/background loading，窗口会先启动再做重数据加载
- sound / bomb / utility / player 语义已基本从 viewer 主路径抽离
- visibility reconstruction 已独立到 `src/wall/visibility/`，并保持统一的 `VisibilityResultSet -> writer` 路径
- 普通 viewer 已与默认 `awpy.VisibilityChecker` / geometry cache 初始化解耦
- `visibility.parquet` 已成为 parse 后默认生成的 canonical interval visibility artifact
- `grenade_trajectory_segments.parquet` 已成为正式投掷物轨迹 artifact
- viewer 投掷物动画已切到 segment artifact，不再消费旧 `grenades.parquet`
- parse 输出已停止写出旧的 `grenades.parquet/csv`，仅在 parse 进程内短暂保留 raw trajectory 供压缩和声音事件构建使用
- viewer sidebar 已切到 visibility event feed，不再显示旧的 round overview / per-player info 面板
- visibility event feed 已收口到 `viewer/info_events.py`，并只消费 interval visibility schema
- Players 列表已支持按内部稳定 key 选中，并以 alias fallback 兼容缺少 steamid 的 visibility artifact
- feed scroll 默认 stick-to-latest，只有用户手动滚动离开底部时才停止自动跟随
- assets 已按 effects / equipment / ui 分类
- viewer 当前主路径已主要消费 semantic objects，而不是长串原始表参数

## Remaining Cleanup Direction

后续清理仍然建议沿这几个方向继续：

1. 补少量纯 helper 单测
2. 继续压缩 `renderer.py` 的协调复杂度
3. 继续把 visibility artifact 导出补齐 `observer_steamid / target_steamid`
4. 保持新功能先扩 domain，再进 viewer
5. 保持 `docs/` 中的架构文档、roadmap、checklist 同步

## Related Docs

- `docs/technical-roadmap.md`
- `docs/viewer-decoupling-checklist.md`
