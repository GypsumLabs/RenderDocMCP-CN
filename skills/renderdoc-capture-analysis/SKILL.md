---
name: renderdoc-capture-analysis
description: 引导用户和 AI Agent 通过 RenderDoc MCP 对当前已加载的截帧做一次基础分析。当用户提到 RenderDoc、.rdc 截帧、渲染帧、DrawCall、渲染 Pass、GPU 耗时，或要求"看看这帧/分析这帧/截帧概览"时使用。技能负责确认 RenderDoc 与截帧的就绪状态、指导打开截帧、按固定顺序做基础检索、输出一份基础分析报告，并把后续深入分析的需求交还给用户。
---

# RenderDoc 截帧基础分析

通过 RenderDoc MCP 服务器（MCP 服务器名 `renderdoc`）对**当前已加载的截帧**做一次基础分析并出报告。目标有两个：让用户拿到一份能看懂这帧在干什么的概述，同时让 Agent 通过实操熟悉这套工具的用法，便于用户后续提更具体的问题。

## 硬约束（先读，出错基本都是踩了这些）

- **扩展侧是单请求通道**：同一时刻只能处理一个请求。所有 MCP 工具调用必须**严格串行**，一次只发一个，等返回再发下一个。并行调用会互相覆盖请求文件，先发出的那个只能等满超时。全帧扫描类工具（`get_action_timings`、`find_draws_by_*`）尤其要单独调用。
- **不要同时开多个客户端**（例如 IDE 里的 MCP + 另开一个脚本进程）。被放弃的调用不会立刻停止，会持续抢读 `response.json`，把本该给别人的响应吃掉，表现为各种莫名其妙的超时。
- 首次调用任何工具前会自动做一次连通性探测（5 秒），所以 RenderDoc 没起来时会立刻报错，而不是白等 120 秒。

## 第 0 步：就绪检查（必须先做）

按顺序调用，不要跳过：

1. `ping` → 判断扩展是否在轮询。
2. `get_capture_status` → 判断截帧是否已加载。

### 情况 A：`ping` 返回 `alive: false`

说明扩展没有在轮询请求文件，**不代表 RenderDoc 没启动**。常见原因与处理：

- **RenderDoc 没启动** → 请用户启动，并确认 `Tools > Manage Extensions` 里 "RenderDoc MCP Bridge" 已启用。
- **RenderDoc 在跑但扩展没起来**（例如改了扩展代码后没重启、或 `%TEMP%\renderdoc_mcp` 被清掉）→ 扩展**只在 RenderDoc 启动时加载一次**，重新打开捕获无效，必须重启 RenderDoc。
  可以先用这条命令确认症状（返回 `False` 就是扩展没在运行）：

  ```powershell
  Test-Path "$env:TEMP\renderdoc_mcp"
  ```

  需要时请用户重启 RenderDoc（可直接带截帧启动）：

  ```powershell
  Stop-Process -Name qrenderdoc -Force
  Start-Process "C:\Program Files\RenderDoc\qrenderdoc.exe" -ArgumentList "<捕获路径>"
  ```

- **扩展根本没装** → 让用户在仓库根目录执行 `python scripts/install_extension.py`，然后重启 RenderDoc并启用扩展。

> 重启会关掉用户当前的截帧，动手前先告知用户。重启后重新执行第 0 步。

### 情况 B：`ping` 正常但 `get_capture_status` 返回 `loaded: false`

引导用户提供截帧：

- 用户给了目录 → `list_captures(directory)` 列出该目录下的 `.rdc`（按修改时间倒序，不递归子目录），把结果给用户挑。
- 用户给了具体文件 → 直接进入下一步。
- `open_capture` **会关闭当前已打开的捕获**，调用前必须让用户确认。

打开后重新调 `get_capture_status` 复核，确认 `loaded: true` 并记下 `api` 与 `filename`，再进入分析。

## 基础检索流程

按下面顺序走，每一步的记录都要留到写报告时用。默认不开启"排除编辑器事件"之类的启发式判断——基础分析只呈现事实，把判断留给用户。

### 1. 整帧概览 — `get_frame_summary`

拿到 `api`、`total_actions`、`statistics`（draw_calls / dispatches / clears / copies / presents / markers）、`top_level_markers`、`resource_counts`。

注意：`resource_counts` 是整个捕获的资源总数，不是本帧实际使用的数量。

### 2. 动作层级 — `get_draw_calls`

用**默认参数**（`include_children: true`）取完整树。这一步是后面所有 Pass 归属的基础。

- 响应可能较大。若截帧很大，改用 `marker_filter` 逐个 Pass 取，或配 `exclude_markers` 排除无关标记。
- **不要用 `include_children: false`**：该参数会把所有标记（Pass）一并丢掉，只剩平铺的动作，Pass 结构直接消失。
- **不要用标记的 `event_id` 去设 `event_id_min` / `event_id_max`**：标记自身的 `event_id` 常常落在它子动作的事件范围之外（实测中标记在 6962-6971，子动作却分布在 152-6927），用它当范围会得到空结果。要按 Pass 取内容，用 `marker_filter`。

### 3. 耗时分布 — `get_action_timings`

先无参数调用一次，拿到全帧每个事件的 GPU 耗时，按 `duration_ms` 排序找出热点事件。

- `total_duration_ms` 是本次返回各项之和（GPU 忙时累加），**不是帧时间**，别当成帧耗时报给用户。
- 硬件不支持计时时返回 `available: false`，这时**不要写成"耗时 0"**，直接说明该截帧拿不到 GPU 计时。
- 需要某个 Pass 的合计耗时时，用 `marker_filter="<标记名>"` 单独调一次，读它的 `total_duration_ms`。
- GPU 计时每次运行都有抖动（同一个 Dispatch 两次读到 2.6ms 与 2.1ms）。报告里给量级和相对占比，不要给精确到小数点后三位的绝对值，也不要用它做"A 比 B 快 0.03ms"这类比较。

### 4. 代表事件深入（挑 1-2 个）

从热点事件里选 1-2 个代表性的（耗时最高的那个、或最大 Pass 里的典型绘制），按需取：

- `get_draw_call_details(event_id)` → 索引数、实例数、输出目标。**只能传真实动作的 event_id**，传标记或任意事件会报 `No action at event N`。
- `get_pipeline_state(event_id, include_cbuffer_variables: false)` → 着色器绑定、资源绑定（`resources` / `uavs` / `render_targets` / `depth_target` 都带 `resource_id`）、视口、混合、深度模板。这是拿 `resource_id` 的主要来源。响应通常很大，**务必先传 `include_cbuffer_variables: false`**。先扫一眼有没有 `errors` 字段（个别状态读取失败会记在那里，不影响其它字段）。
- `get_shader_info(event_id, stage, include_disassembly: false, max_variables: <小值>)` → 常量缓冲的实际值。`cbuffer_slots` 用的是**反射索引（从 0 开始）**；默认 `max_variables: 64` 会截断，返回里带 `truncated: true`，所以默认参数拿到的不等于"全部变量"。
- `get_texture_info(resource_id)` → 尺寸、格式、mip 数。读像素前先用它确认 `mip_levels` 与 `msaa_samples`，避免越界。

### 5. 一次反查（演示"按资源回查"）

从第 4 步拿到的资源名里挑一个具体的，调用 `find_draws_by_texture`（或 `find_draws_by_shader` / `find_draws_by_mesh`）。

- 返回 `{"matches": [{event_id, name, match_reason}], total_matches, scanned_draws}`，`match_reason` 会说明命中位置（如 `ShaderStage.Compute UAV: 'xxx'`）。
- 这是**整帧扫描**，逐绘制回放，很慢。必须单独调用，不要和其它调用并发。演示一次即可，不要顺手把四个反查都跑一遍。
- 匹配词要够具体。`find_draws_by_shader` 的匹配目标是入口点名（通常就是 `main`）或着色器资源名，传 `"main"` 会命中几乎所有绘制。

### 6. 可选：取最终画面

想给报告配图时，用 `get_texture_saved(resource_id)` 把纹理存成 PNG，返回 `file_path` / `file_url`。定位"最终画面"的办法：从 `get_draw_calls` 结果找 Present 之前最后一个后处理相关的绘制，用 `get_draw_call_details` 或 `get_pipeline_state` 取它的输出 `resource_id`。

- 大纹理一律用 `get_texture_saved`，不要用 `get_texture_raw`（Base64 会把体积放大约 1/3，容易超限）。
- 图片会累积在扩展安装目录的 `temp/` 下，不自动清理。

## 输出报告

按 `references/report-template.md` 的结构产出，**直接在对话里给出**，除非用户明确要求写成文件。报告要包含：

1. 截帧概述：文件、API、动作统计、资源数量。
2. 主要 Pass 构成：每个 Pass 的名称、动作数、绘制/Dispatch/Clear 数、GPU 耗时与占比。
3. 耗时热点：Top 5-10 个事件及其所属 Pass。
4. 代表事件剖析：管线状态与资源绑定里读到的关键信息。
5. 反查示例：验证了哪个资源被谁使用。
6. 结论与可继续深入的线索。

只写从工具结果里能直接得到的事实。不要凭经验臆断引擎或美术风格；如果工具没给出依据，就标注"未确认"。

## 交还给用户

报告给完后，明确列出下一步能做什么，让用户提具体需求，例如：

- 深入某个 Pass（`get_draw_calls(marker_filter=...)` + `get_action_timings(marker_filter=...)`）
- 查某个资源的全部使用点（`find_draws_by_resource` / `find_draws_by_mesh`）
- 看某个事件的完整管线状态或着色器反汇编（`get_pipeline_state` / `get_shader_info(include_disassembly: true)`）
- 导出中间 RT 看内容（`get_texture_saved`）
- 读顶点/索引缓冲内容（`get_buffer_contents`）

## 参考资源

- `references/tools.md`：18 个工具的参数、返回结构与易踩的坑，需要确认细节时查阅。
- `references/report-template.md`：基础分析报告模板。
