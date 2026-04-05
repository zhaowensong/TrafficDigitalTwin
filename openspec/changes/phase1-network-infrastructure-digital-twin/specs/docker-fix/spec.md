## ADDED Requirements

### 需求:Docker端口修复
系统必须修复 Dockerfile 与 server.py 端口不一致的问题。

#### 场景:端口一致性
- **当** Dockerfile 暴露 7860 端口
- **那么** 应用启动后必须监听 7860 端口
- **并且** 容器必须能正常接收请求

### 需求:启动命令修复
Dockerfile 的 CMD 指令必须正确启动应用。

#### 场景:正确启动
- **当** 执行 docker run
- **那么** 应用必须在 7860 端口启动
- **并且** 必须监听 0.0.0.0（允许外部访问）

**方案1**: 修改 Dockerfile
```dockerfile
CMD ["python", "-c", "from server import app; app.run(host='0.0.0.0', port=7860)"]
```

**方案2**: 修改 server.py
```python
port = int(os.environ.get('PORT', 5000))
host = os.environ.get('HOST', '127.0.0.1')
app.run(host=host, port=port)
```

### 需求:Docker构建验证
修复后必须能成功构建和运行。

#### 场景:镜像构建
- **当** 执行 docker build
- **那么** 必须成功构建镜像
- **并且** 无错误信息

#### 场景:容器运行
- **当** 执行 docker run -p 7860:7860
- **那么** 容器必须正常启动
- **并且** 外部必须能通过 7860 端口访问

#### 场景:功能验证
- **当** 访问 http://localhost:7860
- **那么** 必须正常返回前端页面
- **并且** API 请求必须正常响应
