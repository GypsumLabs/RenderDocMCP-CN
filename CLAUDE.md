# RenderDoc MCP 服务器

作为 RenderDoc UI 扩展运行的 MCP 服务器。AI 助手可以访问 RenderDoc 的捕获数据，协助进行 DirectX 11/12 图形调试。

## 架构

**混合进程分离方式**:

```
Claude/AI 客户端 (stdio)
        │
        ▼
MCP 服务器进程（标准 Python + FastMCP 2.0）
        │ 基于文件的 IPC (%TEMP%/renderdoc_mcp/)
        ▼
RenderDoc 进程（扩展 + 文件轮询）
```

## 项目结构

```
RenderDocMCP/
├── mcp_server/                        # MCP 服务器
│   ├── server.py                      # FastMCP 入口点
│   ├── config.py                      # 配置
│   └── bridge/
│       └── client.py                  # 基于文件的 IPC 客户端
│
├── renderdoc_extension/               # RenderDoc 扩展
│   ├── __init__.py                    # register()/unregister()
│   ├── extension.json                 # 清单文件
│   ├── socket_server.py               # 基于文件的 IPC 服务器
│   ├── request_handler.py             # 请求处理
│   └── renderdoc_facade.py            # RenderDoc API 包装器
│
└── scripts/
    └── install_extension.py           # 扩展安装脚本
```

## MCP 工具

| 工具名 | 说明 |
|---------|------|
| `list_captures` | 获取指定目录内的.rdc 文件列表 |
| `open_capture` | 打开捕获文件（自动关闭现有捕获） |
| `get_capture_status` | 检查捕获加载状态 |
| `get_draw_calls` | 获取绘制调用列表（支持层级结构和过滤） |
| `get_frame_summary` | 获取帧整体统计信息（绘制调用数、标记列表等） |
| `find_draws_by_shader` | 通过着色器名称反向搜索绘制调用 |
| `find_draws_by_texture` | 通过纹理名称反向搜索绘制调用 |
| `find_draws_by_resource` | 通过资源 ID 反向搜索绘制调用 |
| `get_draw_call_details` | 获取特定绘制调用的详细信息 |
| `get_action_timings` | 获取操作的 GPU 执行时间 |
| `get_shader_info` | 获取着色器源码/常量缓冲区 |
| `get_buffer_contents` | 获取缓冲区数据（支持偏移量/长度指定） |
| `get_texture_info` | 获取纹理元数据 |
| `get_texture_raw` | 获取纹理像素数据（支持 mip/slice/3D 切片） |
| `get_pipeline_state` | 获取完整管线状态 |

### get_draw_calls 过滤选项

```python
get_draw_calls(
    include_children=True,      # 包含子操作
    marker_filter="Camera.Render",  # 仅获取此标记下的内容
    exclude_markers=["GUI.Repaint", "UIR.DrawChain"],  # 排除的标记
    event_id_min=7372,          # event_id 范围起点
    event_id_max=7600,          # event_id 范围终点
    only_actions=True,          # 排除标记（仅绘制调用）
    flags_filter=["Drawcall", "Dispatch"],  # 仅特定标志
)
```

### 捕获管理工具

```python
# 列出目录内的捕获文件
list_captures(directory="D:\\captures")
# → {"count": 3, "captures": [{"filename": "game.rdc", "path": "...", "size_bytes": 12345, "modified_time": "..."}, ...]}

# 打开捕获文件（现有捕获会自动关闭）
open_capture(capture_path="D:\\captures\\game.rdc")
# → {"success": true, "filename": "game.rdc", "api": "D3D11"}
```

### 反向搜索工具

```python
# 按着色器名称搜索（部分匹配）
find_draws_by_shader(shader_name="Toon", stage="pixel")

# 按纹理名称搜索（部分匹配）
find_draws_by_texture(texture_name="CharacterSkin")

# 按资源 ID 搜索（完全匹配）
find_draws_by_resource(resource_id="ResourceId::12345")
```

### GPU 时间获取

```python
# 获取所有操作的时间
get_action_timings()
# → {"available": true, "unit": "CounterUnit.Seconds", "timings": [...], "total_duration_ms": 12.5, "count": 150}

# 仅获取特定事件 ID
get_action_timings(event_ids=[100, 200, 300])

# 按标记过滤
get_action_timings(marker_filter="Camera.Render", exclude_markers=["GUI.Repaint"])
```

**注意**: GPU 时间计数器在某些硬件/驱动程序上可能不可用。如果返回 `available: false`，表示该捕获无法获取时间信息。

## 通信协议

基于文件的 IPC：
- IPC 目录：%TEMP%/renderdoc_mcp/
- `request.json`: 请求（MCP 服务器 → RenderDoc）
- `response.json`: 响应（RenderDoc → MCP 服务器）
- `lock`: 写入中锁文件
- 轮询间隔：100ms（RenderDoc 侧）

## 开发笔记

- RenderDoc 内置 Python 没有 socket/QtNetwork 模块，因此采用基于文件的 IPC
- RenderDoc 扩展仅使用 Python 3.6 标准库
- 通过 `BlockInvoke` 访问 ReplayController

## 参考链接

- [FastMCP](https://github.com/jlowin/fastmcp)
- [RenderDoc Python API](https://renderdoc.org/docs/python_api/index.html)
- [RenderDoc 扩展注册](https://renderdoc.org/docs/how/how_python_extension.html)