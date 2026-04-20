# URP 渲染管线结构参考

## 概述

Universal Render Pipeline (URP) 是Unity官方的轻量级可编程渲染管线。本文档列举URP在RenderDoc截帧中的典型渲染流程、Marker层级结构，以及分析时的关键注意点。

## 如何判断是URP管线

### 关键Marker标识

在RenderDoc截帧中，**URP管线的核心标识是 `UniversalRenderPipeline` 开头的Marker**:

```
PushMarker: "UniversalRenderPipeline.RenderSingleCameraInternal"
```

- 如果截帧的顶层Marker中存在 `UniversalRenderPipeline` 相关名称，即可确认是URP管线
- 内置管线(Built-in)不会有此Marker，而是直接以 `Camera.Render` 等形式出现
- HDRP管线会使用 `HDRenderPipeline` 开头的Marker

### 常见的URP顶层Marker

| Marker名称 | 含义 |
|---|---|
| `UniversalRenderPipeline.RenderSingleCameraInternal` | URP渲染单个相机的完整流程 |
| `UniversalRenderPipeline.RenderCameraStack` | URP渲染相机栈（Base + Overlay） |
| `UGUI.Rendering.RenderOverlays` | UGUI覆盖渲染（Screen Space - Overlay模式的UI） |

## URP 默认渲染流程（Forward渲染路径）

以下是URP Forward渲染路径下，单个相机的典型渲染顺序：

```
UniversalRenderPipeline.RenderSingleCameraInternal
├── InitRenderGraphFrame                     // 初始化RenderGraph帧数据
├── RecordAndExecuteRenderGraph              // 录制并执行RenderGraph
│   ├── MainLightShadow                      // 主光源阴影贴图
│   │   ├── Cascade 0                        // 级联阴影第0级
│   │   ├── Cascade 1                        // 级联阴影第1级
│   │   ├── Cascade 2                        // 级联阴影第2级
│   │   └── Cascade 3                        // 级联阴影第3级
│   ├── AdditionalLightsShadow              // 额外光源阴影（如果有Point/Spot光）
│   ├── DepthPrepass                         // 深度预渲染（可选，取决于设置）
│   ├── DepthNormalPrepass                   // 深度+法线预渲染（SSAO等需要）
│   ├── DrawOpaqueObjects                    // 绘制不透明物体
│   ├── DrawSkybox                           // 绘制天空盒
│   ├── CopyDepthPass                        // 拷贝深度缓冲（用于透明物体深度采样）
│   ├── CopyColorPass                        // 拷贝颜色缓冲（用于折射等效果）
│   ├── DrawTransparentObjects               // 绘制半透明物体
│   ├── PostProcessing                       // 后处理（Bloom、Tonemapping等）
│   │   ├── SetupPostProcessing
│   │   ├── Bloom                            // 泛光
│   │   │   ├── BloomPrefilter
│   │   │   ├── BloomBlurH / BloomBlurV      // 高斯模糊（多次迭代）
│   │   │   └── BloomUpsample
│   │   ├── UberPost                         // 合并后处理（色调映射、色彩校正等）
│   │   └── FinalBlit                        // 最终Blit到屏幕
│   └── InvokeOnRenderObjectCallbacks        // OnRenderObject回调（如果有）
└── FinishRenderGraphRendering               // 结束RenderGraph渲染
```

## URP 默认渲染流程（Deferred渲染路径）

Deferred路径与Forward路径的主要区别在GBuffer阶段：

```
UniversalRenderPipeline.RenderSingleCameraInternal
├── RecordAndExecuteRenderGraph
│   ├── MainLightShadow                      // 主光源阴影
│   ├── DepthPrepass / DepthNormalPrepass     // 深度预渲染
│   ├── GBufferPass                          // GBuffer写入（漫反射、法线、高光等）
│   │   └── DrawOpaqueObjects                // 在GBuffer阶段绘制不透明物体
│   ├── CopyDepthPass                        // 拷贝深度
│   ├── DeferredLighting                     // 延迟光照计算
│   │   ├── StencilVolume                    // 光源模板体（Point/Spot光源）
│   │   └── DeferredPass                     // 延迟光照Pass
│   ├── DrawSkybox                           // 天空盒
│   ├── CopyColorPass                        // 拷贝颜色
│   ├── DrawTransparentObjects               // 半透明物体（仍使用Forward）
│   ├── PostProcessing                       // 后处理
│   └── FinalBlit
└── FinishRenderGraphRendering
```

**注意**: Deferred路径下半透明物体仍然使用Forward方式渲染，这是因为延迟渲染无法处理半透明混合。

## URP 多相机与Camera Stack

### Camera Stack 机制

URP支持Camera Stack（相机栈），由一个**Base Camera**和多个**Overlay Camera**组成：

```
UniversalRenderPipeline.RenderCameraStack
├── UniversalRenderPipeline.RenderSingleCameraInternal (Base Camera)
│   ├── MainLightShadow
│   ├── DrawOpaqueObjects
│   ├── DrawSkybox
│   ├── DrawTransparentObjects
│   └── (注意: 此处没有PostProcessing！)
├── UniversalRenderPipeline.RenderSingleCameraInternal (Overlay Camera 1)
│   ├── DrawOpaqueObjects
│   └── DrawTransparentObjects
├── UniversalRenderPipeline.RenderSingleCameraInternal (Overlay Camera 2 - 最后一个)
│   ├── DrawOpaqueObjects
│   ├── DrawTransparentObjects
│   ├── PostProcessing                       // ⭐ 后处理在最后一个Overlay相机执行
│   └── FinalBlit
```

### 关键注意点

1. **后处理只在Camera Stack的最后一个相机执行**
   - 如果只有Base Camera（无Overlay），后处理在Base Camera执行
   - 如果有Overlay Camera，后处理推迟到最后一个Overlay Camera执行
   - 中间的相机不会执行后处理，即使勾选了Post Processing选项

2. **Overlay Camera不渲染天空盒和阴影**
   - Overlay Camera不会单独生成阴影贴图，共享Base Camera的阴影数据
   - Overlay Camera不绘制天空盒（直接叠加在Base Camera画面上）

3. **多个Base Camera的情况**
   - 场景中可以有多个独立的Base Camera
   - 每个Base Camera独立渲染，各自拥有自己的Camera Stack
   - 会出现多个 `RenderSingleCameraInternal` 或 `RenderCameraStack` 顶层Marker

4. **分析时如何区分不同相机**
   - 同一个 `RenderCameraStack` 下的多个 `RenderSingleCameraInternal` 代表同一个Stack中的不同相机
   - 可以通过渲染内容（DrawCall中的对象）来区分不同相机的用途（如：主场景相机、UI相机、小地图相机等）

## 编辑器截帧 vs 真机截帧

### 编辑器截帧的额外内容

在Unity编辑器中截帧时，RenderDoc会捕获到编辑器自身的渲染事件：

```
全部事件
├── UIR.DrawChain (编辑器UI)              ❌ 排除
├── Gizmos.Draw (编辑器Gizmo)             ❌ 排除
├── Handles (编辑器Handle)                ❌ 排除
├── SceneView (场景视图渲染)               ❌ 排除
├── UniversalRenderPipeline.xxx           ✅ 游戏渲染
└── UGUI.Rendering.RenderOverlays         ✅ 游戏UI
```

**关键原则**: 分析时必须排除 `UniversalRenderPipeline` 之前的所有编辑器事件。

### 真机截帧

真机截帧（Android/iOS/PC Build）不会包含编辑器事件，截帧内容更干净：
- 直接以 `UniversalRenderPipeline` 相关Marker开始
- 不会有 `UIR.DrawChain`、`Gizmos` 等编辑器内容
- 性能数据更接近真实运行情况

## URP RenderGraph（Unity 6+）

Unity 6 开始URP全面使用RenderGraph系统，截帧中的Marker结构会有所变化：

### RenderGraph模式的特征

```
UniversalRenderPipeline.RenderSingleCameraInternal
├── InitRenderGraphFrame
├── RecordAndExecuteRenderGraph              // ⭐ RenderGraph的标志性Marker
│   ├── SetupCameraProperties
│   ├── MainLightShadowCasterPass
│   ├── BuildGPULightListPass               // GPU光源列表构建（Forward+）
│   ├── DrawOpaqueForwardPass
│   ├── DrawSkyboxPass
│   ├── CopyDepthPass
│   ├── DrawTransparentForwardPass
│   ├── PostProcessPass
│   └── FinalBlitPass
└── FinishRenderGraphRendering
```

### 与传统URP的区别

| 区别项 | 传统URP | RenderGraph URP |
|---|---|---|
| 外层Marker | 直接列出各Pass | 包裹在 `RecordAndExecuteRenderGraph` 下 |
| Pass命名 | `DrawOpaqueObjects` | `DrawOpaqueForwardPass` |
| 资源管理 | 手动管理RT | 自动生命周期管理 |
| Forward+ | 不支持 | 支持（`BuildGPULightListPass`） |
| NativeRenderPass | 不支持 | 支持（合并兼容的SubPass） |

### Forward+ 渲染路径（Unity 6 默认）

Unity 6 的URP默认使用Forward+渲染路径，其特点：

```
RecordAndExecuteRenderGraph
├── DepthPrepass                             // 必须的深度预渲染
├── BuildGPULightListPass                    // ⭐ Forward+的标志：GPU光源列表
├── DrawOpaqueForwardPass                    // 前向渲染不透明物体
├── ...
```

- **`BuildGPULightListPass`** 是Forward+的标志性Pass，传统Forward没有这个Pass
- Forward+通过GPU光源列表支持大量实时光源，不需要切换到Deferred
- 仍然保留了Forward渲染的半透明物体优势

## 常见Pass详解与性能关注点

### MainLightShadow（主光源阴影）

- **作用**: 为场景中的主方向光生成级联阴影贴图(Cascaded Shadow Map)
- **性能关注**: 
  - 级联数量（1~4级）直接影响DrawCall数量，每一级都要重新渲染投影物体
  - 阴影分辨率越高，GPU填充开销越大
  - 投影物体过多会导致阴影Pass DrawCall暴增
- **优化方向**: 减少级联数、降低阴影距离、使用Shadow Caster LOD

### AdditionalLightsShadow（额外光源阴影）

- **作用**: 为Point Light和Spot Light生成阴影
- **性能关注**:
  - 每个需要阴影的额外光源都会产生额外的DrawCall
  - Point Light需要渲染6个面（CubeMap），开销特别大
- **优化方向**: 严格控制需要投射阴影的额外光源数量

### DepthPrepass / DepthNormalPrepass

- **作用**: 预渲染场景深度（和法线），供后续Pass使用
- **何时出现**: 
  - SSAO开启时需要DepthNormal
  - 需要深度纹理时出现DepthPrepass
  - Deferred模式下通常需要
- **性能关注**: 会额外绘制一遍不透明物体，增加DrawCall

### DrawOpaqueObjects / DrawOpaqueForwardPass

- **作用**: 渲染所有不透明物体（RenderQueue 0~2500）
- **性能关注**: 通常是DrawCall最密集的阶段
- **渲染顺序**: 从前到后(Front-to-Back)排序，利用Early-Z减少OverDraw

### DrawTransparentObjects / DrawTransparentForwardPass

- **作用**: 渲染半透明物体（RenderQueue 2501~5000）
- **性能关注**:
  - 从后到前(Back-to-Front)排序，无法利用Early-Z
  - OverDraw是半透明物体的主要性能问题
  - 粒子特效通常在此阶段渲染
- **优化方向**: 减少半透明物体面积、降低粒子数量

### CopyDepthPass / CopyColorPass

- **作用**: 将当前深度/颜色缓冲拷贝一份供Shader采样
- **何时出现**:
  - Shader中使用了 `_CameraDepthTexture`（如软粒子、水面折射）
  - Shader中使用了 `_CameraOpaqueTexture`（如折射、扭曲效果）
- **性能关注**: 全屏拷贝操作，在高分辨率下带宽开销大

### PostProcessing

- **作用**: 屏幕后处理效果
- **常见子Pass**:
  - `Bloom` - 泛光（多次降采样和模糊）
  - `UberPost` - 合并后处理（Tonemapping、Color Grading、Vignette等）
  - `FXAA/SMAA` - 抗锯齿
  - `MotionBlur` - 运动模糊
  - `DepthOfField` - 景深
- **性能关注**: 
  - 后处理是纯像素操作，分辨率越高开销越大
  - Bloom的迭代次数影响模糊质量和性能
  - 景深(DOF)通常是后处理中开销最大的效果

### FinalBlit

- **作用**: 将最终渲染结果Blit到屏幕后缓冲
- **性能关注**: 通常开销很小，但如果涉及分辨率缩放(Dynamic Resolution)会有额外开销

## UGUI渲染

### Screen Space - Overlay 模式

UGUI的Overlay模式UI不在URP管线内渲染，而是在管线执行完毕后单独绘制：

```
UniversalRenderPipeline.RenderSingleCameraInternal   // URP管线
UGUI.Rendering.RenderOverlays                         // UI在管线之外
```

- Overlay UI不受后处理影响
- Overlay UI有独立的DrawCall，不与场景渲染合批

### Screen Space - Camera 模式

Camera模式的UI在指定相机的渲染流程内绘制：

```
UniversalRenderPipeline.RenderSingleCameraInternal
├── DrawOpaqueObjects
├── DrawTransparentObjects
├── Canvas.RenderSubBatch (UI在透明阶段渲染)          // ⭐ UI在管线内
├── PostProcessing                                     // UI会被后处理影响
└── FinalBlit
```

- Camera模式的UI会被后处理影响（如Bloom会让UI发光）
- 通常需要配合Camera Stack使用，将UI放在单独的Overlay Camera避免被后处理影响

### World Space 模式

World Space的UI作为场景中的普通物体渲染，出现在 `DrawTransparentObjects` 中。

## 分析时的常见陷阱

1. **不要混淆编辑器DrawCall和游戏DrawCall**
   - 编辑器截帧中 `UniversalRenderPipeline` 之前的事件都是编辑器的
   - 统计DrawCall时务必排除编辑器事件

2. **注意RenderScale的影响**
   - URP支持RenderScale（渲染分辨率缩放）
   - 实际渲染分辨率可能与屏幕分辨率不同
   - 在分析RT尺寸时要考虑RenderScale

3. **SRP Batcher的影响**
   - URP默认开启SRP Batcher
   - SRP Batcher不减少DrawCall数量，但减少了SetPass Call
   - 在RenderDoc中DrawCall数量看起来可能很多，但实际CPU开销可能不高

4. **自定义RenderFeature/RenderPass**
   - 项目中可能添加了自定义的ScriptableRenderPass
   - 这些自定义Pass会出现在截帧中，Marker名称取决于开发者的命名
   - 分析时遇到不认识的Marker，可能是项目自定义的渲染Pass

5. **NativeRenderPass合并**
   - Unity 6+ 的RenderGraph可能将多个兼容的Pass合并为一个NativeRenderPass
   - 合并后在RenderDoc中可能看到fewer pass transitions
   - 这是性能优化的表现，不是异常

6. **多相机后处理位置**
   - Camera Stack中只有最后一个相机执行后处理
   - 如果在中间相机看不到PostProcessing的Marker，这是正常行为
   - 如果需要每个相机独立后处理，需要使用多个独立的Base Camera

## 参考资源

- Unity URP官方文档: https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@latest
- URP Camera Stack文档: https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@latest/index.html?subfolder=/manual/camera-stacking.html
- URP RenderGraph文档: https://docs.unity3d.com/6000.0/Documentation/Manual/urp/render-graph.html
