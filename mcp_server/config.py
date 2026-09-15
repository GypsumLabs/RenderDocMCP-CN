"""Configuration for RenderDoc MCP Server"""

import os


class Settings:
    """Server settings"""

    def __init__(self):
        # 通信改为基于文件的 IPC 后不再占用端口，host/port 已废弃，故不再读取环境变量
        # self.renderdoc_host = os.environ.get("RENDERDOC_MCP_HOST", "127.0.0.1")
        # self.renderdoc_port = int(os.environ.get("RENDERDOC_MCP_PORT", "19876"))
        # 常规请求超时
        self.bridge_timeout = float(os.environ.get("RENDERDOC_MCP_TIMEOUT", "120"))
        # 需要遍历整帧的反向搜索超时（逐 DrawCall 回放，耗时随 DrawCall 数量增长）
        self.bridge_search_timeout = float(os.environ.get("RENDERDOC_MCP_SEARCH_TIMEOUT", "300"))
        # 首次调用前的连通性探测超时，用于在扩展未加载时快速失败
        self.bridge_probe_timeout = float(os.environ.get("RENDERDOC_MCP_PROBE_TIMEOUT", "5"))


settings = Settings()
