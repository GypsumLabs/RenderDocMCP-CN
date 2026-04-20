"""
Resource information service for RenderDoc.
"""

import base64
import os
from datetime import datetime

import renderdoc as rd

from ..utils import Parsers


class ResourceService:
    """Resource information service"""

    def __init__(self, ctx, invoke_fn):
        self.ctx = ctx
        self._invoke = invoke_fn

    def _find_texture_by_id(self, controller, resource_id):
        """Find texture by resource ID"""
        target_id = Parsers.extract_numeric_id(resource_id)
        for tex in controller.GetTextures():
            tex_id_str = str(tex.resourceId)
            tex_id = Parsers.extract_numeric_id(tex_id_str)
            if tex_id == target_id:
                return tex
        return None

    def get_buffer_contents(self, resource_id, offset=0, length=0):
        """Get buffer data"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            # Parse resource ID
            try:
                rid = Parsers.parse_resource_id(resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            # Find buffer
            buf_desc = None
            for buf in controller.GetBuffers():
                if buf.resourceId == rid:
                    buf_desc = buf
                    break

            if not buf_desc:
                result["error"] = "Buffer not found: %s" % resource_id
                return

            # Get data
            actual_length = length if length > 0 else buf_desc.length
            data = controller.GetBufferData(rid, offset, actual_length)

            result["data"] = {
                "resource_id": resource_id,
                "length": len(data),
                "total_size": buf_desc.length,
                "offset": offset,
                "content_base64": base64.b64encode(data).decode("ascii"),
            }

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]

    def get_texture_info(self, resource_id):
        """Get texture metadata"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"texture": None, "error": None}

        def callback(controller):
            try:
                tex_desc = self._find_texture_by_id(controller, resource_id)

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
            except Exception as e:
                import traceback
                result["error"] = "Error: %s\n%s" % (str(e), traceback.format_exc())

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["texture"]

    def get_texture_raw(self, resource_id, mip=0, slice=0, sample=0, depth_slice=None):
        """Get texture raw pixel data (Base64 encoded)."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            tex_desc = self._find_texture_by_id(controller, resource_id)

            if not tex_desc:
                result["error"] = "Texture not found: %s" % resource_id
                return

            # Validate mip level
            if mip < 0 or mip >= tex_desc.mips:
                result["error"] = "Invalid mip level %d (texture has %d mips)" % (
                    mip,
                    tex_desc.mips,
                )
                return

            # Validate slice for array/cube textures
            max_slices = tex_desc.arraysize
            if tex_desc.cubemap:
                max_slices = tex_desc.arraysize * 6
            if slice < 0 or (max_slices > 1 and slice >= max_slices):
                result["error"] = "Invalid slice %d (texture has %d slices)" % (
                    slice,
                    max_slices,
                )
                return

            # Validate sample for MSAA
            if sample < 0 or (tex_desc.msSamp > 1 and sample >= tex_desc.msSamp):
                result["error"] = "Invalid sample %d (texture has %d samples)" % (
                    sample,
                    tex_desc.msSamp,
                )
                return

            # Calculate dimensions at this mip level
            mip_width = max(1, tex_desc.width >> mip)
            mip_height = max(1, tex_desc.height >> mip)
            mip_depth = max(1, tex_desc.depth >> mip)

            # Validate depth_slice for 3D textures
            is_3d = tex_desc.depth > 1
            if depth_slice is not None:
                if not is_3d:
                    result["error"] = "depth_slice can only be used with 3D textures"
                    return
                if depth_slice < 0 or depth_slice >= mip_depth:
                    result["error"] = "Invalid depth_slice %d (texture has %d depth at mip %d)" % (
                        depth_slice,
                        mip_depth,
                        mip,
                    )
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

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]

    def get_texture_saved(self, resource_id, mip=0, slice=0, sample=0, depth_slice=None):
        """Save texture as PNG file and return file path."""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            tex_desc = self._find_texture_by_id(controller, resource_id)

            if not tex_desc:
                result["error"] = "Texture not found: %s" % resource_id
                return

            # 验证参数
            if mip < 0 or mip >= tex_desc.mips:
                result["error"] = "Invalid mip level %d (texture has %d mips)" % (
                    mip,
                    tex_desc.mips,
                )
                return

            max_slices = tex_desc.arraysize
            if tex_desc.cubemap:
                max_slices = tex_desc.arraysize * 6
            if slice < 0 or (max_slices > 1 and slice >= max_slices):
                result["error"] = "Invalid slice %d (texture has %d slices)" % (
                    slice,
                    max_slices,
                )
                return

            if sample < 0 or (tex_desc.msSamp > 1 and sample >= tex_desc.msSamp):
                result["error"] = "Invalid sample %d (texture has %d samples)" % (
                    sample,
                    tex_desc.msSamp,
                )
                return

            mip_width = max(1, tex_desc.width >> mip)
            mip_height = max(1, tex_desc.height >> mip)
            mip_depth = max(1, tex_desc.depth >> mip)

            is_3d = tex_desc.depth > 1
            if depth_slice is not None:
                if not is_3d:
                    result["error"] = "depth_slice can only be used with 3D textures"
                    return
                if depth_slice < 0 or depth_slice >= mip_depth:
                    result["error"] = "Invalid depth_slice %d (texture has %d depth at mip %d)" % (
                        depth_slice,
                        mip_depth,
                        mip,
                    )
                    return

            # 确定扩展路径和temp目录
            try:
                # 获取扩展安装路径
                import sys
                extension_dir = None
                if hasattr(sys, "path"):
                    for p in sys.path:
                        if "renderdoc_mcp_bridge" in p:
                            extension_dir = p
                            break
                
                if extension_dir is None:
                    # 备用：使用当前文件路径
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
                import traceback
                result["error"] = "Failed to save texture: %s\n%s" % (str(e), traceback.format_exc())
                return

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]
