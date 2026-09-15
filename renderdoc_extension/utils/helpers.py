"""
Common helper functions for RenderDoc operations.
"""

import renderdoc as rd


class Helpers:
    """Common helper functions (static methods)"""

    @staticmethod
    def replay_call(invoke_fn, result, callback):
        """在 replay 线程执行回调，并把回调内抛出的异常收进 result["error"]

        RenderDoc 的 BlockInvoke 会吞掉回调内抛出的异常：不显式捕获的话，
        调用方拿到的只会是 None，错误信息全部丢失
        （例如 stage 名非法时 get_shader_info 会静默返回 null 而不是报错）。
        """
        def guarded(controller):
            try:
                callback(controller)
            except Exception as e:
                result["error"] = str(e)

        invoke_fn(guarded)

    @staticmethod
    def flatten_actions(actions):
        """Flatten hierarchical actions to a list"""
        flat = []
        for action in actions:
            flat.append(action)
            if action.children:
                flat.extend(Helpers.flatten_actions(action.children))
        return flat

    @staticmethod
    def count_children(action):
        """Count total number of children recursively"""
        count = 0
        if action.children:
            for child in action.children:
                count += 1
                count += Helpers.count_children(child)
        return count

    @staticmethod
    def get_all_shader_stages():
        """Get list of all shader stages"""
        return [
            rd.ShaderStage.Vertex,
            rd.ShaderStage.Hull,
            rd.ShaderStage.Domain,
            rd.ShaderStage.Geometry,
            rd.ShaderStage.Pixel,
            rd.ShaderStage.Compute,
        ]
