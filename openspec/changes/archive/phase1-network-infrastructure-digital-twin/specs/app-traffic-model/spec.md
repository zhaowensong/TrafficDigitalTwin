## ADDED Requirements

### 需求:视频类APP模型
系统必须定义视频类APP（抖音、B站等）的流量特征。

#### 场景:视频APP参数
- **当** 获取视频类APP模型
- **那么** 必须返回以下参数：
  - name: 字符串，APP名称（"video"）
  - description: 字符串，描述（"视频类APP：抖音、B站等"）
  - dl_ul_ratio: 数值，上下行比例（10:1）
  - burstiness: 字符串，突发性（"high"）
  - avg_bandwidth: 数值，平均带宽（7.5 Mbps）
  - min_bandwidth: 数值，最小带宽（5 Mbps）
  - max_bandwidth: 数值，最大带宽（10 Mbps）
  - latency_sensitive: 布尔值，是否延迟敏感（false）

### 需求:社交类APP模型
系统必须定义社交类APP（微信、微博等）的流量特征。

#### 场景:社交APP参数
- **当** 获取社交类APP模型
- **那么** 必须返回以下参数：
  - name: 字符串，APP名称（"social"）
  - description: 字符串，描述（"社交类APP：微信、微博等"）
  - dl_ul_ratio: 数值，上下行比例（1:1）
  - burstiness: 字符串，突发性（"medium"）
  - avg_bandwidth: 数值，平均带宽（1.25 Mbps）
  - min_bandwidth: 数值，最小带宽（0.5 Mbps）
  - max_bandwidth: 数值，最大带宽（2 Mbps）
  - latency_sensitive: 布尔值，是否延迟敏感（false）

### 需求:游戏类APP模型
系统必须定义游戏类APP（王者荣耀等）的流量特征。

#### 场景:游戏APP参数
- **当** 获取游戏类APP模型
- **那么** 必须返回以下参数：
  - name: 字符串，APP名称（"gaming"）
  - description: 字符串，描述（"游戏类APP：王者荣耀等"）
  - dl_ul_ratio: 数值，上下行比例（2:1）
  - burstiness: 字符串，突发性（"low"）
  - avg_bandwidth: 数值，平均带宽（2 Mbps）
  - min_bandwidth: 数值，最小带宽（1 Mbps）
  - max_bandwidth: 数值，最大带宽（3 Mbps）
  - latency_sensitive: 布尔值，是否延迟敏感（true）
  - max_latency: 数值，最大可接受延迟（50 ms）

### 需求:浏览类APP模型
系统必须定义浏览类APP（新闻、购物等）的流量特征。

#### 场景:浏览APP参数
- **当** 获取浏览类APP模型
- **那么** 必须返回以下参数：
  - name: 字符串，APP名称（"browsing"）
  - description: 字符串，描述（"浏览类APP：新闻、购物等"）
  - dl_ul_ratio: 数值，上下行比例（5:1）
  - burstiness: 字符串，突发性（"medium"）
  - avg_bandwidth: 数值，平均带宽（3.5 Mbps）
  - min_bandwidth: 数值，最小带宽（2 Mbps）
  - max_bandwidth: 数值，最大带宽（5 Mbps）
  - latency_sensitive: 布尔值，是否延迟敏感（false）

### 需求:APP流量生成
系统必须支持基于APP模型生成流量数据。

#### 场景:生成APP流量
- **当** 调用流量生成函数
- **那么** 必须根据APP类型返回合理的带宽需求
- **并且** 带宽值应在 min-max 范围内随机分布
- **并且** 游戏类APP必须满足延迟要求

### 需求:APP模型查询
系统必须支持查询所有APP模型。

#### 场景:获取所有APP类型
- **当** 请求所有APP模型
- **那么** 必须返回视频、社交、游戏、浏览四类APP的完整参数
