"""
File-based IPC Server for RenderDoc MCP Bridge
Uses file polling with a Qt timer since the extension runs on the Qt UI thread.
"""

import json
import os
import traceback
import tempfile

from PySide2.QtCore import QObject, QTimer


# IPC directory
IPC_DIR = os.path.join(tempfile.gettempdir(), "renderdoc_mcp")
REQUEST_FILE = os.path.join(IPC_DIR, "request.json")
RESPONSE_FILE = os.path.join(IPC_DIR, "response.json")
# 响应先写入临时文件，写完后再原子重命名，避免客户端读到半截内容
RESPONSE_TMP_FILE = os.path.join(IPC_DIR, "response.json.tmp")
LOCK_FILE = os.path.join(IPC_DIR, "lock")


class MCPBridgeServer(QObject):
    """File-based IPC server for MCP bridge communication"""

    # 原构造签名为 (host, port, handler, parent)，改用文件 IPC 后 host/port 已无意义
    def __init__(self, handler, parent=None):
        super(MCPBridgeServer, self).__init__(parent)
        self.handler = handler
        self._timer = None
        self._running = False

        # Create IPC directory
        if not os.path.exists(IPC_DIR):
            os.makedirs(IPC_DIR)

    def start(self):
        """Start the server with polling"""
        self._running = True

        # Clean up old files
        self._cleanup_files()

        # Start polling timer (check every 100ms)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_request)
        self._timer.start(100)

        print("[MCP Bridge] File-based IPC server started")
        print("[MCP Bridge] IPC directory: %s" % IPC_DIR)
        return True

    def stop(self):
        """Stop the server"""
        self._running = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        self._cleanup_files()
        print("[MCP Bridge] Server stopped")

    def is_running(self):
        """Check if server is running"""
        return self._running

    def get_ipc_dir(self):
        """返回 IPC 目录，便于外部提示用户"""
        return IPC_DIR

    def _safe_remove(self, path):
        """删除文件，忽略不存在或占用等异常"""
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _cleanup_files(self):
        """Remove IPC files"""
        for f in [REQUEST_FILE, RESPONSE_FILE, RESPONSE_TMP_FILE, LOCK_FILE]:
            self._safe_remove(f)

    def _poll_request(self):
        """Check for incoming request"""
        if not self._running:
            return

        # Check if request file exists
        if not os.path.exists(REQUEST_FILE):
            return

        # Check if lock file exists (client is still writing)
        if os.path.exists(LOCK_FILE):
            return

        # 先把请求读出来；无论解析成功与否都必须删掉请求文件，
        # 否则解析失败会每 100ms 报错一次并永久阻塞后续所有请求
        try:
            with open(REQUEST_FILE, "r", encoding="utf-8") as f:
                request = json.load(f)
        except Exception as e:
            print("[MCP Bridge] 丢弃无法解析的请求: %s" % str(e))
            self._safe_remove(REQUEST_FILE)
            return

        self._safe_remove(REQUEST_FILE)

        # Process request
        try:
            response = self.handler.handle(request)
        except Exception as e:
            traceback.print_exc()
            response = {
                "id": request.get("id"),
                "error": {"code": -32603, "message": str(e)}
            }

        # Write response
        # 原实现直接写 response.json，客户端可能在写入途中读到半截文件
        # with open(RESPONSE_FILE, "w", encoding="utf-8") as f:
        #     json.dump(response, f)
        try:
            with open(RESPONSE_TMP_FILE, "w", encoding="utf-8") as f:
                json.dump(response, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(RESPONSE_TMP_FILE, RESPONSE_FILE)
        except Exception as e:
            print("[MCP Bridge] 写入响应失败: %s" % str(e))
            traceback.print_exc()
