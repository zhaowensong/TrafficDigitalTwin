## ADDED Requirements

### 需求:DataManager类
系统必须提供 DataManager 类统一封装数据访问。

#### 场景:初始化DataManager
- **当** 应用启动时
- **那么** 必须创建 DataManager 实例
- **并且** 必须传入数据文件路径配置

#### 场景:保持现有缓存机制
- **当** DataManager 加载 NPZ 数据
- **那么** 必须保持现有的 NPZ_DATA_CACHE 缓存机制
- **并且** 避免重复加载大文件

### 需求:基站数据访问
DataManager 必须提供基站相关数据的访问接口。

#### 场景:获取基站列表
- **当** 调用 data_manager.get_station_list()
- **那么** 必须返回所有基站的基本信息（ID、名称、经纬度）
- **并且** 数据必须来自扩展后的 base2info.json

#### 场景:获取基站详情
- **当** 调用 data_manager.get_station_detail(station_id)
- **那么** 必须返回指定基站的完整信息（基础、天线、容量、状态、空间特征）
- **并且** 必须包含该基站在 bs_record 中的时序数据

#### 场景:获取基站统计数据
- **当** 调用 data_manager.get_station_stats(station_id)
- **那么** 必须返回该基站的统计值（均值、标准差）
- **并且** 计算应使用 NumPy 向量化操作

### 需求:用户数据访问
DataManager 必须提供用户数据的访问接口。

#### 场景:加载用户轨迹数据
- **当** 调用 data_manager.load_user_trajectories()
- **那么** 必须从 data/user_data/trajectories.json 加载用户轨迹
- **并且** 支持按需加载（分页或分片）

#### 场景:按区域查询用户
- **当** 调用 data_manager.get_users_in_area(center, radius)
- **那么** 必须返回指定区域内的所有用户
- **并且** 应使用空间索引提高效率

#### 场景:获取用户详情
- **当** 调用 data_manager.get_user_detail(user_id)
- **那么** 必须返回指定用户的完整信息（画像 + 轨迹摘要）

#### 场景:获取用户画像
- **当** 调用 data_manager.get_user_profile(user_id)
- **那么** 必须返回结构化画像和文本画像

#### 场景:查询基站连接用户
- **当** 调用 data_manager.get_users_by_station(station_id, time_range)
- **那么** 必须返回指定时段内连接该基站的所有用户

### 需求:数据加载错误处理
DataManager 必须统一处理数据加载错误。

#### 场景:数据文件不存在
- **当** 请求的数据文件不存在
- **那么** DataManager 必须抛出明确的异常
- **并且** 异常信息必须包含缺失的文件路径

#### 场景:数据格式错误
- **当** 加载的数据格式不正确
- **那么** DataManager 必须给出清晰的错误提示
- **并且** 不应导致整个应用崩溃

### 需求:扩展接口预留
DataManager 必须预留扩展接口，支持后续数据类型。

#### 场景:预留卫星图像接口
- **当** 后续需要接入卫星图像数据
- **那么** 必须通过 data_manager.get_satellite_image(station_id) 访问
- **并且** 当前可实现为返回空数据或模拟数据

#### 场景:预留POI数据接口
- **当** 后续需要接入POI数据
- **那么** 必须通过 data_manager.get_poi_data(station_id) 访问
- **并且** 当前可实现为返回空数据或模拟数据
