"""
Pipeline state service for RenderDoc.
"""

import renderdoc as rd

from ..utils import Parsers, Serializers, Helpers


class PipelineService:
    """Pipeline state service"""

    def __init__(self, ctx, invoke_fn):
        self.ctx = ctx
        self._invoke = invoke_fn

    def _get_pipeline_object(self, pipe, stage):
        """取当前 stage 对应的管线对象；计算着色器必须用计算管线对象，否则反汇编与取常量缓冲会失败"""
        if stage == rd.ShaderStage.Compute:
            return pipe.GetComputePipelineObject()
        return pipe.GetGraphicsPipelineObject()

    def get_shader_info(self, event_id, stage, cbuffer_slots=None, max_variables=64, include_disassembly=True):
        """Get shader information for a specific stage

        Args:
            cbuffer_slots: 只返回这些常量缓冲槽位的变量值（None 表示全部）
            max_variables: 每个常量缓冲最多返回多少个变量（避免响应过大）
            include_disassembly: 是否包含反汇编
        """
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"shader": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)

            pipe = controller.GetPipelineState()
            stage_enum = Parsers.parse_stage(stage)
            pipeline_object = self._get_pipeline_object(pipe, stage_enum)

            shader = pipe.GetShader(stage_enum)
            if shader == rd.ResourceId.Null():
                result["error"] = "No %s shader bound" % stage
                return

            entry = pipe.GetShaderEntryPoint(stage_enum)
            reflection = pipe.GetShaderReflection(stage_enum)

            shader_info = {
                "resource_id": str(shader),
                "entry_point": entry,
                "stage": stage,
            }

            # Get disassembly
            if include_disassembly:
                try:
                    targets = controller.GetDisassemblyTargets(True)
                    if targets:
                        # 原实现固定传 pipe.GetGraphicsPipelineObject()，compute 阶段会取不到反汇编
                        shader_info["disassembly"] = controller.DisassembleShader(pipeline_object, reflection, targets[0])
                except Exception as e:
                    shader_info["disassembly_error"] = str(e)

            # Get constant buffer info
            if reflection:
                shader_info["constant_buffers"] = self._get_cbuffer_info(
                    controller, pipe, reflection, stage_enum, cbuffer_slots, max_variables, pipeline_object
                )
                shader_info["resources"] = self._get_resource_bindings(reflection)

            result["shader"] = shader_info

        Helpers.replay_call(self._invoke, result, callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["shader"]

    def get_pipeline_state(self, event_id, include_cbuffer_variables=True):
        """Get full pipeline state at an event

        include_cbuffer_variables：是否返回常量缓冲的变量列表。
        常量缓冲可能包含数百个变量（名字多为 cb0_v1 这类无意义编号），
        关掉后能显著减小响应体积，需要变量值时请改用 get_shader_info。
        """
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"pipeline": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)

            pipe = controller.GetPipelineState()
            api = controller.GetAPIProperties().pipelineType

            pipeline_info = {
                "event_id": event_id,
                "api": str(api),
            }

            # Shader stages with detailed bindings
            stages = {}
            stage_list = Helpers.get_all_shader_stages()
            for stage in stage_list:
                shader = pipe.GetShader(stage)
                if shader != rd.ResourceId.Null():
                    stage_info = {
                        "resource_id": str(shader),
                        "entry_point": pipe.GetShaderEntryPoint(stage),
                    }

                    reflection = pipe.GetShaderReflection(stage)

                    stage_info["resources"] = self._get_stage_resources(
                        controller, pipe, stage, reflection
                    )
                    stage_info["uavs"] = self._get_stage_uavs(
                        controller, pipe, stage, reflection
                    )
                    stage_info["samplers"] = self._get_stage_samplers(
                        pipe, stage, reflection
                    )
                    stage_info["constant_buffers"] = self._get_stage_cbuffers(
                        controller, pipe, stage, reflection, include_cbuffer_variables
                    )

                    stages[str(stage)] = stage_info

            pipeline_info["shaders"] = stages

            # Viewport and scissor
            # 原实现调用 pipe.GetViewportScissor()，RenderDoc 1.46 的 PipeState 没有该方法，
            # 异常又被 except: pass 吞掉，导致输出里连 viewports 字段都不存在
            # 旧实现已统一挪到文件末尾的“修订记录”，避免横插在主流程中间影响阅读
            self._read_state(pipeline_info, "viewport_scissors", lambda: self._get_viewport_scissors(pipe))

            # Render targets
            # 原实现调用 pipe.GetOutputMerger()，RenderDoc 1.46 用 GetOutputTargets()/GetDepthTarget()
            # 旧实现见文件末尾“修订记录”
            self._read_state(pipeline_info, "render_targets", lambda: self._get_render_targets(controller, pipe))
            self._read_state(pipeline_info, "depth_target", lambda: self._get_depth_target(controller, pipe))

            # Input assembly
            # 原实现调用 pipe.GetIAState()，RenderDoc 1.46 用 GetPrimitiveTopology()
            # 旧实现见文件末尾“修订记录”
            self._read_state(pipeline_info, "input_assembly", lambda: self._get_input_assembly(pipe))

            # 混合与深度/模板状态（原实现完全没有输出这两块）
            self._read_state(pipeline_info, "blend", lambda: self._get_blend_state(pipe))
            self._read_state(pipeline_info, "depth_stencil", lambda: self._get_depth_stencil_state(pipe))

            result["pipeline"] = pipeline_info

        Helpers.replay_call(self._invoke, result, callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["pipeline"]

    def _read_state(self, pipeline_info, key, getter):
        """读取一项管线状态；失败时把异常写进 errors（原来 except: pass 会把问题藏起来）"""
        try:
            pipeline_info[key] = getter()
        except Exception as e:
            pipeline_info.setdefault("errors", {})[key] = str(e)

    # 视口/裁剪的索引上限；D3D 最多允许 16 个，原实现硬编码为 8 会静默丢掉后半部分
    MAX_INDEXED_STATES = 16

    def _collect_indexed(self, getter, describe, limit=None):
        """按索引收集状态：越界或无效即停止，索引 0 的异常向上抛"""
        if limit is None:
            limit = self.MAX_INDEXED_STATES
        items = []

        for index in range(limit):
            try:
                value = getter(index)
            except Exception:
                if index == 0:
                    raise
                break

            if value is None:
                break
            if index > 0 and not getattr(value, "enabled", True):
                break
            if index > 0 and getattr(value, "width", 1) == 0 and getattr(value, "height", 1) == 0:
                break

            items.append(describe(index, value))

        return items

    def _get_viewport_scissors(self, pipe):
        """获取视口与裁剪矩形"""
        viewports = self._collect_indexed(
            pipe.GetViewport,
            lambda index, v: {
                "index": index,
                "x": v.x,
                "y": v.y,
                "width": v.width,
                "height": v.height,
                "min_depth": v.minDepth,
                "max_depth": v.maxDepth,
                "enabled": bool(v.enabled),
            },
        )

        scissors = self._collect_indexed(
            pipe.GetScissor,
            lambda index, s: {
                "index": index,
                "x": s.x,
                "y": s.y,
                "width": s.width,
                "height": s.height,
                "enabled": bool(s.enabled),
            },
        )

        return {"viewports": viewports, "scissors": scissors}

    def _get_render_targets(self, controller, pipe):
        """获取颜色输出目标"""
        targets = []

        for index, target in enumerate(pipe.GetOutputTargets()):
            if target.resource == rd.ResourceId.Null():
                continue
            info = {"index": index, "resource_id": str(target.resource)}
            info.update(self._get_resource_details(controller, target.resource))
            targets.append(info)

        return targets

    def _get_depth_target(self, controller, pipe):
        """获取深度/模板输出目标"""
        target = pipe.GetDepthTarget()
        if target is None or target.resource == rd.ResourceId.Null():
            return None

        info = {"resource_id": str(target.resource)}
        info.update(self._get_resource_details(controller, target.resource))
        return info

    def _get_input_assembly(self, pipe):
        """获取输入装配状态（图元拓扑与图元重启）"""
        state = {"topology": str(pipe.GetPrimitiveTopology())}

        try:
            state["restart_enabled"] = bool(pipe.IsRestartEnabled())
            state["restart_index"] = pipe.GetRestartIndex()
        except Exception as e:
            state["restart_error"] = str(e)

        return state

    def _get_blend_state(self, pipe):
        """获取混合状态（支持每目标独立混合）"""
        state = {
            "independent_blending": bool(pipe.IsIndependentBlendingEnabled()),
            "blend_factor": [float(v) for v in pipe.GetBlendFactor()],
            "targets": [],
        }

        for index, blend in enumerate(pipe.GetColorBlends()):
            state["targets"].append(self._describe_blend(index, blend))

        return state

    def _describe_blend(self, index, blend):
        """把单个输出目标的混合状态转成可读字典"""
        info = {
            "index": index,
            "enabled": bool(blend.enabled),
            "write_mask": str(blend.writeMask),
            "logic_operation_enabled": bool(getattr(blend, "logicOperationEnabled", False)),
            "logic_operation": str(getattr(blend, "logicOperation", "")),
        }

        color_equation = getattr(blend, "colorBlend", None)
        if color_equation is not None:
            info["color_source"] = str(self._first_attr(color_equation, ["source", "srcColor"]))
            info["color_destination"] = str(self._first_attr(color_equation, ["destination", "dstColor"]))
            info["color_operation"] = str(self._first_attr(color_equation, ["operation", "colorOperation"]))

        alpha_equation = getattr(blend, "alphaBlend", None)
        if alpha_equation is not None:
            info["alpha_source"] = str(self._first_attr(alpha_equation, ["source", "srcAlpha"]))
            info["alpha_destination"] = str(self._first_attr(alpha_equation, ["destination", "dstAlpha"]))
            info["alpha_operation"] = str(self._first_attr(alpha_equation, ["operation", "alphaOperation"]))

        return info

    def _get_depth_stencil_state(self, pipe):
        """获取深度与模板状态"""
        depth = pipe.GetDepthTestState()

        state = {
            "depth_enable": bool(depth.depthEnable),
            "depth_writes": bool(depth.depthWrites),
            "depth_function": str(depth.depthFunction),
            "depth_bounds": bool(depth.depthBounds),
            "min_depth_bounds": depth.minDepthBounds,
            "max_depth_bounds": depth.maxDepthBounds,
            "stencil_enable": bool(pipe.IsStencilTestEnabled()),
        }

        try:
            faces = pipe.GetStencilFaces()
            if faces and len(faces) == 2:
                state["stencil_front"] = self._describe_stencil_face(faces[0])
                state["stencil_back"] = self._describe_stencil_face(faces[1])
        except Exception as e:
            state["stencil_error"] = str(e)

        return state

    def _describe_stencil_face(self, face):
        """把单个面的模板状态转成可读字典"""
        return {
            "compare_function": str(self._first_attr(face, ["function", "compareFunction"])),
            "reference": self._first_attr(face, ["reference"], 0),
            "compare_mask": self._first_attr(face, ["compareMask"], 0),
            "write_mask": self._first_attr(face, ["writeMask"], 0),
            "pass_operation": str(self._first_attr(face, ["passOperation"])),
            "fail_operation": str(self._first_attr(face, ["failOperation"])),
            "depth_fail_operation": str(self._first_attr(face, ["depthFailOperation"])),
        }

    def _first_attr(self, source, names, default=""):
        """按候选名依次取属性（RenderDoc 不同版本字段命名不一致，例如 BlendEquation 的 source/srcColor）"""
        for name in names:
            if hasattr(source, name):
                return getattr(source, name)
        return default

    def _get_stage_resources(self, controller, pipe, stage, reflection):
        """Get shader resource views (SRVs) for a stage"""
        return self._collect_stage_bindings(controller, pipe, stage, reflection, True)

    def _get_stage_uavs(self, controller, pipe, stage, reflection):
        """Get unordered access views (UAVs) for a stage"""
        return self._collect_stage_bindings(controller, pipe, stage, reflection, False)

    def _collect_stage_bindings(self, controller, pipe, stage, reflection, read_only):
        """收集某个 stage 的 SRV/UAV 绑定

        SRV 与 UAV 的描述结构一致（Bindpoint 数组 + 反射名映射），原先是两份几乎逐行相同的实现，
        这里统一处理，只在 mip/slice 与 element 字段上按视图类型区分。
        """
        items = []
        try:
            if read_only:
                bindings = pipe.GetReadOnlyResources(stage, False)
                reflection_list = reflection.readOnlyResources if reflection else None
            else:
                bindings = pipe.GetReadWriteResources(stage, False)
                reflection_list = reflection.readWriteResources if reflection else None

            name_map = {}
            if reflection_list:
                for res in reflection_list:
                    name_map[res.fixedBindNumber] = res.name

            for binding in bindings:
                if binding.descriptor.resource == rd.ResourceId.Null():
                    continue

                slot = binding.access.index
                info = {
                    "slot": slot,
                    "name": name_map.get(slot, ""),
                    "resource_id": str(binding.descriptor.resource),
                }
                info.update(self._get_resource_details(controller, binding.descriptor.resource))

                if read_only:
                    info["first_mip"] = binding.descriptor.firstMip
                    info["num_mips"] = binding.descriptor.numMips
                    info["first_slice"] = binding.descriptor.firstSlice
                    info["num_slices"] = binding.descriptor.numSlices
                else:
                    info["first_element"] = binding.descriptor.firstMip
                    info["num_elements"] = binding.descriptor.numMips

                items.append(info)
        except Exception as e:
            items.append({"error": str(e)})

        return items

    # 采样器描述字段表：(输出字段名, 源属性名, 转换函数)；不同后端/版本的字段可能缺失，缺失即跳过
    SAMPLER_FIELDS = (
        ("address_u", "addressU", str),
        ("address_v", "addressV", str),
        ("address_w", "addressW", str),
        ("filter", "filter", str),
        ("compare_function", "compareFunction", str),
        ("max_anisotropy", "maxAnisotropy", None),
        ("min_lod", "minLOD", None),
        ("max_lod", "maxLOD", None),
        ("mip_lod_bias", "mipLODBias", None),
    )

    def _get_stage_samplers(self, pipe, stage, reflection):
        """Get samplers for a stage"""
        samplers = []
        try:
            sampler_list = pipe.GetSamplers(stage, False)

            name_map = {}
            if reflection:
                for samp in reflection.samplers:
                    name_map[samp.fixedBindNumber] = samp.name

            for samp in sampler_list:
                slot = samp.access.index
                samp_info = {"slot": slot, "name": name_map.get(slot, "")}
                desc = samp.descriptor

                # 原实现为每个字段写一段 try/except AttributeError，改为按字段表统一处理
                for key, attr_name, caster in self.SAMPLER_FIELDS:
                    if hasattr(desc, attr_name):
                        value = getattr(desc, attr_name)
                        samp_info[key] = caster(value) if caster else value

                border_color = getattr(desc, "borderColor", None)
                if border_color is not None:
                    try:
                        samp_info["border_color"] = [border_color[0], border_color[1], border_color[2], border_color[3]]
                    except (TypeError, IndexError):
                        pass

                samplers.append(samp_info)
        except Exception as e:
            samplers.append({"error": str(e)})

        return samplers

    def _get_stage_cbuffers(self, controller, pipe, stage, reflection, include_variables=True):
        """Get constant buffers for a stage from shader reflection"""
        cbuffers = []
        try:
            if not reflection:
                return cbuffers

            for index, cb in enumerate(reflection.constantBlocks):
                # slot 统一为反射索引（从 0 开始），与 get_shader_info 的 cbuffer_slots 保持一致；
                # 原实现这里用 bindPoint，导致两个工具对“槽位”的定义不同
                cb_info = {
                    "slot": index,
                    "bind_point": cb.bindPoint if hasattr(cb, 'bindPoint') else cb.fixedBindNumber,
                    "name": cb.name,
                    "byte_size": cb.byteSize,
                    "variable_count": len(cb.variables) if cb.variables else 0,
                    "variables": [],
                }
                if include_variables and cb.variables:
                    for var in cb.variables:
                        cb_info["variables"].append({
                            "name": var.name,
                            "byte_offset": var.byteOffset,
                            "type": str(var.type.name) if var.type else "",
                        })
                cbuffers.append(cb_info)

        except Exception as e:
            cbuffers.append({"error": str(e)})

        return cbuffers

    def _get_resource_details(self, controller, resource_id):
        """Get details about a resource (texture or buffer)"""
        details = {}

        try:
            resource_name = self.ctx.GetResourceName(resource_id)
            if resource_name:
                details["resource_name"] = resource_name
        except Exception:
            pass

        for tex in controller.GetTextures():
            if tex.resourceId == resource_id:
                details["type"] = "texture"
                details["width"] = tex.width
                details["height"] = tex.height
                details["depth"] = tex.depth
                details["array_size"] = tex.arraysize
                details["mip_levels"] = tex.mips
                details["format"] = str(tex.format.Name())
                details["dimension"] = str(tex.type)
                details["msaa_samples"] = tex.msSamp
                return details

        for buf in controller.GetBuffers():
            if buf.resourceId == resource_id:
                details["type"] = "buffer"
                details["length"] = buf.length
                return details

        return details

    def _get_cbuffer_info(self, controller, pipe, reflection, stage, slots=None, max_variables=64, pipeline_object=None):
        """Get constant buffer information and values

        注意：RenderDoc 1.46 的 PipeState 没有 GetConstantBuffer()，取绑定必须用 GetConstantBlock(stage, index, arrayIndex)
        pipeline_object：计算着色器必须传计算管线对象，为空时按 stage 自动推断
        """
        cbuffers = []

        for i, cb in enumerate(reflection.constantBlocks):
            cb_info = {
                "name": cb.name,
                "slot": i,
                "size": cb.byteSize,
                "variables": [],
            }

            if slots is not None and i not in slots:
                cb_info["skipped"] = True
                cbuffers.append(cb_info)
                continue

            try:
                bind = pipe.GetConstantBlock(stage, i, 0)
                descriptor = bind.descriptor
                if descriptor.resource != rd.ResourceId.Null():
                    # 原实现固定传 pipe.GetGraphicsPipelineObject()，compute 阶段会取不到变量值
                    target_pipeline = pipeline_object if pipeline_object is not None else self._get_pipeline_object(pipe, stage)
                    variables = controller.GetCBufferVariableContents(
                        target_pipeline,
                        reflection.resourceId,
                        stage,
                        reflection.entryPoint,
                        i,
                        descriptor.resource,
                        descriptor.byteOffset,
                        cb.byteSize,
                    )
                    serialized = Serializers.serialize_variables(variables)
                    cb_info["variable_count"] = len(serialized)
                    if max_variables and len(serialized) > max_variables:
                        cb_info["truncated"] = True
                        serialized = serialized[:max_variables]
                    cb_info["variables"] = serialized
            except Exception as e:
                # 出错时把原因带出去，不要静默吞掉，否则调用方无法判断是"没有值"还是"读失败"
                cb_info["error"] = str(e)

            cbuffers.append(cb_info)

        return cbuffers

    # ShaderResource 的资源类型字段名各版本不一致（1.46 里没有 resType），按候选依次尝试
    RESOURCE_TYPE_FIELDS = ("resType", "resourceType", "type")

    def _get_resource_bindings(self, reflection):
        """Get shader resource bindings（只读与读写资源结构相同，统一处理，不再吞掉异常）"""
        resources = []

        bindings = (
            (getattr(reflection, "readOnlyResources", None), "ReadOnly"),
            (getattr(reflection, "readWriteResources", None), "ReadWrite"),
        )

        for binding_list, access in bindings:
            if not binding_list:
                continue
            for res in binding_list:
                info = {
                    "name": res.name,
                    "binding": res.fixedBindNumber,
                    "access": access,
                }

                # 原实现直接读 res.resType，异常被 except: pass 吞掉，导致 resources 永远是空数组；
                # 取不到类型时不再输出该字段，而不是留个空串让人误以为读到了值
                res_type = self._first_attr(res, self.RESOURCE_TYPE_FIELDS, None)
                if res_type is not None:
                    info["type"] = str(res_type)

                resources.append(info)

        return resources


# ==================== 修订记录 ====================
# 以下为 RenderDoc 1.46 适配前的旧实现，已停用，仅保留备查（原来横插在 get_pipeline_state 主流程中间）。
#
# 1) 视口与裁剪：旧实现调用 pipe.GetViewportScissor()，1.46 的 PipeState 没有该方法，
#    异常又被 except: pass 吞掉，结果连 viewports 字段都不会出现。
# try:
#     vp_scissor = pipe.GetViewportScissor()
#     if vp_scissor:
#         viewports = []
#         for v in vp_scissor.viewports:
#             viewports.append(
#                 {
#                     "x": v.x,
#                     "y": v.y,
#                     "width": v.width,
#                     "height": v.height,
#                     "min_depth": v.minDepth,
#                     "max_depth": v.maxDepth,
#                 }
#             )
#         pipeline_info["viewports"] = viewports
# except Exception:
#     pass
#
# 2) 渲染目标：旧实现调用 pipe.GetOutputMerger()，1.46 改为 GetOutputTargets()/GetDepthTarget()。
# try:
#     om = pipe.GetOutputMerger()
#     if om:
#         rts = []
#         for i, rt in enumerate(om.renderTargets):
#             if rt.resourceId != rd.ResourceId.Null():
#                 rts.append({"index": i, "resource_id": str(rt.resourceId)})
#         pipeline_info["render_targets"] = rts
#
#         if om.depthTarget.resourceId != rd.ResourceId.Null():
#             pipeline_info["depth_target"] = str(om.depthTarget.resourceId)
# except Exception:
#     pass
#
# 3) 输入装配：旧实现调用 pipe.GetIAState()，1.46 改为 GetPrimitiveTopology()。
# try:
#     ia = pipe.GetIAState()
#     if ia:
#         pipeline_info["input_assembly"] = {"topology": str(ia.topology)}
# except Exception:
#     pass
