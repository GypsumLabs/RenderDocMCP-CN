"""
RenderDoc Bridge Client
Communicates with the RenderDoc extension via file-based IPC.
"""

import json
import os
import tempfile
import time
import uuid
from typing import Any


# IPC directory (must match renderdoc_extension/socket_server.py)
IPC_DIR = os.path.join(tempfile.gettempdir(), "renderdoc_mcp")
REQUEST_FILE = os.path.join(IPC_DIR, "request.json")
RESPONSE_FILE = os.path.join(IPC_DIR, "response.json")
# 响应临时文件由扩展侧写入后原子重命名，客户端只读最终文件，这里保留定义用于说明协议
RESPONSE_TMP_FILE = os.path.join(IPC_DIR, "response.json.tmp")
LOCK_FILE = os.path.join(IPC_DIR, "lock")

# 轮询间隔（秒）
POLL_INTERVAL = 0.05


class RenderDocBridgeError(Exception):
    """Error communicating with RenderDoc bridge"""

    pass


class RenderDocBridge:
    """Client for communicating with RenderDoc extension via file-based IPC"""

    def __init__(self, timeout: float = 120.0, probe_timeout: float = 5.0):
        # 通信改为文件 IPC 后不再占用端口，因此不再需要 host/port
        self.timeout = float(timeout)  # seconds
        self.probe_timeout = float(probe_timeout)
        self._verified = False

    def ping(self, timeout: float | None = None) -> bool:
        """探测扩展是否存活；失败不抛异常，只返回 False"""
        probe_timeout = self.probe_timeout if timeout is None else float(timeout)
        try:
            result = self.call("ping", timeout=probe_timeout)
        except RenderDocBridgeError:
            return False
        return bool(result) and result.get("status") == "ok"

    def _ensure_alive(self):
        """首次调用前做一次快速探测，避免扩展未加载时白等满整个超时"""
        if self._verified:
            return
        if not self.ping():
            raise RenderDocBridgeError(
                f"RenderDoc MCP Bridge 未响应（IPC 目录: {IPC_DIR}）。"
                "请确认 RenderDoc 已启动，并已在 Tools > Manage Extensions 中启用 \"RenderDoc MCP Bridge\"。"
            )
        self._verified = True

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        """Call a method on the RenderDoc extension"""
        # Check if IPC directory exists
        if not os.path.exists(IPC_DIR):
            raise RenderDocBridgeError(
                f"找不到 IPC 目录 {IPC_DIR}。请确认 RenderDoc 已启动并加载了 MCP Bridge 扩展（扩展启动时会创建该目录）。"
            )

        # 探测请求自身不再递归探测
        if method != "ping":
            self._ensure_alive()

        # 允许单次调用覆盖默认超时（整帧遍历类查询耗时远高于普通查询）
        effective_timeout = self.timeout if timeout is None else float(timeout)

        request = {
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

        try:
            # 清理上一轮的响应；扩展侧用原子重命名写响应，这里只需处理最终文件
            if os.path.exists(RESPONSE_FILE):
                os.remove(RESPONSE_FILE)

            # Create lock file to signal we're writing
            with open(LOCK_FILE, "w") as f:
                f.write("lock")

            # Write request
            with open(REQUEST_FILE, "w", encoding="utf-8") as f:
                json.dump(request, f)

            # Remove lock file to signal write complete
            os.remove(LOCK_FILE)

            # Wait for response
            start_time = time.time()
            while True:
                response = self._read_response()

                if response is not None:
                    # 丢弃上一次超时请求迟到的响应，否则会把旧结果当成本次结果返回
                    if response.get("id") != request["id"]:
                        continue

                    if "error" in response:
                        error = response["error"]
                        raise RenderDocBridgeError(f"[{error['code']}] {error['message']}")

                    return response.get("result")

                # Check timeout
                if time.time() - start_time > effective_timeout:
                    raise RenderDocBridgeError(
                        f"请求超时({effective_timeout:g}s)：扩展可能未加载，或未在轮询 {IPC_DIR}"
                    )

                # Poll interval
                time.sleep(POLL_INTERVAL)

        except RenderDocBridgeError:
            raise
        except Exception as e:
            raise RenderDocBridgeError(f"Communication error: {e}")

    def _read_response(self) -> dict[str, Any] | None:
        """读取并消费响应文件；文件不存在或内容不完整时返回 None"""
        if not os.path.exists(RESPONSE_FILE):
            return None

        try:
            with open(RESPONSE_FILE, "r", encoding="utf-8") as f:
                response = json.load(f)
        except (ValueError, OSError):
            # 扩展侧使用原子重命名，正常情况下不会读到半截内容，这里仅作兜底
            return None

        try:
            os.remove(RESPONSE_FILE)
        except OSError:
            pass

        return response
