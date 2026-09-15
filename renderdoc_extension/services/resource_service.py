"""
Resource information service for RenderDoc.
"""

import base64
import os
import traceback
from datetime import datetime

import renderdoc as rd

from ..utils import Parsers, Helpers


class ResourceService:
    """Resource information service"""

    def __init__(self, ctx, invoke_fn):
        self.ctx = ctx
        self._invoke = invoke_fn

    def _find_texture_by_id(self, controller, resource_id):
        """Find texture by resource ID

        用数字形式比较：rd.ResourceId() 构造出的对象与真实 ResourceId 不相等，
        一旦用它做比较会出现"永远找不到"或"匹配到 Null 资源"两类错误。
        """
        target_id = Parsers.numeric_id(resource_id)
        for tex in controller.GetTextures():
            if Parsers.numeric_id(tex.resourceId) == target_id:
                return tex
        return None

    def _resolve_subresource(self, tex_desc, mip, slice, sample, depth_slice):
        """校验 mip/slice/sample/depth_slice 并计算该 mip 下的尺寸

        返回 (错误信息, mip_width, mip_height, mip_depth, is_3d)；错误信息为 None 表示校验通过。
        原先 get_texture_raw 与 get_texture_saved 各写了一份逐行相同的校验，这里统一实现。
        """
        if mip < 0 or mip >= tex_desc.mips:
            return ("Invalid mip level %d (texture has %d mips)" % (mip, tex_desc.mips), 0, 0, 0, False)

        max_slices = tex_desc.arraysize
        if tex_desc.cubemap:
            max_slices = tex_desc.arraysize * 6
        if slice < 0 or (max_slices > 1 and slice >= max_slices):
            return ("Invalid slice %d (texture has %d slices)" % (slice, max_slices), 0, 0, 0, False)

        if sample < 0 or (tex_desc.msSamp > 1 and sample >= tex_desc.msSamp):
            return ("Invalid sample %d (texture has %d samples)" % (sample, tex_desc.msSamp), 0, 0, 0, False)

        mip_width = max(1, tex_desc.width >> mip)
        mip_height = max(1, tex_desc.height >> mip)
        mip_depth = max(1, tex_desc.depth >> mip)
        is_3d = tex_desc.depth > 1

        if depth_slice is not None:
            if not is_3d:
                return ("depth_slice can only be used with 3D textures", 0, 0, 0, is_3d)
            if depth_slice < 0 or depth_slice >= mip_depth:
                return ("Invalid depth_slice %d (texture has %d depth at mip %d)" % (depth_slice, mip_depth, mip), 0, 0, 0, is_3d)

        return (None, mip_width, mip_height, mip_depth, is_3d)

    def get_buffer_contents(self, resource_id, offset=0, length=0):
        """Get buffer data"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            # Parse resource ID
            try:
                target_id = Parsers.numeric_id(resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            # Find buffer（原实现用 parse_resource_id 构造的对象比较，恒不相等，导致永远报 Buffer not found）
            buf_desc = None
            for buf in controller.GetBuffers():
                if Parsers.numeric_id(buf.resourceId) == target_id:
                    buf_desc = buf
                    break

            if not buf_desc:
                result["error"] = "Buffer not found: %s" % resource_id
                return

            # Get data
            actual_length = length if length > 0 else buf_desc.length
            data = controller.GetBufferData(buf_desc.resourceId, offset, actual_length)

            result["data"] = {
                "resource_id": resource_id,
                "length": len(data),
                "total_size": buf_desc.length,
                "offset": offset,
                "content_base64": base64.b64encode(data).decode("ascii"),
            }

        Helpers.replay_call(self._invoke, result, callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]

    def get_texture_info(self, resource_id):
        """Get texture metadata"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"texture": None, "error": None}

        def callback(controller):
            # 原实现用一层大 try 包住并回传 traceback，非法 ID 时会把整段堆栈抛给调用方；
            # 异常现在由 replay_call 统一兜底，这里只需要区分"ID 非法"与"纹理不存在"。
            try:
                tex_desc = self._find_texture_by_id(controller, resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            if not tex_desc:
                result["error"] = "Texture not found: %s" % resource_id
                return

            result["texture"] = {
                "resource_id": resource_id,
                "width": tex_desc.width,
                "height": tex_desc.height,
                "depth": tex_desc.depth,
                "array_size": tex_desc.arraysize,
                "mip_levels": tex_desc.mips,
                "format": str(tex_desc.format.Name()),
                "dimension": str(tex_desc.type),
                "msaa_samples": tex_desc.msSamp,
                "byte_size": tex_desc.byteSize,
            }

        Helpers.replay_call(self._invoke, result, callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["texture"]

    def get_texture_raw(self, resource_id, mip=0, slice=0, sample=0, depth_slice=None):
        """Get texture raw pixel data (Base64 encoded)."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            try:
                tex_desc = self._find_texture_by_id(controller, resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            if not tex_desc:
                result["error"] = "Texture not found: %s" % resource_id
                return

            # 参数校验与 mip 尺寸计算统一走 _resolve_subresource（原为 raw/saved 两份重复实现）
            error, mip_width, mip_height, mip_depth, is_3d = self._resolve_subresource(tex_desc, mip, slice, sample, depth_slice)
            if error:
                result["error"] = error
                return

            # Create subresource specification
            sub = rd.Subresource()
            sub.mip = mip
            sub.slice = slice
            sub.sample = sample

            # Get texture data
            try:
                data = controller.GetTextureData(tex_desc.resourceId, sub)
            except Exception as e:
                result["error"] = "Failed to get texture data: %s" % str(e)
                return

            # Extract depth slice for 3D textures if requested
            output_depth = mip_depth
            if is_3d and depth_slice is not None:
                total_size = len(data)
                bytes_per_slice = total_size // mip_depth
                slice_start = depth_slice * bytes_per_slice
                slice_end = slice_start + bytes_per_slice
                data = data[slice_start:slice_end]
                output_depth = 1

            result["data"] = {
                "resource_id": resource_id,
                "width": mip_width,
                "height": mip_height,
                "depth": output_depth,
                "mip": mip,
                "slice": slice,
                "sample": sample,
                "depth_slice": depth_slice,
                "format": str(tex_desc.format.Name()),
                "dimension": str(tex_desc.type),
                "is_3d": is_3d,
                "total_depth": mip_depth if is_3d else 1,
                "data_length": len(data),
                "content_base64": base64.b64encode(data).decode("ascii"),
            }

        Helpers.replay_call(self._invoke, result, callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]

    def get_texture_saved(self, resource_id, mip=0, slice=0, sample=0, depth_slice=None):
        """Save texture as PNG file and return file path."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            try:
                tex_desc = self._find_texture_by_id(controller, resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            if not tex_desc:
                result["error"] = "Texture not found: %s" % resource_id
                return

            # 验证参数（与 get_texture_raw 共用同一份实现）
            error, mip_width, mip_height, mip_depth, is_3d = self._resolve_subresource(tex_desc, mip, slice, sample, depth_slice)
            if error:
                result["error"] = error
                return

            # 确定扩展路径和temp目录
            try:
                # 本文件位于 <扩展目录>/services/resource_service.py，上溯两级即扩展根目录
                # 原实现先遍历 sys.path 找 "renderdoc_mcp_bridge"，但下面的兜底分支本就等价且更可靠
                # import sys
                # extension_dir = None
                # if hasattr(sys, "path"):
                #     for p in sys.path:
                #         if "renderdoc_mcp_bridge" in p:
                #             extension_dir = p
                #             break
                # if extension_dir is None:
                #     extension_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                extension_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

                temp_dir = os.path.join(extension_dir, "temp")
                os.makedirs(temp_dir, exist_ok=True)

                # 生成文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                numeric_id = Parsers.extract_numeric_id(resource_id)
                filename = "texture_%s_mip%d" % (numeric_id, mip)
                if slice > 0:
                    filename += "_slice%d" % slice
                if sample > 0:
                    filename += "_sample%d" % sample
                if depth_slice is not None:
                    filename += "_depth%d" % depth_slice
                filename += "_%s.png" % timestamp
                
                file_path = os.path.join(temp_dir, filename)

                # 使用RenderDoc的SaveTexture API保存为PNG
                save_data = rd.TextureSave()
                save_data.resourceId = tex_desc.resourceId
                save_data.mip = mip
                
                # 设置slice参数 - 使用Subresource对象
                slice_mapping = rd.TextureSliceMapping()
                slice_mapping.sliceIndex = depth_slice if (is_3d and depth_slice is not None) else slice
                save_data.slice = slice_mapping
                
                # 设置sample参数 - 使用CompType对象或默认值
                comp_mapping = rd.TextureComponentMapping()
                save_data.comp = comp_mapping
                save_data.sample.mapToArray = False
                save_data.sample.sampleIndex = sample if sample < tex_desc.msSamp else 0

                # 保存为PNG
                controller.SaveTexture(save_data, file_path)

                # 返回文件信息
                file_size = os.path.getsize(file_path)
                output_depth = 1 if (is_3d and depth_slice is not None) else mip_depth
                
                result["data"] = {
                    "resource_id": resource_id,
                    "width": mip_width,
                    "height": mip_height,
                    "depth": output_depth,
                    "mip": mip,
                    "slice": slice,
                    "sample": sample,
                    "depth_slice": depth_slice,
                    "format": str(tex_desc.format.Name()),
                    "dimension": str(tex_desc.type),
                    "file_path": file_path,
                    "file_url": "file:///%s" % file_path.replace(os.sep, '/'),
                    "file_size": file_size,
                    "filename": filename,
                }

            except Exception as e:
                result["error"] = "Failed to save texture: %s\n%s" % (str(e), traceback.format_exc())
                return

        Helpers.replay_call(self._invoke, result, callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]
