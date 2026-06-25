# Technical Roadmap

本文档记录 `wall` 的长期技术路线、当前优先级，以及未来研究方向。

---

# 项目定位

`wall` 的核心定位是：

> 面向 CS2 Demo 的信息重建与行为分析平台。

当前优先级：

1. 稳定 Demo 解析
2. 稳定数据集生成
3. 完善本地播放器
4. 构建信息重建能力

当前阶段不把“鉴挂”作为主要目标；它只是未来可能的应用方向之一。

---

# 核心理念

项目围绕一个核心问题展开：

> 在某个时刻，一个玩家理论上能够获得哪些信息？

长期目标不是简单播放回放，而是重建：

```text
世界状态
→ 可获得信息
→ 玩家决策
→ 玩家行为
```

短期产品主线仍然是：

```text
Demo
→ Dataset
→ Viewer
```

当前 viewer sidebar 已经从旧的 round overview / per-player 信息面板，切到：

```text
Players list
→ selection
→ Visibility Feed
```

也就是说，近期 viewer 的信息侧栏主线是围绕 precomputed visibility feed 做交互，而不是继续在 sidebar 里堆叠原始状态字段。

---

# CLI 方向

统一入口：

```powershell
wall demo\match.dem
wall outputs\match_xxx
wall demo\match.dem --renew
wall catalog <dataset_dir>
```

默认行为是：如有需要先解析，再直接打开 Viewer。

当前默认链路还包括：

```text
demo
→ parse / dataset build
→ visibility.parquet
→ Viewer
```

也就是说，`visibility.parquet` 已经属于核心 dataset artifact 阶段，而不是 viewer feature。

---

# 数据集理念

原始表不是最终目标。

长期路线：

```text
Raw Events
→ Semantic Events
→ Information State
→ Behavior Analysis
```

未来的数据集应逐步提供更高层的语义对象，而不仅仅是 CSV/Parquet 表。

---

# 空间与 Region

后续分析尽量使用 Region，而不是直接使用原始坐标。

推荐空间层级：

```text
Raw Coordinates
→ Nav Area
→ Place Name
→ Tactical Region
```

例如：

```text
(x, y, z)
→ Area 182
→ TopMid
→ Mid
```

推荐保留两层语义 Region：

* Level 1: 战术区域
  `Long / Short / Mid / A Site / B Site`
* Level 2: 细粒度位置
  `Pit / Blue Box / Long Corner / Default / Window`

Region System 是后续信息状态、决策分析、转点分析和行为建模的基础层。

---

# Information State

长期目标是重建玩家在时刻 `t` 理论上能够获得的信息上界。

核心组成：

* 视觉信息
  当前可见敌人、最近可见位置、投掷物和 C4 可见性
* 听觉信息
  枪声、脚步、投掷物声音、下包与拆包声音
* 公共信息
  击杀信息、雷包状态、回合阶段
* 空间信息
  当前区域、队友区域、已知控制区域

未来播放器应支持玩家信息面板，用于展示这些信息状态，而不是试图还原玩家真实想法。

建议面板优先展示：

* Visible Now
* Heard Recently
* Last Seen Enemies
* Known Enemy Regions
* Bomb Knowledge
* Utility Knowledge
* Team Knowledge

---

# 感知路线

## 声音

声音系统建议分三层：

```text
Event Layer
→ Propagation Layer
→ Perception Layer
```

第一版重点是“能否听到”，而不是真实声学模拟。

## 可见性

可见性系统仍以 Awpy 几何能力作为 geometry 模式基础，但普通 viewer 启动不再默认走这条路径。

当前应明确区分三种模式：

1. `precomputed`
   dataset 已有 `visibility.parquet`，viewer 直接消费 artifact
2. `unavailable`
   dataset 暂无 `visibility.parquet`，viewer 正常打开，但不展示可见性结果
3. `geometry`
   仅显式重建、debug 或 on-demand LOS 才初始化 `awpy.VisibilityChecker`

推荐分阶段推进：

1. `FOV Only`
   只考虑朝向和距离，用于 Viewer 原型和信息面板验证
2. `Geometry Visibility`
   引入 Line Of Sight 判断
3. `Effective Visibility`
   在几何可见基础上加入 FOV、烟、闪等视觉干扰
4. `Perception Layer`
   区分“理论可见”和“理论上容易注意到”

当前已落地的 viewer 消费方式：

* `info_events.py` 只读取 precomputed `visibility.parquet`
* viewer startup 会一次性 preload all-round visibility feed
* round 切换和 Players selection 只过滤已有 `InfoEvent`
* 不重新读取 parquet
* 不重新 build spotted events
* artifact 缺少 `observer_steamid / target_steamid` 时，当前 viewer 通过 display-name alias 做兼容过滤

## Map-Scoped Visibility Runtime

在进入 batch 之前，先要完成一层稳定的 map-scoped runtime，把单 dataset visibility reconstruction 从 viewer 数据流里独立出来。

目标：

```text
MatchDataset
→ Map-Scoped Visibility Context
→ RoundData
→ VisibilityResultSet
→ pair / summary writer
```

设计边界：

* 把单 dataset visibility export 从 viewer startup 主路径里拆出来
* 把 `VisibilityChecker` 初始化限制在 `geometry` 模式
* 普通 viewer 对已有 artifact 应只走 `precomputed` 模式
* 普通 viewer 对缺失 artifact 应只走 `unavailable` 模式
* 保持 FOV、敌我、存活、位置有效性和 observer/target tick 查询语义继续留在 domain
* 不引入 dataset discovery、batch grouping 或 persistent worker pool

当前状态：

* `visibility.parquet` 已作为默认 pair-level artifact 落盘
* viewer 已与默认 geometry cache 初始化解耦
* viewer sidebar 已基于 `InfoEvent` 展示 visibility spotted feed
* Players list selection 内部 key 已优先使用 Steam64
* 当前仍需长期补齐 artifact 导出的 `observer_steamid / target_steamid`
* 后续 batch 仍然需要单独命令和 map-grouped worker 设计

## Visibility Batch

当需要批量处理大量已解析数据集时，应单独提供 `wall visibility-batch`，而不是继续堆高单 demo 模式的并发。

目标路线：

```text
Discover Datasets
→ Group By Map
→ Persistent Worker Pool Per Map
→ One VisibilityChecker Init Per Worker
→ Many Dataset/Round Tasks Per Worker
```

设计边界：

* 按 `map_name` 分组，因 `VisibilityChecker` 是地图相关对象
* worker 生命周期应覆盖多个 dataset，而不是只覆盖一个 demo
* 默认跳过已存在输出，只有 `--renew` 时重算
* 单 demo CLI 保持简单，batch 作为独立命令维护

---

# 地图几何路线

原则：

```text
Awpy
负责地图几何

wall
负责语义和分析
```

当前推荐路线：

```text
Awpy Geometry
+ Awpy Nav Mesh
+ Awpy Place Names
+ wall Tactical Regions
```

`wall` 不重复维护地图几何数据，只维护少量语义层补充，例如 Region Alias 和 Tactical Region Mapping。

职责边界建议保持为：

* Awpy
  Radar 资源、World/Radar 坐标转换、Nav Mesh、Place Names、Visibility Geometry
* wall
  Dataset、Visibility Artifacts、Event Timeline、Information State、Viewer、Behavior Analysis

---

# 行为分析路线

行为分析应建立在信息重建之后。

核心研究链条：

```text
Information
→ Decision
→ Action
```

短期目标是解释行为，而不是评价行为。

潜在行为原语包括：

* Region Transition
* Holding
* Rotation
* Peek
* Utility Usage

## 决策点设计

后续不应把每个 `tick` 都视为决策点。

更重要的是：

```text
决策点应优先定义为空间情境中的战术选择点
而不是时间轴上的逐 tick 判断点
```

更合理的建模方式是：

```text
Behavior = Decision(PositionContext, InformationState, TimePhase)
```

其中：

* `PositionContext` 是主轴
* `InformationState` 是解释轴
* `TimePhase` 是修饰轴

问题应优先表达为：

```text
玩家在这个位置情境下
结合当时可获得的信息
选择了什么后续行动？
```

## 空间决策点

决策点优先从具有战术意义的空间情境中生成，例如：

* 进入关键区域
* 在某个位置停留、观察、架枪或等待
* 离开某个区域并改变路线或战术重心

也就是说，决策分析首先依赖：

```text
位置情境
+ 信息状态
+ 后续行动
```

## PositionContextEpisode

在实现层，推荐使用 `PositionContextEpisode` 作为基础分析单位。

它表示玩家在某个战术位置或区域中停留、进入或离开的一段时间，用于统一记录：

```text
玩家在哪里
停留了多久
看见了什么
听见了什么
队友和炸弹信息是什么
附近有什么烟、火、道具
随后做出了什么行动
```

episode 候选可优先从三类事件生成：

```text
Enter Region
Dwell Region
Exit Region
```

## 分析主链路

后续推荐主链路：

```text
PlayerTimeline
  -> RegionTimeline
  -> PositionContextEpisode
  -> FutureActionLabel
  -> DecisionContextMiner
  -> InformationStateExplainer
  -> EvidenceAggregator
```

需要区分三层概念：

```text
PositionContextEpisode
Decision Episode
Evidence Episode
```

各层含义：

* `PositionContextEpisode`
  玩家处于某个位置和信息状态中
* `Decision Episode`
  玩家在该位置情境下做出了有战术意义的选择
* `Evidence Episode`
  该选择后来表现出较强信息价值，可进入后续证据累计

最终判断应来自多个 episode 的累积，而不是单个“可疑瞬间”。

---

# 信息约束下的行为分析

长期关注的问题是：

```text
玩家获得的信息
→ 是否足以支持该行为
```

例如：

* 这次转点是否有信息支撑
* 这次架枪是否有信息支撑
* 行为能否由已有信息解释

---

# 机器学习路线

机器学习不是当前优先级。

当前阶段应先完成：

```text
稳定数据集
→ 语义时间线
→ Region / Sound / Visibility / Utility
→ Information State
→ PositionContextEpisode
→ 行为解释
```

在这些基础对象稳定之前，不急于训练模型。机器学习应作为后期辅助分析工具，而不是直接替代信息重建或行为解释。

未来主要用途：

* 发现相似位置情境下的常见行为分叉
* 判断某个后续行动在相似情境中是否罕见
* 聚类玩家在不同 Region / Information State 下的行为模式
* 为 episode-level 分析提供统计基线
* 辅助生成解释、报告和异常片段排序

推荐顺序：

```text
规则系统
→ 统计特征
→ 相似情境基线
→ 传统模型
→ 时序模型
→ 大模型辅助解释
```

当前原则：

```text
先重建信息
再解释行为
最后才考虑学习模型
```

机器学习的目标不是直接判断玩家是否可疑，而是帮助回答：

```text
在相似位置情境和信息状态下，
这个后续行动是否常见？
```

可考虑的模型类型：

* 传统模型
  Logistic Regression、Random Forest、XGBoost、LightGBM
* 时序模型
  HMM、Temporal CNN、Transformer
* 大模型
  主要用于解释、报告和结果总结，不负责底层行为推断

---

# 研究方向

未来可能探索：

* FPS 环境中的信息重建
* 信息可获得性建模
* 部分可观测环境下的决策行为
* 信息约束下的行为分析
* Hidden-State Alignment

---

# 推荐开发顺序

当前推荐路线：

1. Player / Bomb / Viewer decoupling 收尾
2. Visibility artifact 补齐 `observer_steamid / target_steamid`
3. Region System
4. UtilityTimeline：烟、闪、火、雷的有效窗口
5. SoundExposure：谁在何时能听到什么
6. Viewer 继续消费 precomputed visibility / unavailable fallback
7. Visibility Batch：按地图分组复用 checker
8. Player Information Panel：展示 visible / heard / bomb / utility
9. InformationState 表落盘
10. PositionContextEpisode
11. Behavior primitives
12. Action explanation / evidence aggregation
13. Statistics / ML

---

# Related Docs

* `docs/architecture.md`
* `docs/viewer-decoupling-checklist.md`
* `docs/sound-feed-governance.md`
