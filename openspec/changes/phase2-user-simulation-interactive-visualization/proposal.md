## 为什么

Phase 1 已完成网络基础设施层数字孪生：基站实体建模、用户数据接入、APP流量模型、DataManager 数据访问层、Electron 桌面客户端。Phase 2 需要在此基础上实现用户行为仿真与交互可视化：大规模用户模拟、用户-基站连接可视化、密度热力图、Handover 切换动画等。

对应平台需求文档第二阶段核心目标：
1. 引入用户层级模拟 [location, app, traffic]，可视化 + 大规模用户模拟支撑
2. 优化用户与基站之间交互可视化，实时展示基站连入人数
3. 体现车与人两种移动模式（预留接口）
4. 微突发场景模拟（留待第三阶段）

## 变更内容

1. **模拟引擎** ✅：基于 10000 用户 × 336 时间片的全量模拟快照 API
2. **连接可视化** ✅：用户→基站连接线，信号质量三色着色（绿/黄/红），动态线宽
3. **密度热力图** ✅：流量加权用户密度热力图
4. **Handover 可视化** ✅：切换检测 + 弧线高亮动画
5. **用户图标渲染** ✅：SDF 像素绘制小人图标，信号强度着色
6. **用户弹窗** ✅：点击显示职业、运动状态、APP、信号、流量、Handover 状态
7. **基站时间序列** ✅：双轴图（用户数 + 流量），支持点击基站查看
8. **PRB 资源利用率** ✅：基站 PRB 占用率估算与显示
9. **APP 类别 emoji** ✅：19 类别 emoji 映射，弹窗 + 地图标签
10. **实时统计仪表盘** ✅：用户数/流量/Handover/基站数四格面板
11. **播放控制** ✅：0.5x / 1x / 2x / 4x 速度切换
12. **性能优化** ✅：后端 Gzip 压缩（86%体积减少）、预取缓存（5帧/容量50）
13. **本地部署** ✅：支持本地运行后端（无需远程服务器）

## 功能 (Capabilities)

### 新增功能
- `simulation-engine`: ✅ 模拟快照 API（/api/simulation/snapshot, info, station_locs, station_id_map, station_time_series）
- `connection-visualization`: ✅ 用户-基站连接线（信号着色 + 动态线宽 + LOD）
- `density-heatmap`: ✅ 流量加权密度热力图
- `handover-detection`: ✅ 切换检测 + 弧线动画
- `user-icon-rendering`: ✅ SDF 小人图标 + 信号着色 + 职业/APP 标签
- `user-popup`: ✅ 用户详情弹窗（职业/运动/APP/信号/流量/Handover）
- `station-time-series`: ✅ 基站双轴时间序列图
- `prb-utilization`: ✅ PRB 资源利用率显示
- `app-emoji-labels`: ✅ 19 类别 emoji 标识（弹窗 + 地图标签）
- `stats-dashboard`: ✅ 实时统计仪表盘
- `playback-control`: ✅ 播放速度控制（0.5x/1x/2x/4x）
- `gzip-compression`: ✅ 后端 Gzip 压缩中间件
- `prefetch-cache`: ✅ 快照预取缓存（5帧预取，50帧容量）

### 修改文件
- `server.py`: ✅ 新增模拟 API 端点 + Gzip 压缩中间件
- `data_manager.py`: ✅ 新增 get_simulation_snapshot()、get_station_time_series() 等方法
- `electron-client/src/script.js`: ✅ 模拟模式全部前端逻辑
- `electron-client/src/style.css`: ✅ 模拟模式 UI 样式
- `electron-client/src/index.html`: ✅ 模拟模式 HTML 结构
- `electron-client/main.js`: ✅ 生产环境关闭 DevTools

## 影响

- **后端**: 新增 6 个模拟 API 端点，Gzip 压缩（响应 2.4MB→357KB）
- **前端**: script.js 从 48KB 增长到 103KB，新增完整模拟可视化模块
- **性能**: 本地 E2E 延迟 ~0.19s（远程 ~1.54s），内存占用 ~3.3GB
- **部署**: 支持本地/远程双模式运行，本机 RTX 4060 + 32GB RAM 可流畅运行

## 未实现（明确排除）

- **Sankey 流量流向图**：用户→基站→核心网流向（需求文档提及但未实现）
- **网格聚合显示**：>1 万用户按网格聚合计数（热力图部分替代）
- **车/人移动模式区分**：数据仅有 move/stay，无 walking/driving 细分
- **微突发场景模拟**：演唱会 3D 场景、无人机调度（属第三阶段范畴）
