# Traffic Digital Twin Platform - Phase 1

网络基础设施层数字孪生平台 - 第一阶段

## 项目概述

本项目是一个空间网络智能化管理平台，实现基站网络基础设施的数字孪生，具备数据可视化、AI 流量预测和能耗控制功能。

参考项目：https://huggingface.co/spaces/Karaku9/Traffic-Flow-Predictor

---

## 初始代码状态

从现有代码库开始，项目已包含以下基础功能：

### 已有功能
- **3D 可视化**：基于 Mapbox 的基站位置展示（3D 柱状图）
- **时序数据展示**：使用 Chart.js 展示流量时序曲线
- **AI 预测**：Hierarchical Flow Matching V4 模型进行流量预测
- **能耗控制**：基础能耗策略模拟
- **后端 API**：Flask 提供数据接口

### 原始代码结构
```
├── server.py                          # Flask 后端服务
├── prediction_backend.py              # AI 预测后端
├── hierarchical_flow_matching_v4.py   # 流匹配模型
├── multimodal_spatial_encoder_v4.py   # 多模态编码器
├── index.html                         # 前端页面
├── script.js                          # 前端交互逻辑
├── style.css                          # 样式文件
├── data/                              # 数据目录
│   ├── base2info.json                 # 基站位置信息
│   ├── bs_record_energy_normalized_sampled.npz  # 时序数据
│   └── spatial_features.npz           # 空间特征
└── best_corr_model.pt                 # 训练好的模型
```

---

## 主要改动记录

### 1. 性能优化 - 数据加载（server.py）

**问题**：
- 原始代码在启动时加载所有数据，包括 `bs_record` (5326×672) 大数组
- 数据转换耗时极长，服务器启动需要数分钟甚至更久

**改动**：
```python
# 优化前：加载所有属性，包括大型数组
def load_and_process_data(json_path, npz_path):
    # ... 加载所有属性，包括 bs_record 等大型数组
    for attr in station_attributes:
        val = npz_data[attr][i]
        entry[attr] = _convert_numpy_type(val)  # 耗时操作

# 优化后：只加载轻量级属性，大型数组按需读取
def load_and_process_data(json_path, npz_path, npz_data=None):
    # 排除大型数组属性
    excluded_attrs = {'bs_record', 'hours_in_weekday', ...}
    # 按需从 NPZ_DATA_CACHE 读取大型数组
```

**效果**：
- 服务器启动时间从数分钟缩短到 10-20 秒
- 内存占用显著降低

### 2. API 优化 - 减少响应大小（server.py）

**问题**：
- `/api/stations/locations` 返回所有站点的完整时序数据（5326 站点 × 672 时间步）
- 响应大小约 350MB，浏览器无法处理
- 页面一直显示 "SYSTEM INITIALIZING"

**改动**：
```python
# 优化前：返回完整时序数据
lightweight_data.append({
    "id": item['id'],
    "loc": item['loc'],
    "val_h": avg,
    "val_c": std,
    "vals": records  # 672 个值的数组
})

# 优化后：只返回统计值
lightweight_data.append({
    "id": item['id'],
    "loc": item['loc'],
    "val_h": avg,
    "val_c": std
    # 移除 vals，需要时从 NPZ_CACHE 读取
})
```

**效果**：
- 响应大小从 ~350MB 减少到 ~200KB
- 页面可以正常加载和交互

### 3. 统计计算优化（server.py）

**改动**：
```python
# 优化前：从内存列表计算
def calculate_stats(data_list):
    for item in data_list:
        records = item.get('bs_record', [])
        # ... 计算

# 优化后：直接从 NPZ 数据计算，使用向量化操作
def calculate_stats(npz_data, data_list):
    bs_record = npz_data.get('bs_record', None)
    for item in data_list:
        idx = item.get('npz_index', 0)
        records = bs_record[idx]
        avg = float(records.mean())  # NumPy 向量化
        std = float(records.std())
```

### 4. 安全修复 - 移除敏感信息

**问题**：
- 代码中包含 Mapbox Access Token
- GitHub 推送时被阻止（Secret Scanning）

**改动**：
```python
# prediction_backend.py
# 优化前：
MAPBOX_ACCESS_TOKEN = "pk.eyJ1IjoieXlhaXl5..."

# 优化后：
MAPBOX_ACCESS_TOKEN = os.environ.get('MAPBOX_ACCESS_TOKEN', 'YOUR_MAPBOX_TOKEN_HERE')
```

```javascript
// script.js
// 优化前：
MAPBOX_TOKEN: 'pk.eyJ1IjoieXlhaXl5...',

// 优化后：
MAPBOX_TOKEN: 'YOUR_MAPBOX_TOKEN_HERE', // Replace with your Mapbox token
```

### 5. Git 配置优化

**添加 .gitignore**：
```
*.pt          # 模型文件（约 550MB）
*.npz         # 数据文件（约 75MB）
__pycache__/  # Python 缓存
*.pyc
.DS_Store
```

**原因**：
- GitHub 单文件限制 100MB
- 模型和数据文件需要单独传输或使用 Git LFS

---

## 当前架构

### 数据流
```
基站数据 (NPZ) + 位置信息 (JSON)
    ↓
NPZ_DATA_CACHE (内存缓存)
    ↓
Flask API (按需读取大型数组)
    ↓
前端可视化 (Mapbox + Chart.js)
```

### API 接口
```
GET /api/stations/locations    # 获取所有基站位置和统计信息
GET /api/stations/detail/<id>  # 获取单个基站详情
GET /api/predict/<id>          # AI 预测未来流量
```

### 核心组件
1. **HierarchicalFlowMatchingSystemV4** - 核心预测模型
2. **MultiModalSpatialEncoder** - 多模态空间编码器
3. **MapboxSatelliteFetcher** - 卫星图像获取

---

## 运行说明

### 安装依赖
```bash
pip install -r requirements.txt
```

### 配置 Mapbox Token
```bash
# 方式1：环境变量
export MAPBOX_ACCESS_TOKEN="your_token_here"

# 方式2：修改代码
# 编辑 prediction_backend.py 和 script.js，替换 YOUR_MAPBOX_TOKEN_HERE
```

### 启动服务
```bash
python server.py
```

访问 http://127.0.0.1:5000

---

## 缺失文件说明

以下文件由于大小限制未包含在 Git 中，需要单独获取：

| 文件 | 大小 | 说明 |
|-----|------|------|
| `best_corr_model.pt` | ~550MB | 训练好的 AI 模型 |
| `data/bs_record_energy_normalized_sampled.npz` | ~71MB | 基站时序数据 |
| `data/spatial_features.npz` | ~287KB | 空间特征数据 |

---

## 第一阶段完成度

| 功能模块 | 完成度 | 说明 |
|---------|-------|------|
| 数据层 | 90% | 已优化加载性能 |
| 3D 可视化 | 85% | 基础功能完成 |
| AI 预测 | 80% | 模型已集成 |
| 能耗控制 | 70% | 基础策略模拟 |
| 基站实体建模 | 待开发 | 需补充物理属性、容量模型 |
| API 标准化 | 80% | 接口已优化 |

---

## 后续开发计划

### 第一阶段剩余工作
1. 基站实体属性建模（海拔、天线参数、KPI）
2. 完善 API 错误处理和文档
3. 预留用户实体和移动模型接口

### 第二阶段预览
1. 用户层级模拟（location, app, traffic）
2. 用户与基站交互可视化
3. 步行/驾驶两种移动模式
4. 微突发场景模拟

---

## 技术栈

- **后端**：Python + Flask + PyTorch
- **前端**：HTML5 + JavaScript + Mapbox GL JS + Chart.js
- **数据**：NumPy + JSON
- **模型**：Hierarchical Flow Matching V4

---

## 开发者

- 原始代码：项目团队
- 优化改动：AI Coding with Qoder
