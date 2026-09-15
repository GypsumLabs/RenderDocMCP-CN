"""
RenderDoc MCP Bridge Extension
Provides file-based IPC bridge for the external MCP server.
"""

from . import socket_server
from . import request_handler
from . import renderdoc_facade

# Global state
_context = None
_server = None
_version = ""

# Try to import qrenderdoc for UI integration (only available in RenderDoc)
try:
    import qrenderdoc as qrd

    _has_qrenderdoc = True
except ImportError:
    _has_qrenderdoc = False


def register(version, ctx):
    """
    Called when extension is loaded.

    Args:
        version: RenderDoc version string (e.g., "1.20")
        ctx: CaptureContext handle
    """
    global _context, _server, _version
    _version = version
    _context = ctx

    # Create facade and handler
    facade = renderdoc_facade.RenderDocFacade(ctx)
    handler = request_handler.RequestHandler(facade)

    # Start file-based IPC server（host/port 已废弃：通信走文件，不占用端口）
    # _server = socket_server.MCPBridgeServer(
    #     host="127.0.0.1", port=19876, handler=handler
    # )
    _server = socket_server.MCPBridgeServer(handler=handler)
    _server.start()

    # Register menu item if UI is available
    if _has_qrenderdoc:
        try:
            ctx.Extensions().RegisterWindowMenu(
                qrd.WindowMenu.Tools, ["MCP Bridge", "Status"], _show_status
            )
        except Exception as e:
            print("[MCP Bridge] Could not register menu: %s" % str(e))

    print("[MCP Bridge] Extension loaded (RenderDoc %s)" % version)
    print("[MCP Bridge] IPC directory: %s" % _server.get_ipc_dir())


def unregister():
    """Called when extension is unloaded"""
    global _server
    if _server:
        _server.stop()
        _server = None
    print("[MCP Bridge] Extension unloaded")


def _show_status(ctx, data):
    """Show status dialog"""
    if _server and _server.is_running():
        ctx.Extensions().MessageDialog(
            "MCP Bridge is running\nIPC directory: %s" % _server.get_ipc_dir(), "MCP Bridge Status"
        )
    else:
        ctx.Extensions().ErrorDialog("MCP Bridge is not running", "MCP Bridge Status")
