# README Details

这个文档存放从主 `README.md` 挪出来的操作细节和补充说明。

主 README 保持短、面向第一次进入仓库的人；这里保留稍微啰嗦一点的内容。

## CLI 行为

主入口：

```powershell
wall --help
```

常见行为规则：

* 传 `.dem` 文件时，如果对应数据集目录不存在，会先解析再打开 viewer
* 传 `.dem` 文件时，如果对应数据集目录已经存在，会直接复用现有数据集
* 传 `outputs\xxx` 这种数据集目录时，会直接打开 viewer
* 如果想强制更新中间数据，使用 `--renew`

例如：

```powershell
wall demo\match730_003825715054175584453_1941916173_129.dem --renew
wall outputs\match730_003825715054175584453_1941916173_129
```

显式辅助命令：

* `wall catalog <dataset_dir>`
* `wall assets check ...`
* `wall assets init ...`
* `wall visibility <dataset_dir>`
* `wall sound-exposure <dataset_dir>`
* `wall info-feed-audit <dataset_dir>`

## 可见性补充

当前 `wall visibility` 的核心语义：

* 先做敌我、存活和位置有效性过滤
* 再做大约 `90°` 的 FOV 判断
* 对 FOV 内目标调用 Awpy `VisibilityChecker` 做地图几何 LOS 判断
* 输出 `pair` 或 `summary` 表

常见命令：

```powershell
wall visibility outputs\match730_003825715054175584453_1941916173_129
wall visibility outputs\match730_003825715054175584453_1941916173_129 --output-kind summary
wall visibility outputs\match730_003825715054175584453_1941916173_129 --split-rounds
wall visibility outputs\match730_003825715054175584453_1941916173_129 --profile-visibility
```

viewer 侧当前行为：

* 如果 dataset 中存在 `visibility.parquet`，viewer 会在启动时 preload all-round visibility events
* 如果缺少 `visibility.parquet`，viewer 仍然可以正常打开，但 visibility feed 为空
* 普通 viewer 不会在启动时现场创建 Awpy geometry runtime

当前 `sound_exposure` 补充：

* `sound_exposure.parquet` 是可选 artifact
* 如果 dataset 中存在 `sound_exposure.parquet`，viewer 会把其中高信息价值声音并入右侧 `Info Feed`
* 如果缺少 `sound_exposure.parquet`，viewer 仍然可以正常打开，只是没有 sound-derived feed
* 如果 `sound_exposure.parquet` 损坏或 schema 不兼容，viewer 会 fail-soft 忽略它，不会阻止 GUI 启动

## Viewer 补充

当前 pygame viewer 除了基本播放控制，还包括：

* 右侧 `Players` 列表
* 右侧 `Info Feed`
* 点击玩家后，按选中玩家过滤 Info Feed
* info feed 默认自动跟随最新事件

visibility event 文本格式类似：

```text
80.30s  playerA spotted playerB
```

sound-derived event 文本格式类似：

```text
12.45s  CT heard 4 Glock shots from T
18.20s  playerA heard smoke bloom
22.10s  playerB heard movement from playerC
```

当前 sound-derived feed 规则：

* gunfire、关键 utility detonate、关键 bomb 声音默认允许进入 feed
* `movement/locomotion` 和 `movement/hard_step` 允许进入 feed，但会在 feed builder 层做 merge / threshold / dedupe
* `damage/hurt`、`weapon/reload`、`weapon/zoom` 当前默认不进入 feed

当前诊断命令：

```powershell
wall info-feed-audit outputs\match730_003825715054175584453_1941916173_129
```

这个命令会导出 viewer 当前实际生成的 Info Feed 审计表，方便检查：

* movement 是否过多
* hard_step 是否刷屏
* gunfire 文案是否清晰
* utility / bomb 是否足够突出

## Dataset 补充

默认输出目录：

* `outputs/`

常见 dataset 文件：

* `ticks.parquet`
* `player_death.parquet`
* `inferred_rounds.parquet`
* `metadata.json`

读取端默认优先读 `parquet`，不存在时再回退到 `csv`。

## 相关文档

进一步的设计和架构说明见：

* `docs/technical-roadmap.md`
* `docs/architecture.md`
* `docs/viewer-decoupling-checklist.md`
