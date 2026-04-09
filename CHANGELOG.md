# 改动记录

## 项目启动 - 2026年3月

### 初始状态
拿到项目时，代码已包含基础功能但存在严重性能问题：
- 3D 可视化、AI 预测、能耗控制等功能已有雏形
- 服务器启动极慢（数分钟）
- 前端页面无法加载（卡在初始化）

---

## 改动详情

### 1. 修复服务器启动慢问题

**文件**: `server.py`

**问题**: 启动时加载 `bs_record` (5326×672) 大数组，转换耗时极长

**改动**:
- 修改 `load_and_process_data()` 函数，排除大型数组属性
- 添加 `npz_data` 参数，避免重复加载 NPZ 文件
- 大型数组改为按需从 `NPZ_DATA_CACHE` 读取
- 添加进度输出，方便查看加载状态

**效果**: 启动时间从数分钟缩短到 10-20 秒

---

### 2. 修复前端页面无法加载问题

**文件**: `server.py`

**问题**: `/api/stations/locations` 返回 350MB+ 数据，浏览器崩溃

**改动**:
- 修改 `get_station_locations()` 接口
- 移除 `vals` 字段（672 个时序值）
- 只返回统计值 `val_h`（均值）和 `val_c`（标准差）
- 使用 NumPy 向量化计算替代 Python 循环

**效果**: 响应大小从 ~350MB 减少到 ~200KB，页面正常加载

---

### 3. 优化统计计算

**文件**: `server.py`

**改动**:
- 修改 `calculate_stats()` 函数，传入 `npz_data` 参数
- 直接从 NPZ 数组计算均值和标准差
- 使用 `records.mean()` 和 `records.std()` 向量化操作

---

### 4. 添加辅助函数

**文件**: `server.py`

**新增**:
```python
def get_bs_record_for_station(item):
    """从 NPZ 缓存获取基站的 bs_record"""
    idx = item.get('npz_index', 0)
    if 'bs_record' in NPZ_DATA_CACHE and idx < NPZ_DATA_CACHE['bs_record'].shape[0]:
        return NPZ_DATA_CACHE['bs_record'][idx].tolist()
    return []
```

用于 `get_station_detail()` 按需获取时序数据

---

### 5. 移除敏感信息

**文件**: 
- `prediction_backend.py`
- `script.js`

**问题**: GitHub 推送时检测到 Mapbox Token，被阻止

**改动**:
```python
# prediction_backend.py
# 原代码:
MAPBOX_ACCESS_TOKEN = "pk.eyJ1IjoieXlhaXl5..."

# 改为:
MAPBOX_ACCESS_TOKEN = os.environ.get('MAPBOX_ACCESS_TOKEN', 'YOUR_MAPBOX_TOKEN_HERE')
```

```javascript
// script.js
// 原代码:
MAPBOX_TOKEN: 'pk.eyJ1IjoieXlhaXl5...',

// 改为:
MAPBOX_TOKEN: 'YOUR_MAPBOX_TOKEN_HERE',
```

---

### 6. 添加 .gitignore

**文件**: `.gitignore`

**内容**:
```
*.pt
*.npz
__pycache__/
*.pyc
.DS_Store
```

**原因**: 
- `best_corr_model.pt` (550MB) 超过 GitHub 100MB 限制
- `*.npz` 数据文件较大，不适合版本控制

---

### 7. 创建 README.md

**文件**: `README.md`

**内容**:
- 项目概述
- 初始代码状态
- 所有改动详细说明
- 当前架构
- 运行说明
- 缺失文件清单
- 完成度评估

---

## 改动统计

| 类型 | 数量 | 说明 |
|-----|------|------|
| 修改文件 | 3 | server.py, prediction_backend.py, script.js |
| 新增文件 | 2 | .gitignore, README.md |
| 新增函数 | 1 | get_bs_record_for_station() |
| 优化点 | 4 | 数据加载、API响应、统计计算、安全 |

---

## 当前状态

✅ **已完成**:
- 服务器正常启动（10-20秒）
- 前端页面正常加载
- API 响应正常（~200KB）
- 代码已推送到 GitHub
- Phase 1: 基站扩展 + 用户数据接入 + APP模型 + DataManager
- Phase 2: 模拟模式 + 连接可视化 + 密度热力图 + 基站用户数着色
- Phase 2: Handover 检测与弧线/高亮可视化
- Phase 2: PRB 资源利用率估算显示
- Phase 2: 双轴时间序列图（用户数+流量）
- Phase 2: 用户小人图标（SDF 像素绘制，信号着色）+ 职业标签
- Phase 2: 用户点击弹窗（职业、运动状态、APP名称+类别、Handover状态）
- Phase 2: 快照预取缓存 + 连接线动态线宽
- Phase 2: 后端 Gzip 压缩（API 响应 2.4MB→357KB，86%压缩率）
- Phase 2: APP 类别 emoji 标识（19 类别映射，弹窗+地图标签）
- Phase 2: Lines 图层渲染修复（minzoom/visibility/opacity 三重问题）
- Phase 2: 实时统计仪表盘（用户数/流量/Handover/基站数）
- Phase 2: 播放速度控制（0.5x/1x/2x/4x）
- Phase 2: 热力图配色升级 + 预取缓存扩大（2→5，容量 20→50）
- Phase 2: Electron 生产环境关闭 DevTools
- C/S 架构部署验证通过（SSH 隧道 + Electron）

⚠️ **待处理**:
- 需要手动上传模型文件 `best_corr_model.pt`
- 需要手动上传数据文件 `*.npz`
- 需要配置 Mapbox Token

---

## GitHub 仓库

https://github.com/zhaowensong/TrafficDigitalTwin.git
