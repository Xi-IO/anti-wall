# wall

`wall` 是一个面向 Counter-Strike 2 demo 分析的研究型项目，当前目标是搭建一套用于“透视挂鉴别”的数据处理与可视化基础设施。

目前项目已经完成这几件核心工作：

- 用 `demoparser2` 解析 `.dem` 文件
- 导出 `ticks`、`player_death`、推断回合表
- 从 demo header 中提取地图等基础信息并落盘
- 使用 Awpy 官方地图数据作为回合渲染背景
- 提供命令行导图脚本和本地 GUI 播放器

## 当前目录

当前主要保留的脚本有：

- [`scripts/parse_demo_sample.py`](./scripts/parse_demo_sample.py)
  - 解析 demo
  - 推断回合边界
  - 导出结构化结果
- [`scripts/round_render.py`](./scripts/round_render.py)
  - 公共渲染逻辑
  - 负责地图背景、玩家点位、朝向扇形、死亡标记
- [`scripts/animate_round.py`](./scripts/animate_round.py)
  - 命令行导出单回合或多回合 `png/gif`
- [`scripts/round_gui.py`](./scripts/round_gui.py)
  - 本地 GUI 播放器

示例 demo 位于：

- [`demo/`](./demo)

## 环境配置

### 1. 创建环境

```powershell
conda env create -f environment.yml
```

### 2. 激活环境

```powershell
conda activate wall
```

### 3. 安装 Awpy 地图数据

第一次使用地图背景前，需要拉取 Awpy 官方地图资源：

```powershell
awpy get maps
```

当前项目已经验证可用的地图背景来自：

- `C:\Users\26759\.awpy\maps\`

## 解析 demo

解析脚本会：

- 读取 demo header
- 解析 `player_death`
- 解析 tick 级玩家状态
- 根据“多人同步位置跳变”推断回合边界
- 生成元数据文件

运行方式：

```powershell
python scripts\parse_demo_sample.py demo\match730_003825715054175584453_1941916173_129.dem --output-dir outputs
```

默认输出到：

- [`outputs/`](./outputs)

以当前示例 demo 为例，生成目录是：

- [`outputs/match730_003825715054175584453_1941916173_129/`](./outputs/match730_003825715054175584453_1941916173_129)

其中包含：

- [`ticks.csv`](./outputs/match730_003825715054175584453_1941916173_129/ticks.csv)
- [`player_death.csv`](./outputs/match730_003825715054175584453_1941916173_129/player_death.csv)
- [`inferred_rounds.csv`](./outputs/match730_003825715054175584453_1941916173_129/inferred_rounds.csv)
- [`metadata.json`](./outputs/match730_003825715054175584453_1941916173_129/metadata.json)

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

## 回合导图

### 导出单张静态图

```powershell
python scripts\animate_round.py outputs\match730_003825715054175584453_1941916173_129 --round 1 --format png
```

### 导出单回合动画

```powershell
python scripts\animate_round.py outputs\match730_003825715054175584453_1941916173_129 --round 1 --format gif
```

### 导出回合区间

```powershell
python scripts\animate_round.py outputs\match730_003825715054175584453_1941916173_129 --round 1-4 --format gif
```

### 不写 `--round`

不写 `--round` 时，默认导出全部推断回合。

```powershell
python scripts\animate_round.py outputs\match730_003825715054175584453_1941916173_129 --format gif
```

### 当前渲染内容

渲染结果包含：

- Awpy 官方地图底图
- 玩家当前位置
- 玩家尾迹
- 玩家朝向扇形
- 玩家死亡位置同色 `x`

当前配色约定：

- 警：`#1991BD`
- 匪：`#D9CD21`
- 朝向扇形透明度：`0.6`

## GUI 播放器

启动本地 GUI：

```powershell
python scripts\round_gui.py outputs\match730_003825715054175584453_1941916173_129
```

只展示指定回合范围：

```powershell
python scripts\round_gui.py outputs\match730_003825715054175584453_1941916173_129 --round 1-4
```

GUI 当前支持：

- 选择推断回合
- 播放 / 暂停
- 拖动时间帧
- 调整 `frame step`
- 调整 `trail`
- 调整 `facing radius`
- 调整 `facing FOV`
- 基于 Awpy 地图底图显示玩家移动

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

## 当前状态

当前仓库更接近“第一版可运行的数据与可视化工作流”，已经可以用于：

- 从 demo 稳定导出结构化数据
- 快速检查地图、玩家、回合分段
- 在地图背景上查看单回合玩家运动

还没有系统完成的部分主要是：

- 更严格的 live phase 识别
- 真正面向透视挂鉴别的特征工程
- 视角行为统计与信息论指标
- 训练 / 验证数据集构建

## 后续方向

下一阶段更值得做的是：

- 导出更多事件表，例如 `damage`、`shots`、`grenades`
- 做视角变化速度、停顿、预瞄等行为特征
- 将 `ticks` 与击杀事件窗口联表
- 引入信息论指标，例如熵、互信息、条件信息增益
- 在 GUI 中增加更强的筛选与事件高亮能力
