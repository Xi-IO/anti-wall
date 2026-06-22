# Technical Roadmap

这份文档记录 `wall` 当前的技术路线、兼容策略、后续改造方向，以及与“信息收集/能力评估”相关的设计思路。

## Project Scope

`wall` 当前优先级是：

1. 做好 CS2 demo 的解析
2. 做好数据集目录格式
3. 做好本地播放器

也就是说，当前项目先聚焦“播放器”，不把“鉴挂”作为当前阶段主目标。

## Current Architecture

当前代码已经从“脚本集合”收敛到“可安装包 + 统一 CLI”。

正式实现位于：

- `src/wall/cli.py`
- `src/wall/io/`
- `src/wall/render/`
- `src/wall/viewer/`

职责划分如下：

- `cli`
  - 命令入口
  - `parse / view / open / catalog`
- `io`
  - demo 解析
  - 表读写
  - DuckDB catalog
- `render`
  - 地图渲染
  - 视觉效果
  - pygame 组件
- `viewer`
  - 本地播放器
  - 时间轴、回合切换、交互
  - 当前内部已进一步拆分为：
    - `viewer/cli.py`
    - `viewer/shell.py`
    - `viewer/runtime.py`
    - `viewer/state.py`
    - `viewer/layout.py`
    - `viewer/ui.py`
    - `viewer/renderer.py`
    - `viewer/render_player.py`
    - `viewer/render_sound.py`
    - `viewer/render_bomb.py`
    - `viewer/render_utility.py`
    - `viewer/render_config.py`

## CLI Direction

统一播放器入口是：

```powershell
wall demo\match.dem
```

它表示：

1. 如有需要先解析 demo
2. 再直接打开 viewer

如果传入的是 `outputs\xxx` 这种数据集目录，则直接打开。

如果想强制更新中间数据，则使用：

```powershell
wall demo\match.dem --renew
```

当前只保留一个显式辅助子命令：

- `wall catalog <dataset_dir>`

## Dataset Direction

当前标准数据集格式是：

- `parquet` 表文件
- `metadata.json`

典型目录结构：

```text
outputs/
  match_xxx/
    metadata.json
    ticks.parquet
    player_death.parquet
    player_hurt.parquet
    grenades.parquet
    inferno_startburn.parquet
    inferred_rounds.parquet
```

基本原则：

1. demo 文件是输入
2. dataset 目录是标准中间产物
3. viewer / render / DuckDB 都只面向 dataset

`duckdb` 不是主存储，而是 dataset 上的查询层。

## Compatibility Strategy

仓库当前不再保留脚本形式的运行入口。

运行前需要先安装本地包：

```powershell
pip install -e .
```

当前确定的处理方式：

1. 正式实现只继续放在 `src/wall/`
2. 不再保留脚本形式的兼容运行入口
3. 新文档和命令示例统一使用 `wall ...`
4. 对于不再需要的旧脚本，直接删除，不继续保留多入口

当前仓库已经完成这一步，后续只维护：

- `wall <demo或数据集目录>`

## Why The Old Viewer Entry Hung

之前出现过 `--help` 都会卡住很久的问题。

根因不是 demo 解析慢，而是旧入口在顶层直接 import 整个 viewer 实现，导致：

- `pygame`
- 渲染模块
- 地图模块

在显示帮助前就被一起加载。

当前修复方案是：

1. `wall.cli` 改成懒加载
2. viewer 启动链路拆成 `cli -> shell -> runtime / renderer`
3. 不再保留脚本形式的多入口
4. `--help` 不再触发重模块加载

## Near-Term Cleanup Direction

接下来继续收敛代码时，优先级建议如下：

1. 保持 `src/wall/*` 为唯一正式实现
2. 不再恢复多入口脚本
3. 为 `parse -> dataset -> viewer` 主链路补最小测试
4. 把资源路径、地图路径、输出路径继续统一
5. 保持语义查询在 domain，viewer 只做 orchestration 和 drawing

## Perception Roadmap

播放器后续会需要从“看回放”升级到“看信息差”。

建议分成三类感知信息：

- `直接可见`
  - 当前视野内敌人
  - 最近一次可见位置
  - 可见投掷物、烟、火、C4
- `直接可听`
  - 枪声
  - 脚步
  - 投掷物
  - 下包 / 拆包
- `公共已知`
  - 击杀信息
  - 雷包状态
  - 回合阶段变化

未来建议新增模块：

- `src/wall/domain/perception.py`
- `src/wall/domain/vision.py`
- `src/wall/domain/audio.py`
- `src/wall/domain/knowledge.py`

## Sound Visualization

声音可视化是后续最容易落地的一项。

建议分三层：

- `事件层`
  - 谁在什么 tick 产生了声音
- `传播层`
  - 简化听距 / 听觉半径
- `感知层`
  - 哪些玩家在该 tick 附近理论上能听到

版本 1 不需要追求真实音频模拟，重点是：

- 能否听到
- 大概何时听到
- viewer 如何展示

## Player Knowledge Panel

后续目标之一是：

点击右下名册中的某个玩家，显示“到当前时刻为止他理论上能收集到的全部信息”。

建议先把“信息”定义为播放器可推导的外部信息上界，而不是强行还原玩家真实脑内状态。

面板可以按这些栏目展示：

- `Visible now`
- `Heard recently`
- `Known enemy positions`
- `Bomb knowledge`
- `Utility knowledge`

## Vision And Visibility

“正面 90 度视角内可见的人”可以做，但要分阶段：

### Stage 1: FOV only

- 只判断朝向扇形
- 不判断遮挡
- 适合 UI 原型

### Stage 2: 2D line-of-sight

- 引入平面遮挡
- 需要墙体 / blocker / polygon
- 先忽略楼层

### Stage 3: 3D or quasi-3D visibility

- 加入高度、上下层、室内外遮挡
- 更接近真实游戏可见性
- 工程成本最高

当前阶段更建议先做：

- `FOV-only`
- 或 `FOV + 少量启发式过滤`

而不是直接追求完整 3D 可见性。

## Map Geometry Limitation

当前播放器主要基于地图底图，不是真实 3D 地图建模。

这意味着：

- 角度判断简单
- 真正遮挡判断困难
- 楼层、高低差、墙内外判定都不可靠

当前可选路线：

1. 纯简化路线
   - 只做 FOV 和距离
2. 中间路线
   - 为少数地图建立 2D blocker
3. 重路线
   - 引入真实几何/BSP/nav 数据

如果当前目标是播放器，中间路线最务实。

## Player Scoring Direction

远期可以做“玩家操作评分”，从：

- 菜鸟
- 普通
- 高手
- 可疑

这条路线的核心不是先接模型，而是先定义：

1. 玩家当时能获得什么信息
2. 玩家当时做了什么操作
3. 该操作是否和信息条件匹配

也就是先做“信息约束下的行为解释”。

## Small Models vs LLMs

远期如果要评分，模型是有意义的，但优先级应该是：

1. 规则系统
2. 统计特征
3. 小模型
4. 大模型

更具体地说：

- 小模型有必要
  - Logistic Regression
  - XGBoost
  - LightGBM
  - 简单时序模型
- 大模型不是当前底层核心
  - 不擅长原始时序几何判断
  - 成本更高
  - 更适合做解释和报告生成

因此更合理的路线是：

1. 先做 deterministic features
2. 再用小模型做评分
3. 最后再考虑用大模型把结果组织成人话说明

## Recommended Build Order

如果继续按播放器方向推进，建议顺序如下：

1. 声音事件与听觉可视化
2. 玩家信息面板
3. 简化 FOV 可见性
4. 2D 遮挡层
5. 信息时间线回放
6. 信息驱动的操作点评
7. 最后再考虑模型评分
