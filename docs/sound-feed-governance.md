# Sound Feed Data Governance

这份文档定义 `wall` 在把声音接入信息流 feed 之前，需要先完成的数据治理边界。

目标不是先把所有声音都塞进 sidebar。

目标是先回答三件事：

1. 哪些声音属于正式信息语义
2. 哪些声音只适合渲染或 debug
3. 哪一层负责去噪、归类和 feed 组装

## 1. 当前问题

当前 `sound_effect.parquet` 已经能支持 viewer 声音圈渲染，但它还不是一个适合直接进入信息流的干净语义表。

现状特征：

- 它混合了 parser 原始事件和推断事件
- 它混合了 gameplay 语义和渲染参数
- 它的 `sound_kind` 粒度偏粗，`utility`/`bomb` 下仍然混着很多不同含义
- 它主要服务于 `SoundTimeline` 绘制，而不是服务于“玩家听到了什么”

当前样本中最明显的问题是：

- `inferred_movement` 数量远大于其他声音来源
- 这类事件适合声音圈提示，但不适合直接进入 feed
- 如果不先治理，sidebar 会迅速被低价值 movement 噪声淹没

因此：

- `sound_effect.parquet` 不能直接等同于 sound feed source
- 声音 feed 不能直接复用现在的“全量声音事件表”

## 2. 架构边界

按当前架构，声音 feed 应新增一条独立于渲染的正式语义路径：

```text
raw sound-like events
  -> normalized sound_effect.parquet
  -> domain sound governance / classification
  -> SoundExposure or sound info-event builder
  -> InfoEvent
  -> viewer feed
```

边界约束：

- parse 层负责产出稳定的标准化声音事件表
- domain 层负责声音语义分级、去噪、合并和“是否值得进 feed”的判断
- viewer 只消费已经格式化好的 `InfoEvent`
- `render_sound.py` 不负责决定哪些声音能进入 sidebar

## 3. 正式分层

### 3.1 Layer A: `sound_effect.parquet`

这是 parse 后的标准化声音事件表。

职责：

- 统一各类声音事件的基础字段
- 保留来源、位置、半径、持续时间、发声者等信息
- 供 viewer 声音圈、debug、后续 domain 语义加工消费

非职责：

- 不直接定义 sidebar feed 内容
- 不直接表达“谁理论上听到了什么”
- 不保证每一行都值得进入信息流

### 3.2 Layer B: Sound Governance / Classification

这是 domain 侧新增的正式治理层。

职责：

- 统一声音类别
- 标记事件是否属于 feed candidate
- 为后续 `SoundExposure` 提供稳定输入
- 吸收当前分散在 `sound_kind`、`sound_source`、`detail` 里的语义

### 3.3 Layer C: Sound Exposure / Sound Info Events

这是面向信息流的语义层。

职责：

- 表达“某玩家在某时刻理论上能听到什么”
- 对同源短时间重复事件做聚合
- 生成 viewer 可直接消费的 `InfoEvent`

这层才是声音进入 sidebar 的正式入口。

## 4. 治理原则

### Rule 1: render source 不等于 feed source

能画出来，不代表应该出现在 sidebar。

例如：

- `inferred_movement`
- `inferred_landing`
- 高频 `grenade_bounce`

这类事件可以继续留在 `sound_effect.parquet` 支持渲染，但默认不应直接进入 feed。

### Rule 2: 先做事件分类，再做感知建模

在做“谁能听到什么”之前，先把“这是什么声音”做稳定。

否则后续 `SoundExposure` 会直接建立在不稳定 schema 上。

### Rule 3: `sound_kind` 不足以支撑 feed

当前 `sound_kind` 更偏展示分类，不足以表达 feed 语义。

尤其：

- `utility` 下面混有 smoke / flash / HE / inferno / reload / zoom
- `bomb` 下面混有 pickup / drop / begin plant / begin defuse / abort / defused / exploded

因此后续 feed 不应只靠 `sound_kind` 判断。

### Rule 4: inferred 事件必须显式区分

推断事件和 parser 原始事件必须保持显式可区分。

例如：

- `player_footstep` 与 `inferred_movement`
- 真实落地声与 `inferred_landing`

feed v1 应优先使用更稳定的原始事件，推断事件只在明确证明价值后再进入。

### Rule 5: 先做 observer-agnostic 治理，再做 observer-specific exposure

第一阶段先解决：

- 事件分类
- 噪声压缩
- 事件重要度
- feed 候选筛选

第二阶段再做：

- 距离可听性
- 墙体/几何阻隔
- observer-specific heard events

## 5. 建议新增字段

不建议继续只依赖 `sound_kind + sound_source + detail` 的松散组合。

建议在 domain 治理层先形成稳定分类字段：

```text
sound_class
sound_action
source_type
feed_policy
importance
dedupe_key
```

建议含义：

- `sound_class`
  例：`movement / weapon / utility / bomb / damage`
- `sound_action`
  例：`footstep / landing / gunfire / reload / zoom / detonate / bounce / plant / defuse`
- `source_type`
  例：`parser_event / inferred / derived`
- `feed_policy`
  例：`never / candidate / always`
- `importance`
  例：`low / medium / high / critical`
- `dedupe_key`
  用于短窗口聚合相同语义声音

这些字段未必一开始就要全部落盘到 dataset artifact，但 domain 内必须先有稳定语义。

## 6. Feed V1 准入建议

第一版 sidebar 声音 feed 应严格收缩，只保留高信息价值事件。

建议默认纳入：

- `gunfire`
- `bomb_beginplant`
- `bomb_begindefuse`
- `bomb_abortdefuse`
- `bomb_defused`
- `bomb_exploded`
- `bomb_dropped`
- `smokegrenade_detonate`
- `flashbang_detonate`
- `hegrenade_detonate`
- `inferno_startburn`

建议默认不纳入：

- `inferred_movement`
- `player_footstep`
- `inferred_landing`
- `grenade_bounce`
- `weapon_zoom`
- `weapon_reload`
- 普通 `item_drop`
- 普通 `player_hurt`

说明：

- 这不是永久排除
- 这是为了先得到可用的高信噪比 feed

后续若要加入脚步，也应先经过聚合和 observer-specific 过滤，而不是逐条上屏。

## 7. 第一阶段实现建议

建议分三步，不要一步做到完整听觉系统。

### Step 1: schema 治理

目标：

- 定义稳定的声音语义分类
- 把 render-facing 声表和 feed-facing 语义入口分开

产物建议：

- `docs/sound-feed-governance.md`
- domain 侧声音分类 helper 或 dataclass

### Step 2: feed candidate builder

目标：

- 从 `sound_effect.parquet` 生成高信噪比 sound info candidates
- 不做 observer-specific heard 判断

这一步可以先产出：

- round-scoped `InfoEvent`
- message 例如 `12.45s  bomb begin defuse`
- 或 `18.20s  smoke detonated`

### Step 3: SoundExposure

目标：

- 建模谁理论上能听到什么
- 把“场上发生了声音”升级为“玩家获得了声音信息”

只有到了这一步，声音才真正进入 Information State 主链路。

## 8. 对当前代码的直接约束

后续实现应避免：

- 在 `viewer/info_events.py` 里直接硬编码大量 `sound_source` 分支
- 在 viewer 层直接消费原始 `sound_effect` 并临时拼消息
- 让 `render_sound.py` 兼任 sidebar feed 语义判断

建议新增的正式入口应放在 domain 或 viewer 的 feed builder 边界，而不是放在 renderer。

## 9. 当前结论

现在要做的不是“把声音接进 feed”。

现在要做的是：

1. 承认 `sound_effect.parquet` 目前是基础声音源 artifact
2. 明确它不是 feed 的最终语义表
3. 先建立声音分类和准入规则
4. 再做高信噪比 sound feed
5. 最后再做真正的 `SoundExposure`

这样才能和当前架构、roadmap 保持一致。
