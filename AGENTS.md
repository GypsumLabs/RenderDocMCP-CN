# RenderDoc MCP 服务器（开发笔记）

作为 RenderDoc UI 扩展运行的 MCP 服务器。AI Agent 通过 MCP 访问 RenderDoc 的捕获数据，协助进行 DirectX 11 图形调试。

> 面向使用者的安装步骤、工具清单、参数含义与错误约定统一放在 [README.md](README.md)，本文件只记录开发与排查相关内容，避免两份文档各说一套。

## 架构

**混合进程分离方式**:

```
AI Agent (MCP 客户端, stdio)
        │
        ▼
MCP 服务器进程（标准 Python + FastMCP 2.0）
        │ 基于文件的 IPC (%TEMP%/renderdoc_mcp/)
        ▼
RenderDoc 进程（扩展 + 文件轮询）
```

扩展侧运行在 Qt UI 线程上，因此不使用 socket，而是用 `PySide2.QtCore.QTimer` 每 100ms 轮询请求文件。

## 项目结构

```
RenderDocMCP/
├── mcp_server/                        # MCP 服务器（标准 Python，Python 3.10+）
│   ├── server.py                      # FastMCP 入口点、工具定义
│   ├── config.py                      # 配置（超时相关环境变量）
│   └── bridge/
│       └── client.py                  # 基于文件的 IPC 客户端
│
├── renderdoc_extension/               # RenderDoc 扩展（仅 Python 3.6 标准库 + PySide2）
│   ├── __init__.py                    # register()/unregister()
│   ├── extension.json                 # 清单文件
│   ├── socket_server.py               # 基于文件的 IPC 服务器（文件名沿用历史命名，内部无 socket）
│   ├── request_handler.py             # 请求路由与参数校验
│   ├── renderdoc_facade.py            # RenderDoc API 门面，转发到各 service
│   ├── services/                      # 按功能拆分的服务
│   │   ├── capture_manager.py         # 捕获状态/列表/打开
│   │   ├── action_service.py          # DrawCall、帧摘要、GPU 时间
│   │   ├── search_service.py          # find_draws_by_* 反查
│   │   ├── resource_service.py        # 纹理/缓冲数据
│   │   └── pipeline_service.py        # 管线状态与着色器信息
│   └── utils/                         # 无状态工具类
│       ├── parsers.py                 # stage / ResourceId 解析
│       ├── serializers.py             # Action、变量序列化
│       └── helpers.py                 # 动作遍历、stage 列表
│
└── scripts/
    └── install_extension.py           # 扩展安装脚本（uninstall 参数可卸载）
```

## MCP 工具

工具清单与参数说明见 [README.md](README.md#mcp工具列表)，实现位于 `mcp_server/server.py`，两端路由表位于 `renderdoc_extension/request_handler.py`。新增工具时需要同时改这三处。

### get_draw_calls 过滤选项

```python
get_draw_calls(
    include_children=True,      # 包含子操作
    marker_filter="Camera.Render",  # 仅获取此标记下的内容
    exclude_markers=["GUI.Repaint", "UIR.DrawChain"],  # 排除的标记（连同其子树）
    event_id_min=7372,          # event_id 范围起点
    event_id_max=7600,          # event_id 范围终点
    only_actions=True,          # 排除标记（仅绘制调用）
    flags_filter=["Drawcall", "Dispatch"],  # 仅特定标志
)
```

## 通信协议

基于文件的 IPC：

- IPC 目录：`%TEMP%/renderdoc_mcp/`
- `request.json`：请求（MCP 服务器 → RenderDoc）
- `response.json`：响应（RenderDoc → MCP 服务器）
- `response.json.tmp`：响应临时文件，扩展写完 `fsync` 后原子重命名为 `response.json`
- `lock`：写入中锁文件（客户端写请求时创建，写完删除）
- 轮询间隔：100ms（RenderDoc 侧）

约定：

- 请求与响应都带 `id`，客户端会丢弃 `id` 不匹配的迟到响应，避免超时请求的响应污染下一次请求。
- 扩展侧只要发现 `request.json` 存在就必定消费（无论解析是否成功），否则解析失败会导致请求文件堆积、后续请求永久阻塞。

## 开发笔记

- RenderDoc 扩展仅使用 Python 3.6 标准库 + `PySide2`（扩展侧代码不要用 f-string、海象运算符等 3.7+ 语法）
- 通过 `BlockInvoke` 访问 `ReplayController`
- 管线状态与着色器信息按 RenderDoc 1.46 的 `PipeState` 接口实现，不兼容早期版本命名
- `get_pipeline_state` 中单个状态读取失败会写进 `errors` 字段，不要改回 `except: pass`
- 扩展侧的持续开销来自整帧反查（逐 DrawCall `SetFrameEvent` + 解析资源名），本来就慢，
  改动 `search_service` 时注意不要在每绘制路径上再加额外的 replay 调用，否则会成倍变慢

### 两个已踩过的坑（改动前务必确认）

1. **`BlockInvoke` 会吞掉回调内抛出的异常。**
   回调里抛异常时 `BlockInvoke` 直接返回，调用方只会拿到 `None`（例如 `stage` 非法时 `get_shader_info` 会静默返回 `null`）。
   因此所有 replay 回调都必须用 `Helpers.replay_call(self._invoke, result, callback)` 执行，
   由它把异常写进 `result["error"]`，再在回调外转成 `ValueError`。
2. **不要用 `rd.ResourceId()` 构造对象来比较资源。**
   构造后再赋 `id` 得到的对象与真实 `ResourceId` 不相等（等价于 Null），会让比较恒为假或匹配到所有未绑定的槽位
   （`find_draws_by_resource` 曾因此把"未绑定着色器的 stage"全部误判为命中，`get_buffer_contents` 则恒报 `Buffer not found`）。
   资源比较统一使用 `Parsers.same_resource(a, b)` 或 `Parsers.numeric_id(x)`。

### 改动扩展后的生效流程

扩展代码在 RenderDoc 启动时载入，运行中替换文件不会生效，因此改动 `renderdoc_extension/` 后必须：

1. 重新安装：`python scripts/install_extension.py`
   （逐文件覆盖到 `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`，`temp/` 下的截图会保留）
2. 重启 RenderDoc —— 仅重新打开捕获无效，已导入的模块会被缓存
3. 跑一遍冒烟测试确认没有回归（见下节）

> MCP 服务器侧（`mcp_server/`）改完不需要动 RenderDoc；但客户端有会话级的工具描述缓存，
> 改了工具描述要重连 MCP 才会生效。

### 冒烟测试

```bash
python scripts/smoke_test.py           # 全部工具 + 错误路径
python scripts/smoke_test.py --quick   # 跳过耗时反查
```

脚本绕过 MCP 客户端直接走 IPC，打印每个工具的耗时与结果摘要，失败项会在结尾汇总；
改动扩展后先跑一遍，比逐个人工调用 MCP 工具快得多。

### 已知待办

- 长耗时反查目前占用 Qt 定时器回调，期间 RenderDoc 界面无响应，后续需要分片让出事件循环。
- `get_texture_saved` 生成的 PNG 无清理策略。
- 提案文档 [renderdoc-mcp-improvement-proposal.md](renderdoc-mcp-improvement-proposal.md) 中仅剩批量管线状态、Unity 预设两项未实现。

## 参考链接

- [FastMCP](https://github.com/jlowin/fastmcp)
- [RenderDoc Python API](https://renderdoc.org/docs/python_api/index.html)
- [RenderDoc 扩展注册](https://renderdoc.org/docs/how/how_python_extension.html)
