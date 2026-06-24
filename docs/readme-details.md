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

## Viewer 补充

当前 pygame viewer 除了基本播放控制，还包括：

* 右侧 `Players` 列表
* 右侧 `Visibility Feed`
* 点击玩家后，按选中玩家过滤 visibility feed
* info feed 默认自动跟随最新事件

visibility feed 文本格式类似：

```text
80.30s  playerA spotted playerB
```

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
