## 1. 基站实体属性扩展 (base-station-modeling)

- [x] 1.1 设计扩展后的基站 JSON 结构
- [x] 1.2 创建脚本扩展 base2info.json，添加天线参数（方位角、下倾角、功率）
- [x] 1.3 添加容量模型（PRB资源池、最大用户数、吞吐量曲线）
- [x] 1.4 添加状态监控（实时负载、告警、KPI：RSRP/SINR/丢包率）
- [x] 1.5 添加空间特征（卫星图像特征、POI特征，用假数据填充）
- [x] 1.6 验证扩展后的数据格式正确

## 2. 用户实体数据接入 (user-entity-modeling)

- [ ] 2.1 解压 user_data_shanghai_v1.zip 到 data/user_data/ 目录
- [ ] 2.2 分析 trajectories.json 数据结构和字段
- [ ] 2.3 分析 user_profiles_en.json 画像数据结构
- [ ] 2.4 验证用户轨迹中的基站ID与 base2info_extended.json 匹配
- [ ] 2.5 测试数据加载性能（~100MB JSON）
- [ ] 2.6 如需优化，实现分批加载或索引机制

## 3. APP分类模型 (app-traffic-model)

- [ ] 3.1 分析用户数据中的 APP 使用记录，提取分类特征
- [ ] 3.2 创建 app_models.py 定义APP分类模型
- [ ] 3.3 定义视频类APP模型（抖音、B站）：下行突发、5-10Mbps
- [ ] 3.4 定义社交类APP模型（微信、微博）：上下均衡、0.5-2Mbps
- [ ] 3.5 定义游戏类APP模型（王者荣耀）：低延迟、1-3Mbps
- [ ] 3.6 定义浏览类APP模型（新闻、购物）：下行中等、2-5Mbps
- [ ] 3.7 实现APP流量统计与分类函数

## 4. 数据访问层 (data-access-layer)

- [ ] 4.1 创建 data_manager.py DataManager 类
- [ ] 4.2 实现基站数据加载接口（保持现有 NPZ_DATA_CACHE）
- [ ] 4.3 实现扩展基站属性访问接口
- [ ] 4.4 实现用户轨迹数据加载接口
- [ ] 4.5 实现用户画像数据加载接口（结构化 + 文本）
- [ ] 4.6 实现用户查询接口（按区域、按ID、按基站）
- [ ] 4.7 添加数据加载错误处理
- [ ] 4.8 重构 server.py 使用 DataManager
- [ ] 4.9 新增用户数据相关 API 端点

## 5. Docker部署修复 (docker-deployment)

- [x] 5.1 修改 Dockerfile 启动命令，使用 7860 端口
- [x] 5.2 修改 server.py 支持环境变量配置端口
- [x] 5.3 创建 docker-compose.yml
- [ ] 5.4 测试 Docker 镜像构建
- [ ] 5.5 测试 Docker 容器运行
- [ ] 5.6 验证容器内数据访问正常

## 6. Electron桌面客户端 (electron-desktop-client)

- [x] 6.1 创建 Electron 项目结构
- [x] 6.2 复制前端代码（index.html, script.js, style.css）到 Electron 项目
- [x] 6.3 修改 script.js 的 API_BASE 支持远程服务器配置
- [x] 6.4 创建主进程 main.js，加载本地前端页面
- [x] 6.5 配置 package.json，添加 Electron 依赖和打包脚本
- [x] 6.6 实现服务器地址配置界面（齿轮按钮 + 设置弹窗）
- [x] 6.7 测试 Electron 应用连接本地后端
- [ ] 6.8 测试 Electron 应用连接远程后端（需后端部署到服务器后验证）
- [x] 6.9 打包生成 Windows exe 便携版
- [x] 6.10 验证桌面客户端在本地正常运行

## 7. 集成验证与文档

- [ ] 7.1 验证所有现有 API 正常工作
- [ ] 7.2 验证扩展后的基站数据可正常访问
- [ ] 7.3 验证用户轨迹数据可通过API访问
- [ ] 7.4 验证用户画像数据可通过API访问
- [ ] 7.5 验证 C/S 架构部署（服务器后端 + 桌面客户端）
- [ ] 7.6 提交代码到 GitHub（解决 Mapbox Token 和大文件问题）
