# Side Roadmap: Smoke Detonation Corpus

这份文档记录一个独立 side project 的路线图。

当前状态：

- 不进入当前主线开发
- 不影响现有 `wall` parse / visibility / viewer 计划
- 仅作为未来可能启动的 backlog 方案保留

## 0. 项目定位

这是一个独立 side project。

目标只有一个：

```text
从大量 CS2 demo 中提取烟雾弹爆点，聚类后标注常见 smoke occlusion zones。
```

本项目不分析比赛，不还原投掷轨迹，不研究谁扔的，不研究什么时候扔的。

最终产物：

```text
map_smoke_zones.parquet
```

供主项目判断烟雾遮挡模型使用。

---

## 1. 核心目标

输入：

```text
public demo links
```

处理：

```text
download demo
parse smoke detonation points
append to corpus
delete demo
cluster points
manual zone labeling
export map_smoke_zones.parquet
```

输出：

```text
smoke_detonation_points.parquet
map_smoke_zones.parquet
demo_manifest.parquet
```

---

## 2. 非目标

本项目不保留：

```text
thrower_id
thrower_side
round_id
tick
start_tick
end_tick
trajectory
bounce_count
weapon info
player info
team info
damage info
visibility info
sound info
full parser output
```

本项目不做：

```text
demo viewer
visibility calculation
smoke duration modeling
grenade trajectory reconstruction
tactical event feed
player information chain
```

---

## 3. 最小数据表

### 3.1 smoke_detonation_points.parquet

核心表。

```text
point_id
map_name
demo_hash
x
y
z
source
parser_version
created_at
```

说明：

```text
point_id:
    本地唯一 ID。

map_name:
    地图名。聚类必须按地图分开。

demo_hash:
    用于去重和审计，不进入战术分析。

x, y, z:
    烟雾弹爆点坐标。

source:
    hltv / faceit / manual / other。

parser_version:
    方便以后知道这批点来自哪一版 parser。
```

不保留 round，不保留 tick，不保留 thrower。

---

### 3.2 demo_manifest.parquet

只用于工程状态管理。

```text
demo_hash
source
url_hash
map_name
status
downloaded_at
parsed_at
deleted_after_parse
error_message
```

状态：

```text
pending
downloaded
parsed
deleted
failed
skipped_duplicate
```

manifest 不参与聚类，只用于断点续跑和去重。

---

### 3.3 map_smoke_zones.parquet

最终知识库。

```text
map_name
zone_id
zone_name
zone_type
center_x
center_y
center_z
match_radius_xy
trigger_z_min
trigger_z_max
occluder_shape
occluder_radius
occluder_z_min
occluder_z_max
confidence
version
notes
```

`zone_type`：

```text
generic_disk
elevated_cylinder
portal_smoke
unknown
```

`occluder_shape`：

```text
disk
vertical_cylinder
portal
```

---

## 4. 数据流

```text
demo_links.csv
    ↓
download one demo
    ↓
parse smoke detonation points only
    ↓
append smoke_detonation_points.parquet
    ↓
delete demo immediately
    ↓
update demo_manifest.parquet
```

原则：

```text
download one
parse one
store points
delete one
continue
```

不批量囤积 demo 文件。

---

## 5. 聚类阶段

聚类只使用：

```text
map_name
x
y
z
```

每张地图单独聚类。

目标不是识别“谁扔的烟”，而是识别：

```text
哪些位置经常爆烟
哪些区域存在明显 z 分层
哪些爆点应该触发 disk blocker
哪些爆点应该触发 vertical cylinder blocker
```

输出：

```text
smoke_cluster_candidates.parquet
cluster_debug_map.png
cluster_report.md
```

候选字段：

```text
map_name
cluster_id
center_x
center_y
center_z
count
z_min
z_max
z_std
xy_radius
has_z_layers
candidate_zone_type
notes
```

---

## 6. 标注阶段

人工不标注单颗烟。

人工只标注 cluster / zone。

错误做法：

```text
第 382 颗烟 = Dust2 中门挂烟
第 918 颗烟 = Dust2 中门挂烟
```

正确做法：

```text
zone_id = de_dust2_mid_doors_elevated
zone_type = elevated_cylinder
trigger_z_min = ...
trigger_z_max = ...
occluder_shape = vertical_cylinder
```

标注结果进入：

```text
map_smoke_zones.parquet
```

---

## 7. 主项目使用方式

主项目不读取 smoke_detonation_points。

主项目只读取：

```text
map_smoke_zones.parquet
```

主项目运行时：

```text
active smoke x/y/z
    ↓
query map_smoke_zones
    ↓
classify blocker shape
    ↓
disk / vertical cylinder / portal
    ↓
evaluate LOS against blocker
```

本 side project 只负责生成知识库，不负责实时遮挡判断。

---

## 8. CLI 草案

```bash
smoke-corpus ingest demo_links.csv \
  --out data/smoke_detonation_points.parquet \
  --manifest data/demo_manifest.parquet \
  --tmp tmp/demos \
  --delete-after-parse
```

```bash
smoke-corpus cluster data/smoke_detonation_points.parquet \
  --map de_dust2 \
  --out outputs/clusters/de_dust2
```

```bash
smoke-corpus zone-draft outputs/clusters/de_dust2/smoke_cluster_candidates.parquet \
  --out outputs/zones/de_dust2_zone_draft.parquet
```

```bash
smoke-corpus zone-export outputs/zones/*.parquet \
  --out data/map_smoke_zones.parquet
```

---

## 9. Phase Plan

### Phase 1 — Detonation Point Ingestion

目标：

```text
给定 demo_links.csv，自动下载 demo，提取 smoke x/y/z，删除 demo。
```

完成标准：

```text
成功处理 20 个 demo
只留下 smoke_detonation_points.parquet
demo 文件全部删除
manifest 可断点续跑
```

---

### Phase 2 — Map-Level Clustering

目标：

```text
按地图聚类 smoke detonation points。
```

完成标准：

```text
de_dust2 可以生成 cluster report
能看到常见烟位聚集区
能看到 z 分层候选
```

---

### Phase 3 — Zone Draft

目标：

```text
从 cluster candidates 生成 zone 草案。
```

完成标准：

```text
可以人工确认：
- generic disk zone
- elevated cylinder zone
- portal smoke zone
```

---

### Phase 4 — Knowledge Base Export

目标：

```text
导出主项目可读取的 map_smoke_zones.parquet。
```

完成标准：

```text
主项目可以根据 smoke x/y/z 查 zone
能输出 blocker shape
能区分 disk 与 vertical cylinder
```

---

## 10. 最小完成标准

项目最小可用状态：

```text
输入 50 个 demo 链接
自动下载、解析、删除
最终只保留：
- smoke_detonation_points.parquet
- demo_manifest.parquet
```

这时项目已经成立。

后续 cluster、zone、主项目集成都建立在这张爆点表上。
