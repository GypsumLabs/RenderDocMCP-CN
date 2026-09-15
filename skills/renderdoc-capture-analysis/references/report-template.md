# 基础分析报告模板

按此结构产出报告，直接写在对话里，除非用户明确要求写成文件。

填写原则：**只写工具结果里能直接读到的事实**。工具没给出依据的内容标注"未确认"，不要凭经验补。

---

## 一、截帧概述

| 项 | 值 |
|---|---|
| 捕获文件 | `[get_capture_status.filename 完整路径]` |
| 图形 API | `[get_capture_status.api]` |
| 总动作数 | `[get_frame_summary.total_actions]` |
| DrawCall | `[statistics.draw_calls]` |
| Dispatch | `[statistics.dispatches]` |
| Clear | `[statistics.clears]` |
| Copy | `[statistics.copies]` |
| Present | `[statistics.presents]` |
| 标记数 | `[statistics.markers]` |
| 纹理 / 缓冲区 | `[resource_counts.textures]` / `[resource_counts.buffers]`（整个捕获的总数，非本帧使用量） |

> `resource_counts` 是整个捕获的资源总数，不是本帧实际使用的数量 —— 这句要写进报告，避免读者误读。

## 二、主要 Pass 构成

Pass 结构来自 `get_draw_calls` 的标记层级。逐条统计每个顶层标记下的动作构成。

| Pass（标记名） | 动作数 | 绘制 | Dispatch | Clear | GPU 耗时 (ms) | 占比 |
|---|---|---|---|---|---|---|
| `[标记名]` | `[后代总数]` | `[count]` | `[count]` | `[count]` | `[合计或"—"]` | `[x%]` |
| 标记外动作 | | | | | | |
| **合计** | `[total_actions]` | `[draw_calls]` | `[dispatches]` | `[clears]` | `[total_duration_ms]` | 100% |

**填表要点**：

- 动作数 = 该标记的后代数（`get_frame_summary.top_level_markers[].child_count`），或直接数 `get_draw_calls` 结果里该标记的 `children`。
- 耗时一列：先无参数调一次 `get_action_timings` 拿到每个事件的耗时，按标记归属求和；或对关注的 Pass 单独用 `get_action_timings(marker_filter="<标记名>")` 读它的 `total_duration_ms`。
- **`total_duration_ms` 是各事件 GPU 忙时之和，不是帧时间**，报告里要注明"以下耗时为各事件 GPU 时间之和，非帧耗时"。
- GPU 计时有抖动、且硬件可能不支持。不支持时（`available: false`）这一列整体写"该截帧无法获取 GPU 计时"，不要填 0。
- 占比按耗时之和计算。

## 三、耗时热点

列出耗时最高的 5-10 个事件（`get_action_timings` 按 `duration_ms` 排序）：

| 排名 | event_id | 动作 | 所属 Pass | 耗时 (ms) | 占 GPU 时间比 |
|---|---|---|---|---|---|
| 1 | `[event_id]` | `[name]` | `[标记名]` | `[duration_ms]` | `[x%]` |

**解读要点**（有依据才写）：

- 单个 Dispatch 就占掉整帧相当比例时，指出它并说明它的 UAV/输出是什么（配合第 4 节）。
- 索引数很大的绘制（`get_draw_call_details.num_indices`）通常对应高顶点开销，可以点出来。
- 大量 `num_indices` 极小的绘制（如 3 / 6）集中出现，通常是小件几何或全屏三角，值得提示但不臆断原因。

## 四、代表事件剖析

挑 1-2 个事件展开。每个写：

- **event_id / 动作名 / 所属 Pass / 耗时**。
- **几何**：`get_draw_call_details` 的 `num_indices`、`num_instances`、`outputs`、`depth_output`。
- **输出目标**：`get_texture_info` 读到的尺寸与格式。
- **绑定资源**：`get_pipeline_state(..., include_cbuffer_variables: false)` 里典型的 SRV / UAV / render_targets 名称。
- **着色器**：`get_shader_info` 的 `resource_id`、常量缓冲槽位大小；如有 `truncated: true` 要注明"变量未取全"。

> 如果该事件的 `get_pipeline_state` 返回里有 `errors`，在这里说明哪些状态块读取失败。
> D3D11 下绘制事件同时列出 `ShaderStage.Compute` 属正常现象，不代表真的执行了计算，不要当成发现。

## 五、反查示例

记录本次演示的 `find_draws_by_*` 调用：

- 工具与匹配词：`find_draws_by_texture("xxx")`
- 结果：`total_matches` / `scanned_draws`，以及每条 `match_reason`
- 说明该资源被哪些事件读写。

> 反查是全帧扫描，很慢，报告里只需一次示例以及它验证了什么。
> `find_draws_by_mesh` 是"绑定即命中"，不代表这次绘制真的用了该缓冲，报告里要注明。

## 六、结论与后续线索

- 3-5 条从上面数据直接得出的结论（哪个 Pass 最重、哪些事件是热点、资源绑定上有什么值得注意的点）。
- 明确列出可以继续做的分析，让用户提需求：
  - 深入某个 Pass（`marker_filter` 取动作 + `marker_filter` 取耗时）
  - 查某个资源的全部使用点（`find_draws_by_resource` / `find_draws_by_mesh`）
  - 看完整管线状态或着色器反汇编（`get_pipeline_state` / `get_shader_info(include_disassembly: true)`）
  - 导出中间 RT 看内容（`get_texture_saved`）
  - 读顶点/索引缓冲内容（`get_buffer_contents`）

---

**报告生成**：RenderDoc MCP (`renderdoc`) + `renderdoc-capture-analysis` skill
