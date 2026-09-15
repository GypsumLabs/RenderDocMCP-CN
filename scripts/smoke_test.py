"""
RenderDoc MCP Bridge 冒烟测试
绕过 MCP 客户端直接通过文件 IPC 调用扩展，逐个工具验证并打印耗时与结果摘要。

用法:
    python scripts/smoke_test.py                 # 全量测试
    python scripts/smoke_test.py --quick         # 跳过整帧反查（find_draws_by_*）
    python scripts/smoke_test.py --capture-dir C:\\path\\to\\captures
"""

import argparse
import json
import os
import sys
import time

# 控制台默认是 GBK，中文输出会变成乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server.bridge.client import RenderDocBridge, RenderDocBridgeError


PASSED = []
FAILED = []


def summarize(result):
    """把结果压缩成一行摘要，避免刷屏"""
    if isinstance(result, dict):
        if "actions" in result:
            return "actions=%d" % len(result["actions"])
        if "matches" in result:
            return "matches=%s scanned=%s" % (result.get("total_matches"), result.get("scanned_draws"))
        if "shaders" in result:
            return "stages=%s errors=%s" % (sorted(result["shaders"].keys()), result.get("errors"))
        if "timings" in result:
            return "available=%s count=%s" % (result.get("available"), result.get("count"))
        if "constant_buffers" in result:
            names = [cb.get("name") for cb in result["constant_buffers"]]
            return "cbuffers=%s disassembly=%s" % (names, "disassembly" in result)
        if "total_size" in result and "content_base64" in result:
            return "buffer read=%s B of %s B" % (result.get("length"), result.get("total_size"))
        if "content_base64" in result:
            return "bytes=%s format=%s" % (result.get("data_length"), result.get("format"))
        if "file_path" in result:
            return "saved=%s size=%s" % (result.get("filename"), result.get("file_size"))
        if "filename" in result:
            return "loaded=%s api=%s" % (result.get("loaded"), result.get("api"))
        if "status" in result and "unit" not in result:
            return json.dumps(result, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)[:200]


def call(bridge, name, method, params=None, timeout=None, expect_error=False):
    """执行一次调用并记录结果"""
    label = "%s(%s)" % (method, json.dumps(params or {}, ensure_ascii=False)) if params else method
    start = time.time()
    try:
        result = bridge.call(method, params, timeout=timeout)
    except RenderDocBridgeError as e:
        elapsed = time.time() - start
        if expect_error:
            PASSED.append(name)
            print("  [预期错误] %-9s %-58s %s" % ("%.1fs" % elapsed, label, str(e)[:120]))
        else:
            FAILED.append(name)
            print("  [失败]     %-9s %-58s %s" % ("%.1fs" % elapsed, label, str(e)[:200]))
        return None
    except Exception as e:
        elapsed = time.time() - start
        FAILED.append(name)
        print("  [异常]     %-9s %-58s %r" % ("%.1fs" % elapsed, label, e))
        return None

    elapsed = time.time() - start
    if expect_error:
        FAILED.append(name)
        print("  [应报错却成功] %-5s %-58s %s" % ("%.1fs" % elapsed, label, summarize(result)[:120]))
        return result

    PASSED.append(name)
    print("  [通过]     %-9s %-58s %s" % ("%.1fs" % elapsed, label, summarize(result)[:160]))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="跳过整帧反查类工具")
    parser.add_argument("--capture-dir", default=os.path.expanduser("~/Downloads"), help="list_captures 使用的目录")
    parser.add_argument("--search-timeout", type=float, default=300.0, help="反查类工具超时（秒）")
    args = parser.parse_args()

    bridge = RenderDocBridge(timeout=120.0, probe_timeout=5.0)
    search_timeout = args.search_timeout

    print("=" * 110)
    print("RenderDoc MCP Bridge 冒烟测试")
    print("=" * 110)

    print("\n[1] 捕获管理与连通性")
    call(bridge, "ping", "ping")
    call(bridge, "get_capture_status", "get_capture_status")
    captures = call(bridge, "list_captures", "list_captures", {"directory": args.capture_dir})

    print("\n[2] 帧概览与 DrawCall")
    summary = call(bridge, "get_frame_summary", "get_frame_summary") or {}
    call(bridge, "get_draw_calls:marker", "get_draw_calls", {"include_children": True, "marker_filter": "Compute Pass #1", "only_actions": True})
    call(bridge, "get_draw_calls:range", "get_draw_calls", {"include_children": False, "only_actions": True, "flags_filter": ["Drawcall"], "event_id_min": 6900, "event_id_max": 7000})
    # 与上一条保持完全相同的过滤条件，否则两次结果数量无法对比
    call(bridge, "get_draw_calls:exclude", "get_draw_calls", {"include_children": False, "exclude_markers": ["Compute Pass #1", "Compute Pass #2"], "only_actions": True, "flags_filter": ["Drawcall"], "event_id_min": 6900, "event_id_max": 7000})
    draw_calls = call(bridge, "get_draw_calls:all", "get_draw_calls", {"include_children": False, "only_actions": True, "flags_filter": ["Drawcall"]})
    action_timings = call(bridge, "get_action_timings", "get_action_timings", {"marker_filter": "Compute Pass #2"})

    # 从结果里挑一个真实 event_id，避免硬编码
    event_id = 0
    for action in (draw_calls or {}).get("actions", []):
        event_id = action["event_id"]
    if not event_id:
        for marker in summary.get("top_level_markers", []):
            event_id = marker["event_id"]
    print("\n  (使用 event_id=%s 继续测试)" % event_id)

    call(bridge, "get_draw_call_details", "get_draw_call_details", {"event_id": event_id})

    # 同一请求重复两次，确认结果稳定（曾观察到相同参数两次返回数量不一致）
    repeat_a = bridge.call("get_draw_calls", {"include_children": False, "only_actions": True, "flags_filter": ["Drawcall"], "event_id_min": 6900, "event_id_max": 7000})
    repeat_b = bridge.call("get_draw_calls", {"include_children": False, "only_actions": True, "flags_filter": ["Drawcall"], "event_id_min": 6900, "event_id_max": 7000})
    if json.dumps(repeat_a, sort_keys=True) == json.dumps(repeat_b, sort_keys=True):
        PASSED.append("determinism")
        print("  [通过]     同一请求重复两次结果一致")
    else:
        FAILED.append("determinism")
        print("  [失败]     同一请求重复两次结果不一致: %s vs %s" % (summarize(repeat_a), summarize(repeat_b)))

    print("\n[3] 管线与着色器")
    pipeline = call(bridge, "get_pipeline_state", "get_pipeline_state", {"event_id": event_id})
    call(bridge, "get_pipeline_state:no_cbvars", "get_pipeline_state", {"event_id": event_id, "include_cbuffer_variables": False})
    stage_key = None
    if pipeline:
        # 优先选真正绑了常量缓冲的 stage，否则覆盖不到变量值读取这条路径
        for key, info in pipeline.get("shaders", {}).items():
            if info.get("constant_buffers"):
                stage_key = key.split(".")[-1].lower()
                break
        if not stage_key:
            for key in ("ShaderStage.Pixel", "ShaderStage.Vertex", "ShaderStage.Compute"):
                if key in pipeline.get("shaders", {}):
                    stage_key = key.split(".")[-1].lower()
                    break
    stage = stage_key or "pixel"
    print("  (使用 stage=%s)" % stage)
    call(bridge, "get_shader_info:lite", "get_shader_info", {"event_id": event_id, "stage": stage, "include_disassembly": False, "max_variables": 8})
    shader = call(bridge, "get_shader_info:full", "get_shader_info", {"event_id": event_id, "stage": stage})
    call(bridge, "get_shader_info:slots", "get_shader_info", {"event_id": event_id, "stage": stage, "cbuffer_slots": [0], "include_disassembly": False, "max_variables": 4})

    # 找一个有绑定资源的 event 用于资源类工具
    resource_id = None
    if pipeline:
        for stage_info in pipeline.get("shaders", {}).values():
            for res in stage_info.get("resources", []):
                resource_id = res.get("resource_id")
                break
            if resource_id:
                break
    if not resource_id and shader:
        resource_id = shader.get("resource_id")
    print("  (使用 resource_id=%s)" % resource_id)

    print("\n[4] 资源读取")
    texture_id = None
    for tex_candidate in ("ResourceId::1071", "ResourceId::308", resource_id):
        if not tex_candidate:
            continue
        info = call(bridge, "get_texture_info:%s" % tex_candidate, "get_texture_info", {"resource_id": tex_candidate})
        if info:
            texture_id = tex_candidate
            break
    if texture_id:
        call(bridge, "get_texture_raw", "get_texture_raw", {"resource_id": texture_id})
        call(bridge, "get_texture_saved", "get_texture_saved", {"resource_id": texture_id})

    # 从管线状态的 UAV/SRV 里找一个 buffer 用于 get_buffer_contents
    # 单个 event 不一定绑定 buffer，这里扫一批 dispatch 直到找到为止
    dispatches = call(bridge, "get_draw_calls:dispatches", "get_draw_calls", {"include_children": True, "only_actions": True, "flags_filter": ["Dispatch"]}) or {}
    buffer_id = None
    for candidate_event in [a["event_id"] for a in dispatches.get("actions", [])][:20]:
        state = bridge.call("get_pipeline_state", {"event_id": candidate_event, "include_cbuffer_variables": False}, timeout=60)
        for stage_info in state.get("shaders", {}).values():
            for binding in list(stage_info.get("uavs", [])) + list(stage_info.get("resources", [])):
                if binding.get("type") == "buffer":
                    buffer_id = binding.get("resource_id")
                    break
            if buffer_id:
                break
        if buffer_id:
            print("  (在 event_id=%s 找到 buffer_id=%s)" % (candidate_event, buffer_id))
            break

    if buffer_id:
        call(bridge, "get_buffer_contents:full", "get_buffer_contents", {"resource_id": buffer_id})
        call(bridge, "get_buffer_contents:range", "get_buffer_contents", {"resource_id": buffer_id, "offset": 0, "length": 32})
    else:
        FAILED.append("get_buffer_contents")
        print("  [跳过]     get_buffer_contents —— 扫过的 event 里都没有 buffer 绑定")

    print("\n[5] 反查")
    if args.quick:
        print("  (--quick 已跳过)")
    else:
        call(bridge, "find_draws_by_shader", "find_draws_by_shader", {"shader_name": "main", "stage": "compute"}, timeout=search_timeout)
        call(bridge, "find_draws_by_texture", "find_draws_by_texture", {"texture_name": "DepthPyramid"}, timeout=search_timeout)
        call(bridge, "find_draws_by_resource", "find_draws_by_resource", {"resource_id": buffer_id or "ResourceId::1309"}, timeout=search_timeout)
        call(bridge, "find_draws_by_mesh", "find_draws_by_mesh", {"mesh_name": "Buffer"}, timeout=search_timeout)

    print("\n[6] 错误路径（应报错）")
    call(bridge, "get_texture_info:bad", "get_texture_info", {"resource_id": "not-a-number"}, expect_error=True)
    call(bridge, "get_texture_info:404", "get_texture_info", {"resource_id": "ResourceId::99999999"}, expect_error=True)
    call(bridge, "get_texture_raw:bad_mip", "get_texture_raw", {"resource_id": texture_id or "ResourceId::1071", "mip": 99}, expect_error=True)
    call(bridge, "get_buffer_contents:bad", "get_buffer_contents", {"resource_id": "not-a-number"}, expect_error=True)
    call(bridge, "get_draw_call_details:404", "get_draw_call_details", {"event_id": 99999999}, expect_error=True)
    call(bridge, "get_shader_info:bad_stage", "get_shader_info", {"event_id": event_id, "stage": "not-a-stage"}, expect_error=True)
    call(bridge, "get_shader_info:no_shader", "get_shader_info", {"event_id": event_id, "stage": "geometry"}, expect_error=True)
    call(bridge, "list_captures:404", "list_captures", {"directory": "Z:\\nope"}, expect_error=True)
    call(bridge, "open_capture:404", "open_capture", {"capture_path": "Z:\\nope.rdc"}, expect_error=True)
    call(bridge, "unknown_method", "no_such_method", {}, expect_error=True)

    print("\n" + "=" * 110)
    print("通过 %d 项，失败 %d 项" % (len(set(PASSED)), len(set(FAILED))))
    if FAILED:
        print("失败项: %s" % ", ".join(sorted(set(FAILED))))
    print("=" * 110)

    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
