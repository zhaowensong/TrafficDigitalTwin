## 上下文

Phase 1 已完成：
- 基站实体属性扩展（base2info_extended.json，5326 站点）
- 用户数据接入（10000 用户，336 万轨迹点，7天×30分钟粒度）
- APP 分类模型（app_models.py，19 类别）
- DataManager 数据访问层
- Electron 桌面客户端 + C/S 架构部署

Phase 2 需要实现用户行为仿真的可视化层，让用户能直观看到万人级别用户在城市中的移动、连接、切换行为。

## 目标 / 非目标

**目标：**
- ✅ 实现模拟快照 API，支持按时间片获取全部用户状态
- ✅ 用户-基站连接线可视化（信号质量着色）
- ✅ 用户密度热力图（流量加权）
- ✅ Handover 切换检测与弧线动画
- ✅ 用户图标（SDF 小人 + 信号着色 + LOD 标签）
- ✅ 基站时间序列分析（双轴图：用户数+流量）
- ✅ PRB 资源利用率估算
- ✅ APP 类别 emoji 标识
- ✅ 播放控制与性能优化
- ✅ 本地/远程双模式部署验证

**非目标：**
- 不实现 Sankey 流量流向图（需求文档提及，当前优先级低）
- 不实现网格聚合显示（热力图已部分替代）
- 不区分步行/驾驶移动模式（数据层仅有 move/stay）
- 不实现第三阶段的微突发场景和无人机调度

## 决策

### 1. 模拟数据传输方案
**决策**: 全量快照模式，每个时间片返回所有用户数据（~2.4MB/请求）
**理由**:
- 10000 用户 × 11 字段的数据量可控
- Gzip 压缩后仅 ~357KB（86% 压缩率）
- 本地延迟 0.19s，远程 1.54s（88% 网络延迟）
- 预取缓存（5帧）可掩盖加载时间
**替代方案**: 增量更新（仅传差异）— 实现复杂度高，收益有限

### 2. 用户图标渲染方案
**决策**: SDF（Signed Distance Field）像素绘制 + Mapbox Symbol Layer
**理由**:
- Uint8ClampedArray 直接绘制 24×24 像素小人图标
- 支持信号质量实时着色（绿/黄/红）
- Mapbox 原生 SDF 支持，GPU 加速渲染
- LOD：zoom < 13 仅显示点，13+ 显示 emoji，15+ 显示 role
**替代方案**: Canvas 2D 图片 — 不支持运行时着色

### 3. Handover 检测方式
**决策**: 前后时间片 serving_base_id 对比
**理由**:
- 简单高效，直接在 get_simulation_snapshot() 中计算
- 同时生成弧线数据（用户位置 → 旧站 → 新站）
- 前端用 GeoJSON LineString 绘制弧线

### 4. 基站 Cell 聚合
**决策**: 200 米阈值，同一基站不同 Cell 合并
**理由**:
- 轨迹数据有 10667 个 cell ID，地图基站仅 5326 个
- 200 米内的 cell 视为同一物理基站的不同扇区
- 7809/10667 cell 成功映射到 4447 个地图基站
- 2858 个 cell（27%）距离 > 200 米未映射（避免错误关联）

### 5. APP 标识方案
**决策**: 按 19 个类别（非 90 个 APP 名称）分配 emoji
**理由**:
- APP 名称为合成数据（非真实），逐个设计图标无意义
- 19 类别覆盖全部 APP，emoji 辨识度高
- 弹窗显示完整 APP 名称，地图标签仅显示 emoji

## 技术架构

```
[Electron 客户端]
  ├─ Mapbox GL JS (WebGL 渲染)
  │   ├─ sim-users-dots (Symbol Layer, SDF 小人图标)
  │   ├─ sim-lines-layer (Line Layer, 信号着色连接线)
  │   ├─ sim-heatmap-layer (Heatmap Layer, 流量加权)
  │   └─ sim-handover-arcs (Line Layer, 切换弧线)
  ├─ Stats Dashboard (实时统计面板)
  ├─ Chart.js (双轴时间序列)
  └─ 预取缓存 (5帧预取, 50帧容量)
        │
        │ HTTP REST (Gzip 压缩)
        ▼
[Flask 后端]
  ├─ /api/simulation/snapshot?t=N (快照)
  ├─ /api/simulation/info (元信息)
  ├─ /api/simulation/station_locs (基站坐标缓存)
  ├─ /api/simulation/station_id_map (ID 映射)
  ├─ /api/simulation/station_time_series/:id (时间序列)
  └─ DataManager
       ├─ user_trajectories: {uid: [336 records]}
       ├─ base_id_to_loc: {numeric_id: [lng, lat]}
       └─ cell_to_station: {cell_id: map_hex_id} (200m 阈值)
```

## 数据 Schema

### 快照用户数组（11 字段）
```
[lng, lat, base_id, signal_dbm, traffic_mb, handover, user_id, movement, app_category, role, app_name]
```

### 轨迹记录（14 字段）
```
[timestamp, longitude, latitude, serving_base_id, serving_base_key, place_type,
 movement_state, app_id, app_name, app_category, traffic_mb, signal_dbm,
 session_duration_min, distance_to_serving_base_m]
```

## 性能指标

| 指标 | 本地运行 | 远程 (SSH 隧道) |
|------|---------|----------------|
| Snapshot API | 0.19s | 1.54s |
| Stations API | 0.15s | 0.80s |
| 数据加载时间 | ~24s | ~20s |
| 快照大小 (原始) | 2.4 MB | 2.4 MB |
| 快照大小 (Gzip) | 357 KB | 357 KB |
| 内存占用 (RSS) | ~3.3 GB | ~3.3 GB |
| GPU 显存 | ~1.9 GB | ~1.9 GB |
