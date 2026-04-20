---
name: renderdoc-analyze
description: 此技能用于分析RenderDoc截帧，提供渲染性能分析、DrawCall统计、模块化渲染管线分析等功能。支持任意图形API（D3D11/D3D12/Vulkan/OpenGL/Metal）和任意引擎/应用的截帧分析，并对Unity URP管线提供额外的特化分析能力。
---

# RenderDoc 截帧分析技能

## 技能概述

此技能提供针对RenderDoc截帧专业分析的能力，主要针对游戏截帧，包括:
- 渲染管线结构分析（根据Marker层级自动识别管线架构）
- DrawCall和性能统计
- 模块化渲染耗时分析
- 资源使用分析（纹理、Buffer）
- 针对性的优化建议

**引擎/管线特化支持**:
- Unity URP（Forward / Forward+ / Deferred）- 提供详细的Pass级参考文档
- 其他引擎和自研管线 - 基于Marker层级进行通用分析

## 前置检查流程

### 1. 检查RenderDoc MCP可用性

首先检查renderdoc MCP是否可用，如果没有找到MCP，引导用户安装和配置:
- 提供安装链接: https://github.com/GypsumLabs/RenderDocMCP-Skilled
- 说明配置步骤

### 2. 检查RenderDoc服务状态

如果MCP存在但无法连接，要求用户:
- 启动配置了MCP服务的RenderDoc应用程序
- 确认MCP服务是否开启，方式：RenderDoc菜单栏 -> Tools -> MCP Bridge -> Status

### 3. 检查截帧状态

调用`get_capture_status`工具检查是否已打开截帧:
- 如果没有截帧打开，引导用户提供截帧文件路径
- 使用`open_capture`工具打开截帧文件
- 确认截帧成功加载后再开始分析

## 渲染快报

一切就绪后，按照以下步骤进行截帧分析，最终给出一份渲染分析报告

### 步骤1: 获取截帧摘要

调用`get_frame_summary`工具获取当前截帧的整体统计信息，包括:
- 图形API类型 (D3D11, D3D12, Vulkan, OpenGL, Metal等)
- 总Action数量
- DrawCall/Dispatch/Clear/Copy/Present次数
- 顶层Marker结构
- 资源统计(贴图和Buffer数量)

### 步骤2: 识别引擎和渲染管线

根据步骤1获取的顶层Marker结构，判断截帧来源的引擎和渲染管线类型:

**Unity引擎识别**:
- 顶层Marker包含 `UniversalRenderPipeline` → Unity URP管线
- 顶层Marker包含 `HDRenderPipeline` → Unity HDRP管线
- 顶层Marker包含 `Camera.Render` 但无上述标识 → Unity Built-in管线
- 在渲染相机之前有 `UIR.DrawChain`、`Gizmos.Draw` 等事件 → Unity编辑器截帧，需排除这些编辑器事件

**Unreal引擎识别**:
- 顶层Marker包含 `Scene`、`BasePass`、`LightingPass` 等 → Unreal渲染管线
- 可能出现 `PrePass`、`HZB`、`SSAO`、`Translucency` 等Marker

**其他引擎/自研管线**:
- 根据Marker命名和层级结构推断管线架构
- 常见模式: Shadow Pass → Depth/GBuffer → Lighting → Transparent → PostProcess → UI

**确定是Unity URP管线时**: 额外参考 `references/urp_pipeline_structure.md` 以获得更准确的分析

### 步骤3: 获取最终渲染画面截图

通过`get_texture_saved`工具获取最终渲染画面的截图，用于分析画面内容。如果模型不具备图片输入能力，跳过这步。

**定位最终画面纹理的方法**:
1. 从DrawCall层级中找到最后一个后处理相关的Pass（如PostProcessing、FinalBlit、Present前的最后一个绘制操作）
2. 获取该Pass最后一个event的`get_pipeline_state`，找到其输出的Render Target的resource_id
3. 调用`get_texture_saved`保存图片并返回图片路径
4. 用返回的文件路径读取图片，分析画面内容：应用类型、美术风格、当前场景等，如果画面很明显不是正常游戏画面，重新回到第一步重新尝试寻找正确的截图

**注意事项**:
- 如果截帧有多个渲染目标或多相机，最终画面通常在最后一个后处理输出或Present之前的RT上
- **输出报告文件时**：需要将最终渲染截图拷贝到报告MD文件的同目录下（不需要改名，使用原文件名），并在报告中使用相对路径引用

### 步骤4: 获取完整DrawCall层级

调用`get_draw_calls`工具获取完整的DrawCall和Action层级结构。

**分析要点**:
- 根据步骤2识别的引擎类型，排除非游戏/应用渲染的事件（如Unity编辑器UI事件）
- 理解Marker层级组织，识别主要渲染阶段
- 注意区分引擎内置Pass和项目自定义Pass

### 步骤5: 统计关键指标

基于`get_draw_calls`的结果（排除非渲染事件后）统计:
- 图形API类型
- 实际渲染的DrawCall数量
- ComputeShader的Dispatch数量
- Clear操作次数
- Copy操作次数
- 使用的贴图和Buffer数量

### 步骤6: 划分渲染功能模块

根据DrawCall的Marker和层级关系识别渲染功能模块。典型的渲染管线模块包括（不同引擎/管线名称可能不同）:

| 通用阶段 | 说明 |
|---|---|
| **Shadow Rendering** | 阴影贴图生成（级联阴影、点光源阴影等） |
| **Depth/GBuffer Pass** | 深度预渲染或GBuffer写入 |
| **Lighting** | 光照计算（前向或延迟） |
| **Opaque Rendering** | 不透明物体绘制 |
| **Sky Rendering** | 天空/环境渲染 |
| **Transparent Rendering** | 半透明物体绘制 |
| **Post Processing** | 后处理效果链 |
| **UI Rendering** | 用户界面渲染 |

根据实际截帧的Marker层级来划分，不要强行套用上述模板。

### 步骤7: 获取模块耗时

针对识别出的每个大模块，调用`get_action_timings`工具，传入对应的Marker名称或event_id范围，获取:
- 该模块的总耗时(毫秒)
- 模块内各子阶段的耗时分布

### 步骤8: 整合同一Pass的DrawCall

一系列属于同一个渲染Pass的DrawCall应该整合到一起呈现，例如:
- 同一GBuffer/Forward Pass中绘制不透明队列的所有DrawCall
- 同一级联阴影的所有DrawCall
- 同一批次的实例化绘制

不需要逐个分析每一条DrawCall，这样信息会过多过杂

### 步骤9: 生成分析报告

- **重要**：严格按照报告模板生成报告
- 表格模板: `assets/report_template.md`
- **如果用户要求输出报告文件**：
  - 分两步完成：先用脚本创建文件夹和空白MD，再写入报告内容
  - **第一步**: 运行 `scripts/generate_report.py` 脚本，脚本会完成以下操作：
    1. 在指定保存路径创建报告文件夹（格式：`{截帧名}_分析报告`）
    2. 拷贝最终渲染截图到文件夹内（统一命名为 `final_capture.png`）
    3. 创建空白MD报告文件（`RenderDoc_分析报告.md`）
    4. 输出MD文件的绝对路径
    5. 注意：`ResourceId`只需要传数字部分作为参数
  - 脚本参数：
    - `--output`: 保存路径（用户指定或从rdc文件路径推断）
    - `--name`: 截帧名称（从rdc文件名提取）
    - `--image-path`: 最终渲染截图源路径（`get_texture_saved`返回的路径）
  - **第二步**: 使用文件写入工具，将完整的报告Markdown内容写入脚本输出的MD文件路径
    - 报告中引用截图时使用相对路径 `final_capture.png`

### 步骤10: 后续分析咨询

将完整的分析结果呈现给用户，并询问:
- 是否需要深入分析某个特定模块
- 是否需要查看特定DrawCall的详细信息
- 是否需要检查Shader或纹理使用情况

## 深入分析工具

根据用户需求，可以使用以下工具进行深入分析:

### 查找特定内容
- `find_draws_by_shader` - 按Shader名称查找DrawCall
- `find_draws_by_texture` - 按贴图名称查找DrawCall
- `find_draws_by_resource` - 按资源ID查找DrawCall

### 详细信息获取
- `get_draw_call_details` - 获取特定DrawCall的详细信息
- `get_shader_info` - 获取Shader信息和常量缓冲区值
- `get_pipeline_state` - 获取完整的管线状态
- `get_texture_info` - 获取贴图元数据
- `get_texture_saved` - 保存纹理为PNG到本地并返回路径
- `get_buffer_contents` - 读取Buffer内容

## 注意事项

1. **排除非渲染事件**: 引擎编辑器的UI绘制事件、调试工具事件等不属于应用渲染，不应计入性能分析
2. **关注实例化批次**: DrawIndexedInstanced的实例数达到上限（如Unity的511/1023）通常表示批次被拆分
3. **识别性能热点**: 通过耗时分析优先关注耗时最长的模块
4. **适配不同管线**: 不同引擎的Marker命名和管线结构差异很大，应以实际截帧内容为准，不要强行套用特定引擎的模板
5. **API差异**: 不同图形API（D3D11/D3D12/Vulkan/OpenGL）的事件类型和命名可能不同，但核心渲染流程是类似的

## 参考资源

- `references/urp_pipeline_structure.md` - Unity URP渲染管线结构参考（管线判断、渲染流程、多相机、常见Pass详解）—— 仅在确认为URP管线时参考
- `references/renderdoc_event_types.md` - RenderDoc事件类型参考（通用，适用于所有截帧）
- `assets/report_template.md` - 分析报告模板
