# 第一阶段交付物验证指南

> 本文档列出所有已完成的功能，附带验证步骤，方便逐一检查效果。

## 前置条件

```
# 1. 启动 SSH 隧道（新终端窗口，保持运行）
ssh -L 7860:localhost:7860 cluster-4090 -N

# 2. 启动 Electron 客户端
cd c:\HKUPRJ\Source\Source\electron-client
npx electron .

# 3. 或在浏览器中直接访问 API
# 基地址: http://127.0.0.1:7860
```

---

## 一、基站实体属性扩展

### 1.1 扩展后的基站数据
**文件**: `Source/data/base2info_extended.json`  
**内容**: 5326 个基站，每个含 10 个属性字段

**验证**: 浏览器访问 → `http://127.0.0.1:7860/api/stations/detail/0`

应看到如下结构（关注扩展字段）:
```json
{
  "id": 0,
  "loc": [121.xxxx, 31.xxxx],
  "stats": { "avg": ..., "std": ... },
  "bs_record": [...],
  "antenna": { "azimuth": 120, "tilt": 6, "power_dbm": 43 },
  "capacity": { "max_prb": 100, "max_users": 200, "throughput_curve": [...] },
  "status_monitoring": { "load_percent": 45, "alarm_level": "normal", "kpi": {...} },
  "spatial": { "satellite_features": [...], "poi_features": [...] }
}
```

### 1.2 基站总览
**验证**: → `http://127.0.0.1:7860/api/stations/locations`

应返回:
- `stations`: 5326 个基站的位置+负载数据
- `stats_height`: 负载统计范围
- `stats_color`: 波动性分级阈值

---

## 二、用户实体数据接入

### 2.1 用户全局统计
**验证**: → `http://127.0.0.1:7860/api/users/stats`

期望结果:
```json
{
  "loaded": true,
  "total_users": 10000,
  "total_trajectories": 3360000,
  "users_with_trajectories": 10000,
  "roles": {
    "service_worker": 3738,
    "office_worker": 1788,
    "student": 1423,
    "factory_worker": 1385,
    "freelancer": 1014,
    "healthcare_worker": 652
  }
}
```

### 2.2 职业分布
**验证**: → `http://127.0.0.1:7860/api/users/roles`

返回 6 种职业及各自人数。

### 2.3 用户列表（分页+筛选）
**验证**:
- 全部用户第1页: → `http://127.0.0.1:7860/api/users/list?page=1&page_size=10`
- 按职业筛选: → `http://127.0.0.1:7860/api/users/list?role=student&page=1`
- 按基站筛选: → `http://127.0.0.1:7860/api/users/list?base_id=100&page=1`

### 2.4 单用户详情
**验证**: → `http://127.0.0.1:7860/api/users/user_0001`

应返回:
- `user_id`, `role`, `age_band`, `usage_intensity`
- `trajectory_count`: 336 条轨迹记录
- `app_summary`: APP使用分类统计

### 2.5 用户轨迹数据
**验证**: → `http://127.0.0.1:7860/api/users/user_0001/trajectory?limit=5`

每条轨迹记录为 14 字段数组:
```
[timestamp, base_id, longitude, latitude, app_category, app_name, 
 duration_min, traffic_mb, signal_rsrp, signal_sinr, 
 connection_type, speed_kmh, direction_deg, is_indoor]
```

### 2.6 用户文本画像
**验证**: → `http://127.0.0.1:7860/api/users/user_0001/profile_text`

返回该用户的英文文本画像描述。

### 2.7 基站关联用户
**验证**: → `http://127.0.0.1:7860/api/users/by_base/100`

返回连接到基站 #100 的用户列表（含 user_id, role, age_band）。

---

## 三、APP 分类流量模型

### 3.1 四大流量模型定义
**验证**: → `http://127.0.0.1:7860/api/app_models`

返回 4 个模型:

| 模型 | 带宽 | 方向 | 延迟敏感 | 包含APP类别 |
|------|------|------|----------|------------|
| **video** (视频流媒体) | 5-10 Mbps | 下行95% | 低 | Photo&Video, Entertainment, Music |
| **social** (社交通信) | 0.5-2 Mbps | 均衡60% | 中 | Social Networking, Lifestyle, Infant&Mom |
| **gaming** (在线游戏) | 1-3 Mbps | 均衡55% | **高** | Games, Sports |
| **browsing** (网页浏览) | 2-5 Mbps | 下行85% | 中 | News, Shopping, Education 等12类 |

### 3.2 APP类别映射
**验证**: → `http://127.0.0.1:7860/api/app_models/categories`

返回 20 个 APP 类别 → 流量模式的完整映射表。

---

## 四、数据访问层 (DataManager)

**文件**: `Source/data_manager.py` (428行)

核心能力:
- 基站数据: NPZ + JSON 合并加载, 5326 站点匹配
- 用户数据: 全量加载 10000 画像 + 336万轨迹到内存
- 索引: 按职业(`user_roles`)、按基站(`base_to_users`)快速查询
- 错误处理: 数据缺失时优雅降级，不阻塞服务启动

**验证**: 服务启动日志应显示:
```
[DataManager] Stations loaded: 5326/5326 matched in ~6s
[DataManager] Profiles loaded: 10000 users in ~0.1s
[DataManager] Trajectories loaded: 10000 users, 3360000 records in ~10s
```

---

## 五、Electron 桌面客户端

### 5.1 基础地图
**验证**: 启动后应看到上海卫星地图 + 基站热力图

### 5.2 3D/2D 视图切换
**验证**: 点击左上 `👁️ View: 3D` 按钮，切换俯视/3D视角

### 5.3 时间轴回放
**验证**: 3D模式下，底部时间条拖动或点击 ▶ 播放，柱状图随时间变化

### 5.4 基站点击详情
**验证**: 地图上点击任意基站 → 左侧面板显示:
- Station ID
- 经纬度
- 平均负载 + 稳定性
- 流量时序图

### 5.5 基站搜索
**验证**: 左上搜索框输入基站ID（如 `100`），点 GO → 飞到该基站

### 5.6 波动性过滤
**验证**: 点击 `🌪️ Filter Volatility` → 选择 Level 5 等级 → 只显示高波动基站

### 5.7 服务器配置
**验证**: 点击左上 ⚙️ 按钮 → 弹出配置窗口:
- Host: 127.0.0.1 | Port: 7860 | Protocol: http
- 点 Test Connection → 应显示 "✓ Connection successful!"

### 5.8 AI 预测模式
**验证**: 切到 2D 视图 → 点击 `🔮 Prediction Mode` → 点击基站
- 右侧弹出预测面板
- ⚠️ 当前 model.pt 未上传，会显示 "Prediction failed"（预期行为）

### 5.9 能量控制模式
**验证**: 类似预测模式，点击 `🔋 Energy Control` → 同样需要模型文件

---

## 六、👤 用户分析面板（新增）

### 6.1 打开面板
**验证**: 点击顶部紫色 `👤 Users` 按钮 → 右侧滑出用户分析面板

### 6.2 概览统计
面板顶部显示 4 个数字卡片:
- Total Users: **10,000**
- Trajectories: **3.4M**
- Role Types: **6**
- With Trajectory: **10,000**

### 6.3 职业分布条形图
6 种职业的水平条形图（彩色），按数量降序排列

### 6.4 站点关联用户
**验证**: 保持 Users 面板打开 → 点击地图上的基站 → 面板中出现:
- "📡 Station Users" 区域
- 该基站关联的用户列表（user_id + 职业标签）

### 6.5 用户详情
**验证**: 在用户列表中点击任意用户 → 面板下方显示:
- User ID
- Role（彩色标签）
- Trajectory 记录数
- APP USAGE 分类统计标签

### 6.6 轨迹可视化
**验证**: 用户详情下方点击 `🗺️ Show Trajectory on Map` 按钮:
- 地图上绘制紫色虚线轨迹
- 绿色圆点 = 起点，红色圆点 = 终点
- 地图自动缩放适配轨迹范围

### 6.7 APP 流量模型卡片
面板底部显示 4 张流量模型卡片:
- Video Streaming（粉色）
- Social & Messaging（蓝色）
- Online Gaming（黄色）
- Web Browsing（青色）
- 每张含带宽、下行比、延迟敏感度、包含APP类别

---

## 七、服务器部署

### 7.1 4090 GPU 服务器
- 地址: `147.8.181.249` (通过 SSH 隧道访问)
- 路径: `/mnt/Data/visitor/TrafficDigitalTwin`
- 环境: Python venv + PyTorch 2.6.0+cu124 (4x RTX 4090)
- 服务: Flask on port 7860, HOST=0.0.0.0

### 7.2 用户数据
- 路径: `/mnt/Data/visitor/user_data_shanghai_v1/`
- trajectories.json: 510MB ✓
- user_profiles_en.json: 8.6MB ✓
- profiles_txt/: 10000 文件 ✓

### 7.3 SSH 连接验证
```powershell
# 测试连接
ssh cluster-4090 "echo 'Connected!'"

# 查看服务日志
ssh cluster-4090 "tail -20 /mnt/Data/visitor/TrafficDigitalTwin/server.log"

# 测试 API
ssh cluster-4090 "curl -s http://localhost:7860/api/users/stats"
```

---

## 八、代码文件清单

| 文件 | 描述 | 行数 |
|------|------|------|
| `server.py` | Flask 后端主程序（重构） | ~258 |
| `data_manager.py` | 统一数据访问层（新建） | ~428 |
| `app_models.py` | APP 流量分类模型（新建） | ~182 |
| `electron-client/main.js` | Electron 主进程 | ~77 |
| `electron-client/src/script.js` | 前端逻辑（含用户面板） | ~1520 |
| `electron-client/src/index.html` | 前端 HTML（含用户面板） | ~270 |
| `electron-client/src/style.css` | 前端样式（含用户面板） | ~900 |

---

## 未完成项

| 任务 | 原因 |
|------|------|
| 5.4-5.6 Docker 测试 | 直接用 venv 部署，Docker 优先级低 |
| AI 预测功能 | `best_corr_model.pt` (537MB) 未上传到服务器 |
