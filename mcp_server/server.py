"""
RenderDoc MCP Server
FastMCP 2.0 server providing access to RenderDoc capture data.

注意：下面每个工具的 docstring 会原样成为 agent 看到的工具描述（tools/list 的 description 字段），
改动这里等于改动 agent 的使用说明，必须与扩展侧实际行为保持一致。
参数的类型约束来自函数注解，docstring 里的说明只是给 agent 读的文本。
"""

from typing import Literal

from fastmcp import FastMCP

# 未使用（保留备查）：RenderDocBridgeError 仅在 client 内部抛出，这里不做捕获
# from .bridge.client import RenderDocBridge, RenderDocBridgeError
from .bridge.client import IPC_DIR, RenderDocBridge
from .config import settings

# Initialize FastMCP server
mcp = FastMCP(
    name="RenderDoc MCP Server",
)

# RenderDoc bridge client（基于文件 IPC，不需要 host/port）
bridge = RenderDocBridge(
    timeout=settings.bridge_timeout,
    probe_timeout=settings.bridge_probe_timeout,
)


def _params(**kwargs) -> dict[str, object]:
    """组装请求参数：过滤掉未显式指定的项，交由扩展侧使用默认值"""
    return {key: value for key, value in kwargs.items() if value is not None}


@mcp.tool
def ping() -> dict:
    """
    探测 RenderDoc 扩展是否存活。

    参数:
        无

    返回:
        {"alive": bool, "ipc_dir": str}

    注意:
        - 只表示"扩展进程正在轮询请求文件"，不代表已经加载了捕获；判断是否加载请用 get_capture_status。
        - 其他工具在首次调用前会自动做一次同样的探测（超时由 RENDERDOC_MCP_PROBE_TIMEOUT 控制，默认 5 秒），
          探测失败会立即报错，因此本工具主要用于人工排查连接问题。
    """
    return {"alive": bridge.ping(), "ipc_dir": IPC_DIR}


@mcp.tool
def get_capture_status() -> dict:
    """
    检查当前是否已加载捕获，并返回图形 API 类型。

    参数:
        无

    返回:
        未加载时只有 {"loaded": false}；已加载时含 {"loaded": true, "api": "GraphicsAPI.D3D11", "filename": "完整路径"}

    注意:
        - 未加载捕获时其余工具都会报 "No capture loaded"，需要先用 open_capture 打开捕获。
        - filename 是捕获文件的完整路径，不是文件名。
    """
    return bridge.call("get_capture_status")


@mcp.tool
def get_draw_calls(
    include_children: bool = True,
    marker_filter: str | None = None,
    exclude_markers: list[str] | None = None,
    event_id_min: int | None = None,
    event_id_max: int | None = None,
    only_actions: bool = False,
    flags_filter: list[str] | None = None,
) -> dict:
    """
    获取当前捕获的动作列表（标记 / 绘制调用 / Dispatch 等），返回层级结构。

    参数:
        include_children: 是否展开子动作，默认 true。**设为 false 时只返回顶层动作**，
            嵌套在其他动作之下的绘制会全部漏掉，很容易看起来"少了很多东西"。
        marker_filter: 只保留名字包含该字符串的 PushMarker 之下的动作（部分匹配）。
        exclude_markers: 丢弃名字包含列表中任意字符串的标记 —— 注意是**连同其整棵子树一起丢弃**。
        event_id_min: 只保留 event_id 不小于该值的动作。
        event_id_max: 只保留 event_id 不大于该值的动作。
        only_actions: true 时剔除标记动作，只保留实际动作，且被剔除标记的子动作会被提升到上一层。
        flags_filter: 只保留标志包含其中任意一项的动作，取值必须与返回的 flags 字符串完全一致
            （区分大小写，例如 ["Drawcall", "Dispatch"]）。

    返回:
        {"actions": [{"event_id", "action_id", "name", "flags", "num_indices", "num_instances", "children"?}]}

    注意:
        - flags_filter 只作用于非标记动作，写错（例如写成 "drawcall"）不会报错，只会拿到空数组，
          拿不准时可先不加该参数看一次 name 与 flags。
        - event_id 范围对标记不生效：为了维持层级，标记无论是否在范围内都会保留。
        - 标记是否出现取决于它的子动作是否通过过滤；标记自己不会被 flags_filter 过滤。
        - 不加限制地取整帧会返回很大的结果，建议配合 marker_filter / event_id 范围 / only_actions 缩小响应。
        - 本工具无需逐个回放，响应很快；需要"按资源反查"时请用 find_draws_by_* 系列（那些会慢很多）。
    """
    params = _params(
        include_children=include_children,
        marker_filter=marker_filter,
        exclude_markers=exclude_markers,
        event_id_min=event_id_min,
        event_id_max=event_id_max,
        only_actions=only_actions,
        flags_filter=flags_filter,
    )
    return bridge.call("get_draw_calls", params)


@mcp.tool
def get_frame_summary() -> dict:
    """
    获取整帧概览（API 类型、动作统计、顶层标记、资源数量），最适合作为探索的起点。

    参数:
        无

    返回:
        api、total_actions、statistics{draw_calls, dispatches, clears, copies, presents, markers}、
        top_level_markers[{name, event_id, child_count}]、resource_counts{textures, buffers}

    注意:
        - statistics.markers 只统计 PushMarker 与 SetMarker：一组 Push/Pop 记 1 个逻辑标记，PopMarker 不计入。
        - top_level_markers 只列顶层标记，可用其 event_id 配合 get_draw_calls 深入。
        - resource_counts 是整个捕获的资源总数，不是某一帧实际使用的数量。
        - 这里拿不到资源的 resource_id，需要时从 get_pipeline_state 的 resources / uavs / render_targets 里取。
    """
    return bridge.call("get_frame_summary")


@mcp.tool
def find_draws_by_shader(
    shader_name: str,
    stage: Literal["vertex", "hull", "domain", "geometry", "pixel", "compute"] | None = None,
) -> dict:
    """
    按着色器名反查使用它的绘制调用（部分匹配）。

    参数:
        shader_name: 匹配关键词，实际匹配的是着色器入口点名或着色器资源名。
        stage: 限定 stage；不填则遍历全部 6 个 stage（更慢）。

    返回:
        {"matches": [{"event_id", "name", "match_reason"}], "total_matches", "scanned_draws"}

    注意:
        - **整帧反查**：逐绘制回放，耗时随绘制数增长（每个绘制都要回放一次）。
          调用期间不要与其他工具并发，也不要和其他客户端同时使用。
        - 着色器入口点通常都叫 "main"，用 "main" 这类通用词会命中几乎全部绘制。
          请用足够具体的关键词，或先通过 get_pipeline_state / get_shader_info 确认真实的资源名。
        - 不填 stage 时计算着色器也会被算进去（D3D11 下很多绘制事件仍绑着计算着色器），这是结果偏多的常见原因。
        - 搜不到时会返回空的 matches 而不是报错；scanned_draws 可用于确认"是否真的扫过整帧"。
    """
    params = _params(shader_name=shader_name, stage=stage)
    return bridge.call("find_draws_by_shader", params, timeout=settings.bridge_search_timeout)


@mcp.tool
def find_draws_by_mesh(mesh_name: str) -> dict:
    """
    按网格（顶点/索引缓冲）名反查绘制调用（部分匹配）。

    参数:
        mesh_name: 顶点/索引缓冲资源名的一部分。

    返回:
        {"matches": [{"event_id", "name", "match_reason"}], "total_matches", "scanned_draws"}

    注意:
        - 是"绑定即命中"：只要该缓冲绑在管线上就算命中，不代表这次绘制真的使用了它（例如被剔除的实例仍会绑定）。
        - 只覆盖顶点/索引缓冲，不覆盖纹理与常量缓冲。
        - **整帧反查**：逐绘制回放，耗时随绘制数增长，不要与其他工具并发。
    """
    return bridge.call("find_draws_by_mesh", {"mesh_name": mesh_name}, timeout=settings.bridge_search_timeout)


@mcp.tool
def find_draws_by_texture(texture_name: str) -> dict:
    """
    按纹理名反查绘制调用（部分匹配）。

    参数:
        texture_name: 纹理资源名的一部分。

    返回:
        {"matches": [{"event_id", "name", "match_reason"}], "total_matches", "scanned_draws"}
        match_reason 会指明命中位置，例如 "ShaderStage.Pixel SRV: 'xxx'"。

    注意:
        - 搜索范围是 SRV、UAV 以及渲染目标；不覆盖顶点/索引缓冲与常量缓冲。
        - 与 get_shader_info 的 resources 不同，这里查的是**实际绑定**的资源，不是反射声明。
        - **整帧反查**：逐绘制回放，耗时随绘制数增长，不要与其他工具并发。
    """
    return bridge.call("find_draws_by_texture", {"texture_name": texture_name}, timeout=settings.bridge_search_timeout)


@mcp.tool
def find_draws_by_resource(resource_id: str) -> dict:
    """
    按资源 ID 精确反查绘制调用。搜索范围：着色器、SRV、UAV、渲染目标、深度目标。

    参数:
        resource_id: "ResourceId::12345" 或 "12345" 均可，比较的是其中的数字部分。

    返回:
        {"matches": [{"event_id", "name", "match_reason"}], "total_matches", "scanned_draws"}

    注意:
        - 需要先知道资源 ID。工具集没有"资源清单"接口，ID 可从 get_pipeline_state 的
          shaders[*].resources / uavs / render_targets / depth_target 里取。
        - ID 格式非法会直接报错；ID 不存在会返回空 matches（不报错），两者表现不一样。
        - **整帧反查**：逐绘制回放，耗时随绘制数增长，不要与其他工具并发。
    """
    return bridge.call("find_draws_by_resource", {"resource_id": resource_id}, timeout=settings.bridge_search_timeout)


@mcp.tool
def get_draw_call_details(event_id: int) -> dict:
    """
    获取单个绘制调用的详细信息（几何数量、输出目标等）。

    参数:
        event_id: 目标动作所在的事件 ID。

    返回:
        event_id、action_id、name、flags、num_indices、num_instances、base_vertex、
        vertex_offset、instance_offset、index_offset、outputs[{index, resource_id}]、depth_output?

    注意:
        - event_id 必须是真实动作（绘制 / Dispatch 等）所在的事件；传标记的 event_id 或任意事件
          会报 "No action at event N"。
        - num_instances 在非实例化绘制上可能为 0，不要直接当成实例数；判读时结合 name
          （DrawIndexed / DrawIndexedInstanced / Draw）一起看。
        - depth_output 只在绑定了深度目标时出现。
        - outputs 只有资源 ID，需要名称/尺寸请再调 get_texture_info。
    """
    return bridge.call("get_draw_call_details", {"event_id": event_id})


@mcp.tool
def get_action_timings(
    event_ids: list[int] | None = None,
    marker_filter: str | None = None,
    exclude_markers: list[str] | None = None,
) -> dict:
    """
    获取动作的 GPU 执行时间。

    参数:
        event_ids: 只取这些事件的耗时；不填则返回全部有计时数据的动作。
        marker_filter: 只保留"从根到当前动作的标记路径"包含该字符串的动作（部分匹配）。
        exclude_markers: 丢弃标记路径包含列表中任意字符串的动作。

    返回:
        available、unit、timings[{event_id, name, duration_seconds, duration_ms}]、total_duration_ms、count

    注意:
        - 部分硬件/驱动不提供 GPU 时间计数器，此时返回 available: false，**不要当成"耗时为 0"**。
        - total_duration_ms 是本次返回项之和，不是整帧总耗时；加了过滤后它会相应变小。
        - 单位由 unit 字段给出（通常是秒），不要假定为毫秒。
        - 过滤是"标记路径包含"语义，与 get_draw_calls 的过滤规则不同；
          路径不匹配时仍会递归子节点，所以嵌套在更内层标记里的动作不会被漏掉。
        - 没有计时数据的事件会被静默跳过，因此 count 可能小于 event_ids 的长度。
        - 它是全帧扫描，建议和别的调用分开。
    """
    params = _params(event_ids=event_ids, marker_filter=marker_filter, exclude_markers=exclude_markers)
    return bridge.call("get_action_timings", params)


@mcp.tool
def get_shader_info(
    event_id: int,
    stage: Literal["vertex", "hull", "domain", "geometry", "pixel", "compute"],
    cbuffer_slots: list[int] | None = None,
    max_variables: int = 64,
    include_disassembly: bool = True,
) -> dict:
    """
    获取指定事件、指定 stage 的着色器信息：反汇编、常量缓冲的实际值、反射声明的资源绑定。

    参数:
        event_id: 要查看的事件 ID。
        stage: 必填，6 个 stage 之一。
        cbuffer_slots: 只读取这些常量缓冲槽位的变量值；不填表示全部。
        max_variables: 每个常量缓冲最多返回多少个变量（默认 64）。
        include_disassembly: 是否返回反汇编（默认 true）。

    返回:
        resource_id、entry_point、stage、disassembly（失败时为 disassembly_error）、
        constant_buffers[{name, slot, size, variables[], skipped?, truncated?, error?}]、resources[]

    注意:
        - **cbuffer_slots 用的是反射索引（从 0 开始）**，与返回里的 slot 字段一致。
        - 被 cbuffer_slots 排除的常量缓冲仍会出现在结果里，只是带 skipped: true 且不含变量值。
        - 变量数超过 max_variables 时会截断并置 truncated: true —— 所以默认参数下拿到的**不是"全部变量"**。
          需要完整数据前请先确认没有 truncated，否则可能漏看关键变量。
        - 变量名常是无意义编号（cb0_v1、cb0_v2…），需要结合 byte_offset 与反汇编里的偏移来推断语义。
        - resources 是"反射声明的绑定"，可能为空；它与 get_pipeline_state 里"实际绑定的资源"不是一回事，
          想知道真正绑了什么请用 get_pipeline_state。
        - 该 stage 未绑定着色器时报 "No X shader bound"；stage 取值非法时报 "Unknown shader stage"。
        - 反汇编失败不会让整个调用失败，错误会放在 disassembly_error 字段里。
        - 响应可能很大（反汇编 + 全部变量值），建议先用 include_disassembly: false 加较小的 max_variables 探路。
    """
    params = _params(
        event_id=event_id,
        stage=stage,
        cbuffer_slots=cbuffer_slots,
        max_variables=max_variables,
        include_disassembly=include_disassembly,
    )
    return bridge.call("get_shader_info", params)


@mcp.tool
def get_buffer_contents(
    resource_id: str,
    offset: int = 0,
    length: int = 0,
) -> dict:
    """
    读取缓冲区内容（Base64 编码）。

    参数:
        resource_id: 缓冲区资源 ID。
        offset: 起始字节偏移，默认 0。
        length: 读取字节数，0 表示读到末尾。

    返回:
        resource_id、length（实际读到的字节数）、total_size（缓冲区总大小）、offset、content_base64

    注意:
        - **只接受缓冲区**：传纹理 ID 会报 "Buffer not found"，请先用 get_texture_info 或
          get_pipeline_state 确认资源类型。
        - 工具集没有"缓冲区清单"：只能从 get_pipeline_state 的 uavs / resources 里挑 type == "buffer" 的
          resource_id，其 length 字段就是缓冲区大小。
        - Base64 会让体积放大约 1/3，大缓冲请用 offset + length 分段读取。
        - offset + length 超出缓冲区大小不会被自动裁剪，请先确认 total_size。
    """
    return bridge.call("get_buffer_contents", _params(resource_id=resource_id, offset=offset, length=length))


@mcp.tool
def get_texture_info(resource_id: str) -> dict:
    """
    获取纹理的元数据（尺寸、格式、mip 数等）。

    参数:
        resource_id: 纹理资源 ID，"ResourceId::123" 或 "123" 均可。

    返回:
        resource_id、width、height、depth、array_size、mip_levels、format、dimension、
        msaa_samples、byte_size

    注意:
        - ID 格式非法报 "Invalid resource ID"；资源不存在报 "Texture not found"；传缓冲区 ID 同样报后者。
        - width / height 是第 0 级 mip 的尺寸。
        - byte_size 是**整张纹理**（含全部 mip 与数组层）的字节数，不是单层大小。
        - 读像素前先用本工具确认 mip_levels 与 msaa_samples，避免越界参数。
    """
    return bridge.call("get_texture_info", {"resource_id": resource_id})


@mcp.tool
def get_texture_raw(
    resource_id: str,
    mip: int = 0,
    slice: int = 0,
    sample: int = 0,
    depth_slice: int | None = None,
) -> dict:
    """
    读取纹理的原始像素数据（Base64），不落盘。仅适合小纹理。

    参数:
        resource_id: 纹理资源 ID。
        mip: mip 级别，默认 0。
        slice: 数组层或立方体面索引，默认 0。立方体贴图按 0=X+, 1=X-, 2=Y+, 3=Y-, 4=Z+, 5=Z-。
        sample: MSAA 采样索引，默认 0。
        depth_slice: 仅 3D 纹理有效，取指定深度的 2D 切片；不填表示整个体数据。

    返回:
        元数据（resource_id、width、height、depth、mip、slice、sample、depth_slice、format、
        dimension、is_3d、total_depth、data_length）+ content_base64

    注意:
        - **大纹理请改用 get_texture_saved**：Base64 会把体积放大约 1/3，很容易超过 MCP 的响应大小限制；
          请先按 width × height × 每像素字节数估算，再决定是否直接读原始数据。
        - mip 必须小于 mip_levels（很多离屏纹理只有 1 级 mip），越界会明确报错。
        - 立方体贴图的 slice 是"面索引"，多层立方体贴图则是 arraysize × 6 的扁平索引。
        - sample 只对 MSAA 纹理（msaa_samples > 1）有效，普通纹理传非 0 会报错。
        - depth_slice 只能用于 3D 纹理（depth > 1），对普通 2D 纹理传它会直接报错。
        - 越界的 mip / slice / sample / depth_slice 都会给出明确的越界错误，可直接按错误信息修正。
    """
    params = _params(resource_id=resource_id, mip=mip, slice=slice, sample=sample, depth_slice=depth_slice)
    return bridge.call("get_texture_raw", params)


@mcp.tool
def get_texture_saved(
    resource_id: str,
    mip: int = 0,
    slice: int = 0,
    sample: int = 0,
    depth_slice: int | None = None,
) -> dict:
    """
    把纹理保存成 PNG 文件并返回路径（推荐用于大纹理，避开响应大小限制）。

    参数:
        resource_id: 纹理资源 ID。
        mip: mip 级别，默认 0。
        slice: 数组层或立方体面索引，默认 0。立方体贴图按 0=X+, 1=X-, 2=Y+, 3=Y-, 4=Z+, 5=Z-。
        sample: MSAA 采样索引，默认 0。
        depth_slice: 仅 3D 纹理有效，取指定深度的 2D 切片；不填表示整个体数据。

    返回:
        除元数据外，含 file_path、file_url、file_size、filename

    注意:
        - 文件写在 **RenderDoc 扩展安装目录的 temp/ 子目录**下，不会自动清理；
          重新安装扩展时会保留该目录，长期使用请自行清理。
        - 返回的路径是"发起调用的那台机器"上的路径；file_url 可直接在浏览器打开。
        - 参数约束与 get_texture_raw 相同：mip / sample / depth_slice 越界或类型不匹配都会报错。
        - 想知道"到底存了哪一层"，看返回里的 mip / slice / sample / depth_slice 与 filename 即可。
    """
    params = _params(resource_id=resource_id, mip=mip, slice=slice, sample=sample, depth_slice=depth_slice)
    return bridge.call("get_texture_saved", params)


@mcp.tool
def get_pipeline_state(event_id: int, include_cbuffer_variables: bool = True) -> dict:
    """
    获取指定事件的完整管线状态。

    参数:
        event_id: 目标事件 ID。
        include_cbuffer_variables: 是否返回每个常量缓冲的变量清单，默认 true；建议传 false。

    返回:
        api、shaders{stage: {resource_id, entry_point, resources[], uavs[], samplers[], constant_buffers[]}}、
        viewport_scissors{viewports[], scissors[]}、render_targets[]、depth_target、input_assembly、
        blend{targets[]}、depth_stencil{stencil_front/back}、errors?

    注意:
        - **响应通常很大，强烈建议先传 include_cbuffer_variables: false**。常量缓冲可能包含数百个变量，
          且名字多是无意义编号（如 cb0_v1），会显著放大响应体积；
          需要变量值时改用 get_shader_info（它支持 cbuffer_slots 与 max_variables 裁剪）。
        - shaders 里只列出真正绑定了着色器的 stage。D3D11 下即使是绘制事件，计算着色器往往仍然绑着，
          所以会同时出现 ShaderStage.Compute —— 这是正常现象，不代表该事件真的执行了计算。
        - 某个状态块读取失败时会写进 errors（键为状态名，例如 errors.blend），其余状态照常返回，
          不会让整个调用失败；解读结果时建议先看一眼有没有 errors。
        - viewport_scissors 最多各返回 16 项，超出的会被丢弃。
        - resources 里的 name 来自着色器反射（例如 "BlitTexture"），resource_id 才是唯一标识；
          需要尺寸/格式之外的信息请用 get_texture_info。
        - 本工具是获取纹理/缓冲区 resource_id 的**主要来源**
          （resources、uavs、render_targets、depth_target 都会带 resource_id）。
    """
    params = _params(event_id=event_id, include_cbuffer_variables=include_cbuffer_variables)
    return bridge.call("get_pipeline_state", params)


@mcp.tool
def list_captures(directory: str) -> dict:
    """
    列出指定目录下的 .rdc 捕获文件。

    参数:
        directory: 要搜索的目录（绝对路径）。

    返回:
        {"directory", "count", "captures": [{"filename", "path", "size_bytes", "modified_time"}]}

    注意:
        - 目录不存在会报错；只匹配 .rdc 扩展名，且**不递归子目录**。
        - 按修改时间倒序（最新的在前），modified_time 是本地时区的 ISO 格式字符串。
        - 只是列文件，不会加载捕获；要加载请用 open_capture。
    """
    return bridge.call("list_captures", {"directory": directory})


@mcp.tool
def open_capture(capture_path: str) -> dict:
    """
    打开捕获文件。

    参数:
        capture_path: .rdc 文件的绝对路径。

    返回:
        {"success": true, "capture_path", "filename", "api"?}

    注意:
        - **会关闭当前已加载的捕获**，当前选中事件等临时状态都会丢失。
        - 文件不存在或扩展名不是 .rdc 会报错。
        - 大捕获加载很慢（可能数十秒），加载期间扩展无法响应任何请求；
          调用时请留足超时时间，并且**不要紧接着发起其他请求**。
        - api 字段可能缺失（读取 API 类型失败时会省略），此时用 get_capture_status 复查更可靠。
    """
    return bridge.call("open_capture", {"capture_path": capture_path})


def main():
    """Run the MCP server"""
    mcp.run()


if __name__ == "__main__":
    main()
