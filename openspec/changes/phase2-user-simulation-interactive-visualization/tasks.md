## 1. 模拟引擎后端 (simulation-engine)

- [x] 1.1 DataManager 新增 get_simulation_snapshot(time_index, bbox) 方法
- [x] 1.2 实现 cell-to-station 映射（200m 阈值聚合）
- [x] 1.3 新增 /api/simulation/snapshot API 端点
- [x] 1.4 新增 /api/simulation/info API（时间片数、用户数、基站数）
- [x] 1.5 新增 /api/simulation/station_locs API（基站坐标缓存）
- [x] 1.6 新增 /api/simulation/station_id_map API（ID 映射）
- [x] 1.7 新增 /api/simulation/station_time_series/:id API（时间序列）
- [x] 1.8 Handover 检测：前后时间片 base_id 对比，生成弧线坐标
- [x] 1.9 快照返回 11 字段用户数组 + station_stats 聚合统计

## 2. 连接可视化 (connection-visualization)

- [x] 2.1 前端创建 sim-lines-layer（Line Layer）
- [x] 2.2 信号质量三色着色：绿 (>-80dBm) / 黄 (-80~-100) / 红 (<-100)
- [x] 2.3 动态线宽：zoom 9→0.3, 13→1, 16→2
- [x] 2.4 动态透明度：zoom 9→0.15, 12→0.45, 16→0.75
- [x] 2.5 修复 line-dasharray 渲染失败问题（改为实线 + round cap）
- [x] 2.6 修复 minzoom:11 导致默认 zoom 10.5 下不可见（改为 9）
- [x] 2.7 设置 Lines 默认可见（visibility: visible）

## 3. 密度热力图 (density-heatmap)

- [x] 3.1 创建 sim-heatmap-layer（Heatmap Layer）
- [x] 3.2 流量加权：heatmap-weight 基于 traffic 字段
- [x] 3.3 配色方案：透明→蓝→青→绿→黄→红渐变
- [x] 3.4 默认关闭，通过图层按钮切换

## 4. Handover 可视化 (handover-visualization)

- [x] 4.1 创建 sim-handover-arcs（Line Layer）
- [x] 4.2 弧线数据：用户位置→旧基站→新基站 三点折线
- [x] 4.3 紫色着色 (#a29bfe) + 动态线宽
- [x] 4.4 默认可见，通过图层按钮切换
- [x] 4.5 弹窗中显示 "🔄 Handover occurred" 标记

## 5. 用户图标渲染 (user-icon-rendering)

- [x] 5.1 SDF 像素绘制 24×24 小人图标（Uint8ClampedArray）
- [x] 5.2 addImage('sim-person-sdf', ..., {sdf: true})
- [x] 5.3 icon-color 基于信号强度着色：绿/黄/红
- [x] 5.4 LOD 文字标签：zoom < 13 无文字，13+ 显示 app emoji，15+ 显示 emoji + role
- [x] 5.5 基站着色：根据接入用户数 step 着色（0→灰, 1→蓝, 10→绿, 30→黄, 50→红）

## 6. 用户弹窗 (user-popup)

- [x] 6.1 点击用户点弹出详情 Popup
- [x] 6.2 显示：user_id、role、movement（带 emoji）、signal、traffic
- [x] 6.3 显示 APP：emoji + app_name + app_category
- [x] 6.4 显示 Handover 状态标记

## 7. 基站时间序列 (station-time-series)

- [x] 7.1 点击基站弹出时间序列图
- [x] 7.2 双轴 Chart.js：左轴用户数（青色）+ 右轴流量 MB（黄色虚线）
- [x] 7.3 当前时间片游标跟随
- [x] 7.4 显示基站 PRB 利用率估算

## 8. APP 类别 emoji 标识 (app-emoji-labels)

- [x] 8.1 定义 APP_CAT_EMOJI 映射（19 类别 → emoji）
- [x] 8.2 弹窗中 APP 名称前显示类别 emoji
- [x] 8.3 地图标签 zoom 13+ 显示 app emoji
- [x] 8.4 GeoJSON feature 添加 app_emoji 属性

## 9. 播放控制与 UI (playback-control)

- [x] 9.1 播放/暂停按钮 + 时间轴滑块
- [x] 9.2 速度控制按钮：0.5x / 1x / 2x / 4x
- [x] 9.3 图层切换按钮：Dots / Lines / Heatmap / Handovers
- [x] 9.4 实时统计仪表盘：用户数 / 流量 / Handover / 基站数
- [x] 9.5 时间显示格式：Day X HH:MM

## 10. 性能优化 (performance-optimization)

- [x] 10.1 后端 Gzip 压缩中间件（compresslevel=6，>1KB 响应压缩）
- [x] 10.2 前端预取缓存：当前帧 +5 帧预取，最大 50 帧缓存
- [x] 10.3 缓存 LRU 淘汰：超过容量删除最旧条目
- [x] 10.4 基站坐标/ID映射仅首次请求，前端缓存

## 11. 部署与验证 (deployment)

- [x] 11.1 远程部署验证：Flask on cluster-4090 + SSH 隧道 + Electron
- [x] 11.2 本地部署验证：本机 Python + Electron 直连 localhost
- [x] 11.3 Electron 生产环境关闭 DevTools
- [x] 11.4 根目录前端文件同步（script.js/style.css/index.html）
- [x] 11.5 服务器前端文件同步（SCP 部署）
- [x] 11.6 Git 提交与推送

## 未实现（需求文档提及但排除）

- [ ] Sankey 流量流向图（用户→基站→核心网）
- [ ] 网格聚合显示（>1 万用户按网格计数）
- [ ] 步行/驾驶移动模式区分（数据层仅 move/stay）
