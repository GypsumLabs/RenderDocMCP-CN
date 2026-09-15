"""
Parse utility functions for RenderDoc data types.
"""

import renderdoc as rd


class Parsers:
    """Parse utility functions (static methods)"""

    @staticmethod
    def parse_stage(stage_str):
        """Convert stage string to ShaderStage enum"""
        stage_map = {
            "vertex": rd.ShaderStage.Vertex,
            "hull": rd.ShaderStage.Hull,
            "domain": rd.ShaderStage.Domain,
            "geometry": rd.ShaderStage.Geometry,
            "pixel": rd.ShaderStage.Pixel,
            "compute": rd.ShaderStage.Compute,
        }
        stage_lower = stage_str.lower()
        if stage_lower not in stage_map:
            raise ValueError("Unknown shader stage: %s" % stage_str)
        return stage_map[stage_lower]

    @staticmethod
    def numeric_id(resource):
        """取出资源 ID 的数字部分，入参可以是 ResourceId 对象或 'ResourceId::123' 形式的字符串"""
        text = str(resource)
        if "::" in text:
            text = text.split("::")[-1]
        return int(text)

    @staticmethod
    def same_resource(a, b):
        """判断两个资源是否为同一个（入参可以是 ResourceId 或字符串 ID）

        不要用 rd.ResourceId() 构造对象再比较：RenderDoc 1.46 的绑定里，
        这样构造出来的对象与真实 ResourceId 并不相等（等价于 Null），
        会让比较恒为假或匹配到所有未绑定资源。
        """
        return Parsers.numeric_id(a) == Parsers.numeric_id(b)

    @staticmethod
    def extract_numeric_id(resource_id_str):
        """Extract numeric ID from resource ID string"""
        return Parsers.numeric_id(resource_id_str)

    @staticmethod
    def parse_resource_id(resource_id_str):
        """[已废弃] 构造 rd.ResourceId

        保留仅为兼容旧调用，不要再用于资源比较：构造出的对象与真实 ResourceId 不相等，
        find_draws_by_resource / get_buffer_contents 曾因此出现"匹配到全部绘制"和
        "始终报 Buffer not found"两类错误。资源比较请改用 same_resource / numeric_id。
        """
        rid = rd.ResourceId()
        rid.id = Parsers.numeric_id(resource_id_str)
        return rid
