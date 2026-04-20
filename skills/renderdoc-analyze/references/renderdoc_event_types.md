# RenderDoc 事件类型参考

## 概述

RenderDoc记录的事件 (Event) 包含各种GPU操作,理解这些事件类型对分析渲染性能至关重要。

## 主要事件类型

### 1. DrawCall 相关事件

#### Draw
- **描述**: 基础绘制命令,非索引绘制
- **典型用途**: 简单几何体、程序生成的顶点
- **参数**:
  - `vertexCount`: 顶点数量
  - `instanceCount`: 实例数量 (通常为1)

#### DrawIndexed
- **描述**: 索引绘制,最常见的绘制类型
- **典型用途**: 大部分3D模型渲染
- **参数**:
  - `indexCount`: 索引数量
  - `instanceCount`: 实例数量 (通常为1)
  - `startIndex`: 起始索引偏移
  - `baseVertex`: 顶点偏移

**性能特点**:
- 每个DrawIndexed是一次独立的GPU提交
- 过多的DrawIndexed会增加CPU开销
- 索引数量直接关联到渲染的三角形数量

#### DrawIndexedInstanced
- **描述**: GPU实例化绘制,批量渲染相同Mesh
- **典型用途**: 大量重复物体 (植被、石头、草、树等)
- **参数**:
  - `indexCount`: 每个实例的索引数量
  - `instanceCount`: 实例数量 ⭐
  - `startIndex`: 起始索引
  - `baseVertex`: 基础顶点偏移
  - `startInstance`: 起始实例ID

**性能特点**:
- 单次DrawCall渲染多个相同Mesh
- 极大减少DrawCall数量
- **关键指标**: `instanceCount` 越高,批次效率越好
- Unity的实例数量上限通常为511或1023

**常见模式**:
```
DrawIndexedInstanced: indexCount=504, instanceCount=511  // 达到批次上限
DrawIndexedInstanced: indexCount=504, instanceCount=147  // 部分批次
DrawIndexedInstanced: indexCount=1236, instanceCount=10  // 小规模批次
```

#### DrawIndexedInstancedIndirect
- **描述**: GPU驱动的间接绘制
- **典型用途**: GPU Culling、程序化渲染
- **参数**:
  - 参数来自GPU Buffer,CPU不可见

#### DrawAuto / DrawTransformFeedback
- **描述**: 变换反馈绘制
- **典型用途**: 几何着色器输出、GPU粒子

### 2. Compute Shader 事件

#### Dispatch
- **描述**: 执行Compute Shader
- **典型用途**: GPU通用计算、粒子系统、后处理
- **参数**:
  - `groupCountX/Y/Z`: 线程组数量

**常见用途**:
- GPU Culling
- 粒子模拟
- 后处理效果 (Bloom、DOF等)
- 程序化生成

#### DispatchIndirect
- **描述**: 间接Dispatch,参数来自GPU Buffer
- **典型用途**: 动态工作负载

### 3. 资源操作事件

#### Clear
- **描述**: 清空渲染目标或深度缓冲
- **类型**:
  - `ClearRenderTargetView` - 清空颜色
  - `ClearDepthStencilView` - 清空深度/模板
- **性能影响**: 通常开销很小,但频繁清空会影响性能

#### Copy
- **描述**: 资源拷贝操作
- **类型**:
  - `CopyResource` - 完整资源拷贝
  - `CopySubresourceRegion` - 部分区域拷贝
  - `ResolveSubresource` - MSAA解析
- **性能影响**: 大尺寸拷贝会消耗带宽

#### Blit / StretchRect
- **描述**: 纹理复制和缩放
- **典型用途**: 后处理中的纹理传递

### 4. 状态设置事件

#### SetMarker / PushMarker / PopMarker
- **描述**: 调试标记,用于分组和标识渲染阶段
- **典型用途**: 
  - 标识渲染Pass名称
  - 层级组织渲染事件
- **性能影响**: 无 (纯调试信息)

#### SetRenderTargets
- **描述**: 设置渲染目标
- **参数**: 颜色目标和深度目标

#### SetViewport
- **描述**: 设置视口
- **参数**: 视口矩形

### 5. 其他事件

#### Present
- **描述**: 呈现到屏幕
- **含义**: 一帧渲染结束,交换缓冲区

#### BeginRenderPass / EndRenderPass
- **描述**: 渲染Pass边界 (Vulkan/Metal)
- **用途**: 标识RenderPass的开始和结束

## 引擎特定事件模式

### Unity引擎

#### QuadTreeBatchNode
- **描述**: Unity地形系统的分块渲染节点
- **典型用途**: Terrain渲染
- **参数**:
  - `indexCount`: 地形块的索引数量
  - `instanceCount`: 地形块实例数

#### Gizmos / Handles
- **描述**: Unity编辑器的Gizmo和Handle绘制
- **注意**: 这些是编辑器UI，不属于应用渲染

#### UIR.DrawChain
- **描述**: Unity编辑器UI渲染链
- **注意**: 编辑器自身UI，应在分析中排除

### Unreal引擎

#### 常见Marker
- `BasePass` - 基础渲染Pass
- `LightingPass` - 光照计算
- `PrePass` / `DepthPass` - 深度预渲染
- `Translucency` - 半透明渲染
- `PostProcessing` - 后处理
- `SlateUI` - Slate UI渲染（编辑器UI，应排除）

## 事件标志 (Flags)

RenderDoc为事件分配标志,用于快速识别类型:

- `Drawcall` - 绘制命令
- `Dispatch` - Compute Shader调度
- `Clear` - 清空操作
- `Copy` - 拷贝操作
- `Resolve` - MSAA解析
- `SetMarker` - 调试标记
- `PushMarker` - 标记组开始
- `PopMarker` - 标记组结束

## 性能分析要点

### 1. DrawCall数量

**健康基准**:
- 移动平台: < 300 DrawCalls
- PC平台: < 1000-2000 DrawCalls
- 高端PC: < 5000 DrawCalls

**优化方向**:
- 使用GPU Instancing (DrawIndexedInstanced)
- 静态批处理
- 动态批处理

### 2. 实例化批次

**理想状态**:
- `instanceCount` 接近上限 (511/1023)
- 相同Mesh的实例数尽可能多

**问题标志**:
- `instanceCount` 很小 (< 10)
- 大量DrawIndexedInstanced但实例数少

### 3. 索引数量

**含义**:
- `indexCount` ÷ 3 = 三角形数量
- 索引数量直接关联到GPU几何处理负载

**监控要点**:
- 单个DrawCall的索引数过大 (> 100万)
- 大量小DrawCall (< 100索引)

### 4. Dispatch模式

**健康模式**:
- Dispatch数量合理 (< 100)
- 线程组数量高效利用GPU

**问题标志**:
- 过多的小Dispatch
- 串行依赖的Dispatch链

## 典型渲染场景示例

### 场景1: 阴影渲染

```
PushMarker: "MainLightShadow"
├── PushMarker: "Cascade0"
│   ├── DrawIndexed: indexCount=12, instanceCount=1        (小物体)
│   ├── DrawIndexed: indexCount=188196, instanceCount=1    (大场景物体)
│   ├── DrawIndexedInstanced: indexCount=18018, instanceCount=10  (树木)
│   └── DrawIndexedInstanced: indexCount=504, instanceCount=511   (草丛,满批次)
├── PopMarker: "Cascade0"
├── PushMarker: "Cascade1"
│   └── ... (类似结构)
└── PopMarker: "Cascade1"
PopMarker: "MainLightShadow"
```

### 场景2: 后处理

```
PushMarker: "PostProcessing"
├── PushMarker: "Bloom"
│   ├── Draw: vertexCount=3 (全屏三角形,降采样)
│   ├── Draw: vertexCount=3 (模糊Pass1)
│   ├── Draw: vertexCount=3 (模糊Pass2)
│   └── Draw: vertexCount=3 (升采样和混合)
├── PopMarker: "Bloom"
├── PushMarker: "ColorGrading"
│   └── Draw: vertexCount=3 (LUT应用)
└── PopMarker: "ColorGrading"
PopMarker: "PostProcessing"
```

### 场景3: UI渲染

```
PushMarker: "UGUI.Rendering.RenderOverlays"
├── DrawIndexed: indexCount=6 (单个UI Quad)
├── DrawIndexed: indexCount=24 (4个Quad的批次)
└── DrawIndexed: indexCount=600 (大量合批的UI元素)
PopMarker: "UGUI.Rendering.RenderOverlays"
```

## 参考资源

- RenderDoc官方文档: https://renderdoc.org/docs/
- Unity性能优化指南: https://docs.unity3d.com/Manual/OptimizingGraphicsPerformance.html
