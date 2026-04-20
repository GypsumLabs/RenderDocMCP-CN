# RenderDoc MCP Server

作为RenderDoc UI扩展功能运行的MCP服务器。AI助手可以访问RenderDoc的捕获数据，协助图形调试。

## 架构

```
Claude/AI Client (stdio)
        │
        ▼
MCP Server Process (Python + FastMCP 2.0)
        │ File-based IPC (%TEMP%/renderdoc_mcp/)
        ▼
RenderDoc Process (Extension)
```

由于RenderDoc内置的Python没有socket模块,因此使用基于文件的IPC进行通信。

## 安装配置

### 1. 安装RenderDoc扩展

```bash
python scripts/install_extension.py
```

扩展将安装到 `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`。

### 2. 在RenderDoc中启用扩展

1. 启动RenderDoc  

2. Tools > Manage Extensions  
<img src="images/Snipaste_2026-04-20_10-58-18.jpg" width="240">

3. 启用 "RenderDoc MCP Bridge"  
<img src="images/Snipaste_2026-04-20_11-01-23.jpg" width="400">

### 3. 安装MCP服务器

```bash
uv tool install
uv tool install --editable . # 编辑模式
uv tool update-shell  # 添加到PATH
```

重启Shell后即可使用 `renderdoc-mcp` 命令。

> **注意**: 添加 `--editable` 参数后,源代码的修改会立即生效(开发时很方便)。
> 如需安装稳定版,请使用 `uv tool install .`。

### 4. 配置MCP客户端

#### Claude Desktop

在 `claude_desktop_config.json` 中添加:

```json
{
  "mcpServers": {
    "renderdoc": {
      "command": "renderdoc-mcp"
    }
  }
}
```

#### Claude Code

在 `.mcp.json` 中添加:

```json
{
  "mcpServers": {
    "renderdoc": {
      "command": "renderdoc-mcp"
    }
  }
}
```

## 使用方法

1. 启动RenderDoc,打开捕获文件 (.rdc)
2. 从MCP客户端 (Claude等) 访问RenderDoc的数据

## MCP工具列表

| 工具 | 说明 |
|--------|------|
| `get_capture_status` | 检查捕获的加载状态 |
| `get_draw_calls` | 获取DrawCall列表的层级结构 |
| `get_draw_call_details` | 获取特定DrawCall的详细信息 |
| `get_shader_info` | 获取着色器源代码和常量缓冲区的值 |
| `get_buffer_contents` | 获取缓冲区内容 (Base64) |
| `get_texture_info` | 获取纹理的元数据 |
| `get_texture_raw` | 获取纹理的原始像素数据 (Base64，大纹理可能超限) |
| `get_texture_saved` | 将纹理保存为PNG文件并返回文件路径（推荐） |
| `get_pipeline_state` | 获取管线状态 |

## 使用示例

### 获取DrawCall列表

```
get_draw_calls(include_children=true)
```

### 获取着色器信息

```
get_shader_info(event_id=123, stage="pixel")
```

### 获取管线状态

```
get_pipeline_state(event_id=123)
```

### 获取纹理数据

```
# 推荐：保存为PNG文件（避免MCP大小限制）
get_texture_saved(resource_id="ResourceId::123")
# 返回: {"file_path": "...", "file_url": "file:///...", "width": 1920, "height": 1080, ...}

# 获取特定的mip级别
get_texture_saved(resource_id="ResourceId::123", mip=2)

# 获取立方体贴图的特定面 (0=X+, 1=X-, 2=Y+, 3=Y-, 4=Z+, 5=Z-)
get_texture_saved(resource_id="ResourceId::456", slice=3)

# 获取3D纹理的特定深度切片
get_texture_saved(resource_id="ResourceId::789", depth_slice=5)

# 原始Base64数据（仅适用于小纹理，大纹理会超过MCP 5MB限制）
get_texture_raw(resource_id="ResourceId::123", mip=2)
```

### 部分获取缓冲区数据

```
# 获取整个缓冲区
get_buffer_contents(resource_id="ResourceId::123")

# 从偏移256处获取512字节
get_buffer_contents(resource_id="ResourceId::123", offset=256, length=512)
```

## 系统要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- RenderDoc 1.20+

> **注意**: 仅在Windows + DirectX 11环境下进行过测试。
> Linux/macOS + Vulkan/OpenGL环境可能也能运行,但未经验证。

## 许可证

MIT
