# RenderDoc MCP 工具速查

MCP 服务器名 `renderdoc`，共 18 个工具。**所有调用必须串行**（扩展侧单请求通道）。

## 捕获管理

### `ping`
无参数。返回 `{"alive": bool, "ipc_dir": str}`。

只表示"扩展进程正在轮询请求文件"，**不代表已经加载了捕获**。其它工具首次调用前会自动做同样的探测（5 秒超时），所以这个工具主要用于人工排查连接问题。

### `get_capture_status`
无参数。未加载时只有 `{"loaded": false}`；已加载时含 `{"loaded": true, "api": "GraphicsAPI.D3D11", "filename": "完整路径"}`。

未加载捕获时其余工具都会报 `No capture loaded`。`filename` 是完整路径而不是文件名。

### `list_captures(directory)`
`directory`：要搜索的目录（绝对路径）。返回 `{"directory", "count", "captures": [{filename, path, size_bytes, modified_time}]}`。

目录不存在会报错；只匹配 `.rdc`，**不递归子目录**；按修改时间倒序。只是列文件，不加载捕获。

### `open_capture(capture_path)`
`capture_path`：`.rdc` 绝对路径。返回 `{"success", "capture_path", "filename", "api"?}`。

**会关闭当前已加载的捕获**，调用前需用户确认。大捕获加载可能数十秒，期间扩展无法响应任何请求，**调用后不要紧接着发其它请求**。`api` 字段可能缺失，用 `get_capture_status` 复查更可靠。

## 动作与绘制

### `get_frame_summary`
无参数。返回 `api`、`total_actions`、`statistics{draw_calls, dispatches, clears, copies, presents, markers}`、`top_level_markers[{name, event_id, child_count}]`、`resource_counts{textures, buffers}`。

- `statistics.markers` 只统计 PushMarker 与 SetMarker（一组 Push/Pop 记 1 个），PopMarker 不计入。
- `top_level_markers` 只列顶层标记；`child_count` 是该标记的全部后代数（含 Clear/Copy，不等于绘制数）。
- `resource_counts` 是整个捕获的资源总数，不是本帧实际使用量。
- 这里拿不到资源的 `resource_id`，需要时从 `get_pipeline_state` 取。

### `get_draw_calls(...)`
返回 `{"actions": [{event_id, action_id, name, flags, num_indices, num_instances, children?}], "error"}`。

参数与行为：

| 参数 | 默认 | 说明 |
|---|---|---|
| `include_children` | `true` | **传 `false` 会把所有标记一并丢掉**（标记只在"有子动作通过过滤"时才被保留，不再递归就没有子动作），结果退化成平铺的动作列表，Pass 结构完全消失 |
| `marker_filter` | 无 | 只保留名字包含该字符串的 PushMarker 之下的动作（部分匹配） |
| `exclude_markers` | 无 | 丢弃名字包含列表项的标记**连同其整棵子树** |
| `event_id_min` / `event_id_max` | 无 | 只对非标记动作生效；为维持层级，标记无论是否在范围内都会保留 |
| `only_actions` | `false` | 剔除标记动作，其子动作会被提升到上一层 |
| `flags_filter` | 无 | 只保留 flags 包含其中任意一项的动作。**区分大小写且必须与返回的字符串完全一致**（如 `["Drawcall", "Dispatch"]`），写错不报错、只返回空数组 |

**已知陷阱：不要用标记自身的 `event_id` 设 `event_id_min` / `event_id_max`。**
实测某帧中标记 "Compute Pass #5" 的 `event_id` 是 6968，而它的子动作 `event_id` 是 4401/4416/4450——标记的事件号落在其子动作范围**之外**。用标记事件号当范围起点会把所有绘制过滤掉，标记又因为没有子动作而被丢弃，最终返回空数组。要按 Pass 取内容，一律用 `marker_filter`。

本工具无需逐个回放，响应很快。不加限制地取整帧结果很大，建议配合 `marker_filter` / `only_actions` 缩小。

### `get_draw_call_details(event_id)`
返回 `event_id`、`action_id`、`name`、`flags`、`num_indices`、`num_instances`、`base_vertex`、`vertex_offset`、`instance_offset`、`index_offset`、`outputs[{index, resource_id}]`、`depth_output?`。

- **`event_id` 必须是真实动作**（绘制/Dispatch 等）。传标记的 event_id 或任意事件会报 `No action at event N`。
- 非实例化绘制的 `num_instances` 可能是 `0`，不要直接当成实例数，结合 `name` 判断。
- `outputs` 只有资源 ID，需要名称/尺寸再调 `get_texture_info`。

### `get_action_timings(event_ids?, marker_filter?, exclude_markers?)`
返回 `available`、`unit`、`timings[{event_id, name, duration_seconds, duration_ms}]`、`total_duration_ms`、`count`。

- 硬件/驱动不提供 GPU 时间计数器时返回 `available: false`，**不要当成"耗时为 0"**。
- `total_duration_ms` 是本次返回项之和（GPU 忙时累加），**不是帧时间**；加了过滤会相应变小。
- 单位由 `unit` 给出，通常是秒。
- 过滤语义是"标记路径包含"（与 `get_draw_calls` 不同），路径不匹配时仍会递归子节点，所以嵌套在更内层标记里的动作不会漏。
- 没有计时数据的事件会被静默跳过，`count` 可能小于 `event_ids` 长度。
- **全帧扫描，单独调用。**
- **同一事件两次读取的耗时会抖动**（实测同一个 Dispatch 分别为 2.615ms 与 2.141ms），只用于判断量级和相对占比。

## 反查（全帧扫描，慢，必须单独调用）

四个工具返回结构一致：`{"matches": [{event_id, name, match_reason}], "total_matches", "scanned_draws}`。
`match_reason` 形如 `"ShaderStage.Pixel SRV: 'CharacterSkin'"`。搜不到时返回空 `matches` 而不报错，`scanned_draws` 可确认是否真的扫过整帧。

### `find_draws_by_shader(shader_name, stage?)`
匹配的是**着色器入口点名或着色器资源名**。入口点通常都叫 `main`，传 `"main"` 会命中几乎全部绘制，请用足够具体的关键词。不填 `stage` 时遍历全部 6 个 stage（更慢），且 D3D11 下很多绘制事件仍绑着计算着色器，会让结果偏多。

### `find_draws_by_texture(texture_name)`
范围是 SRV、UAV 以及渲染目标；**不覆盖顶点/索引缓冲与常量缓冲**。查的是实际绑定的资源，不是 `get_shader_info` 里的反射声明。

### `find_draws_by_mesh(mesh_name)`
按顶点/索引缓冲名匹配。是**"绑定即命中"**——只要缓冲绑在管线上就算命中，不代表这次绘制真的用了它（被剔除的实例仍会绑定）。只覆盖顶点/索引缓冲。

### `find_draws_by_resource(resource_id)`
按资源 ID **精确**匹配，范围含着色器、SRV、UAV、渲染目标、深度目标。`"ResourceId::123"` 或 `"123"` 均可。

需要先知道 ID —— 工具集**没有资源清单接口**，ID 只能从 `get_pipeline_state` 的 `shaders[*].resources` / `uavs` / `render_targets` / `depth_target` 里取。ID 格式非法会直接报错，ID 不存在则返回空 matches，两者表现不同。

## 资源读取

### `get_texture_info(resource_id)`
返回 `resource_id`、`width`、`height`、`depth`、`array_size`、`mip_levels`、`format`、`dimension`、`msaa_samples`、`byte_size`。

- 格式非法报 `Invalid resource ID`；资源不存在或传的是缓冲区 ID 都报 `Texture not found`。
- `width` / `height` 是第 0 级 mip 的尺寸。
- `byte_size` 是**整张纹理**（含全部 mip 与数组层）的字节数。
- 读像素前先用它确认 `mip_levels` 与 `msaa_samples`，避免越界。

### `get_texture_saved(resource_id, mip?, slice?, sample?, depth_slice?)`
保存为 PNG，返回元数据 + `file_path`、`file_url`、`file_size`、`filename`。

- 文件写到**扩展安装目录的 `temp/` 子目录**，不会自动清理；重装扩展时会保留。
- `file_url` 可直接在浏览器打开。
- `slice`：数组层或立方体面（0=X+, 1=X-, 2=Y+, 3=Y-, 4=Z-, 5=Z-）。`depth_slice` 仅 3D 纹理有效。
- 大纹理首选本工具。

### `get_texture_raw(...)`
参数同上，返回元数据 + `content_base64`。**仅适合小纹理**，Base64 放大约 1/3。越界的 `mip` / `slice` / `sample` / `depth_slice` 都会给出明确的越界错误，可按错误信息修正。

### `get_buffer_contents(resource_id, offset?, length?)`
`length` 为 `0` 表示读到末尾。返回 `resource_id`、`length`（实际读到）、`total_size`、`offset`、`content_base64`。

- **只接受缓冲区**，传纹理 ID 报 `Buffer not found`。
- 工具集没有缓冲区清单：从 `get_pipeline_state` 的 `uavs` / `resources` 里挑 `type == "buffer"` 的项，其 `length` 字段就是缓冲区大小。
- 大缓冲用 `offset` + `length` 分段读；`offset + length` 超出不会自动裁剪，先确认 `total_size`。

## 管线与着色器

### `get_pipeline_state(event_id, include_cbuffer_variables=true)`
返回 `api`、`shaders{stage: {resource_id, entry_point, resources[], uavs[], samplers[], constant_buffers[]}}`、`viewport_scissors`、`render_targets[]`、`depth_target`、`input_assembly`、`blend`、`depth_stencil`、`errors?`。

- **响应通常很大，强烈建议传 `include_cbuffer_variables: false`**。常量缓冲可能含数百个变量、名字多是无意义编号（`cb0_v1`），只关心槽位/大小时无需变量值。
- `shaders` 只列真正绑定了着色器的 stage。D3D11 下即使是绘制事件，计算着色器往往仍绑着，所以会同时出现 `ShaderStage.Compute` —— 这是正常现象，**不代表该事件真的执行了计算**。
- 某个状态块读取失败会写进 `errors`（键为状态名，如 `errors.blend`），其余状态照常返回，不会让整个调用失败。解读前先看有没有 `errors`。
- `viewport_scissors` 最多各返回 16 项，超出的被丢弃。
- **获取 `resource_id` 的主要来源**：`resources`、`uavs`、`render_targets`、`depth_target` 都带 `resource_id`；`resources[].name` 来自着色器反射（如 `BlitTexture`），不是资源名，唯一标识只有 ID。

### `get_shader_info(event_id, stage, cbuffer_slots?, max_variables=64, include_disassembly=true)`
`stage` 必填，取 `vertex` / `hull` / `domain` / `geometry` / `pixel` / `compute`。
返回 `resource_id`、`entry_point`、`stage`、`disassembly`（失败时为 `disassembly_error`）、`constant_buffers[{name, slot, size, variables[], skipped?, truncated?, error?}]`、`resources[]`。

- **`cbuffer_slots` 用的是反射索引（从 0 开始）**，与返回里的 `slot` 字段一致。
- 被 `cbuffer_slots` 排除的常量缓冲仍会出现在结果里，只是带 `skipped: true` 且不含变量值。
- 变量数超过 `max_variables` 时会截断并置 `truncated: true` —— **默认参数下拿到的不是"全部变量"**，需要完整数据前先确认没有 `truncated`。
- 变量名常是无意义编号（`cb0_v1`、`cb0_v2`…），需要结合 `byte_offset` 与反汇编里的偏移推断语义。
- `resources` 是**反射声明的绑定**，可能为空；与实际绑定的资源不是一回事，想知道真正绑了什么请用 `get_pipeline_state`。
- 该 stage 未绑定着色器报 `No X shader bound`；stage 取值非法报 `Unknown shader stage`。
- 反汇编失败不会让整个调用失败，错误放在 `disassembly_error` 里。
- 响应可能很大（反汇编 + 全部变量值），建议先用 `include_disassembly: false` 加较小的 `max_variables` 探路。

## 错误码

| 错误码 | 含义 |
|---|---|
| `-32601` | 请求的方法不存在（扩展版本与 MCP 服务器不匹配） |
| `-32602` | 参数不合法（缺少必填参数、`resource_id` 格式错误、`event_id` 无对应动作、mip/slice/sample 越界） |
| `-32000` | 扩展侧执行失败（未加载捕获、RenderDoc API 报错等） |

MCP 服务器侧还可能抛出：
- `找不到 IPC 目录 ...`：RenderDoc 未启动，或扩展未加载（扩展启动时会创建该目录）。
- `RenderDoc MCP Bridge 未响应 ...`：首次调用前的连通性探测失败，说明扩展没有在轮询请求文件。
- `请求超时(Ns) ...`：请求已下发但超时未收到响应，通常是查询本身太慢，可调大超时或缩小范围。
