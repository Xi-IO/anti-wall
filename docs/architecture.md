# Architecture

这份文档描述 `wall` 当前的正式架构边界，以及各层之间应该如何协作。

## Overview

当前主链路是：

```text
demo file
  -> parse / dataset build
  -> domain timelines / semantic objects
  -> viewer orchestration
  -> pygame rendering
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
- 串起 parse 和 viewer 启动流程

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

边界：

- 面向原始表和落盘格式
- 不承担 viewer UI 逻辑
- 只做必要的数据整理，不做播放器特化绘制

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

边界：

- 负责“发生了什么”
- 不负责“画成什么样”

### 4. Viewer layer

目录：

- `src/wall/viewer/`

职责：

- 播放控制
- 回合切换
- 缓存当前帧
- 把 domain 查询结果组织成一帧画面

当前拆分如下：

- `shell.py`
  - 主事件循环
  - 播放状态推进
  - sidebar / timeline 交互
- `runtime.py`
  - round 切换
  - frame cache 生命周期
- `session.py`
  - viewer 已加载数据的会话对象
- `state.py`
  - 播放状态和下拉状态
- `layout.py`
  - 下拉面板等布局计算
- `ui.py`
  - sidebar / bottom bar / 图标等 UI 绘制辅助
- `renderer.py`
  - 一帧渲染总协调器
- `render_player.py`
  - 玩家相关纯绘制
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
- 不应该重新解释 raw DataFrame
- 不应该复制 domain 已经表达过的 gameplay 规则

### 5. Render support layer

目录：

- `src/wall/render/`

职责：

- 地图底图
- pygame 相关底层渲染能力
- viewer 会复用的一些视觉支持逻辑

边界：

- 提供底层绘制基础设施
- 不应重新成为新的“总控 app.py”

## Runtime Flow

正常播放链路：

```text
wall <demo-or-dataset>
  -> wall.cli
  -> wall.viewer.cli
  -> viewer.shell.PygameRoundViewer
  -> viewer.runtime.RoundRuntime
  -> viewer.renderer.PygameRoundRenderer
  -> render helpers
```

如果输入是 demo：

```text
demo
  -> io parse
  -> outputs/<match_dataset>
  -> viewer load dataset
```

如果输入已经是 dataset：

```text
dataset dir
  -> viewer load directly
```

## Data Flow

当前推荐的数据流方向是：

```text
raw tables
  -> domain semantic objects
  -> RoundData semantic viewer input
  -> renderer
```

viewer 当前应优先消费：

- `round_players`
- `bomb_timeline`
- `utility_timeline`
- `sound_timeline`
- `frame_ticks`
- `round_start_tick`

而不是重新在 viewer 内部直接过滤原始表。

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

原则：

- 特效纹理放 `effects/`
- 武器/装备 icon 放 `icons/equipment/`
- UI 控件 icon 放 `ui/icons/`

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

## Current Status

当前已完成的主要收敛：

- `viewer/app.py` 已退役
- viewer 已拆成 shell / runtime / renderer / render helpers
- sound / bomb / utility / player 语义已基本从 viewer 主路径抽离
- assets 已按 effects / equipment / ui 分类
- viewer 当前主路径已主要消费 semantic objects，而不是长串原始表参数

## Remaining Cleanup Direction

后续清理仍然建议沿这几个方向继续：

1. 补少量纯 helper 单测
2. 继续压缩 `renderer.py` 的协调复杂度
3. 保持新功能先扩 domain，再进 viewer
4. 保持 `docs/` 中的架构文档、roadmap、checklist 同步

## Related Docs

- `docs/technical-roadmap.md`
- `docs/viewer-decoupling-checklist.md`
