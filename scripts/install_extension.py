"""
RenderDoc Extension Installer
Copies the extension to RenderDoc's extension directory.
"""

import os
import shutil
import sys
from pathlib import Path


def get_extension_dir():
    """Get RenderDoc extension directory"""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "qrenderdoc" / "extensions"
    else:
        home = Path.home()
        return home / ".local" / "share" / "qrenderdoc" / "extensions"

    raise RuntimeError("Cannot determine RenderDoc extension directory")


def iter_source_files(extension_src):
    """遍历扩展源码，跳过字节码缓存"""
    for src in extension_src.rglob("*"):
        rel = src.relative_to(extension_src)
        if "__pycache__" in rel.parts:
            continue
        if src.suffix in (".pyc", ".pyo"):
            continue
        yield src, rel


def clean_bytecode(dest):
    """清理字节码缓存

    逐个删文件而不是 rmtree：部分 IDE 会拦截 shutil.rmtree 并改成"移动到回收站"，
    在 RenderDoc 正在运行时该操作会失败。
    """
    for cache_file in dest.rglob("*.pyc"):
        try:
            os.remove(str(cache_file))
        except OSError:
            pass

    for cache_dir in dest.rglob("__pycache__"):
        try:
            os.rmdir(str(cache_dir))
        except OSError:
            pass


def install():
    """Install the extension"""
    # Source directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    extension_src = project_root / "renderdoc_extension"

    if not extension_src.exists():
        print("Error: Extension source not found at %s" % extension_src)
        sys.exit(1)

    # Destination directory
    ext_dir = get_extension_dir()
    ext_dir.mkdir(parents=True, exist_ok=True)

    dest = ext_dir / "renderdoc_mcp_bridge"
    dest.mkdir(parents=True, exist_ok=True)

    # 逐文件覆盖而不是删除整个目录：
    # 1) RenderDoc 正在运行时删除扩展目录会被系统拒绝（文件被占用）
    # 2) 整目录删除会连带清掉 get_texture_saved 生成的 temp/ 图片
    expected = set()
    copied = 0
    for src, rel in iter_source_files(extension_src):
        expected.add(str(rel))
        target = dest / rel
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(target))
        copied += 1

    # 删除源码里已经不存在的旧文件（temp/ 等运行期产物保留）
    removed = 0
    for existing in sorted(dest.rglob("*"), reverse=True):
        rel = existing.relative_to(dest)
        if rel.parts and rel.parts[0] == "temp":
            continue
        if "__pycache__" in rel.parts:
            continue
        if str(rel) in expected:
            continue
        if existing.is_dir():
            try:
                os.rmdir(str(existing))
                removed += 1
            except OSError:
                pass
        else:
            try:
                os.remove(str(existing))
                removed += 1
            except OSError:
                pass

    clean_bytecode(dest)

    print("Extension installed to %s" % dest)
    print("  (%d files copied, %d stale entries removed, temp/ preserved)" % (copied, removed))
    print("")
    print("Please restart RenderDoc to load the new code, and make sure the extension is enabled in:")
    print("  Tools > Manage Extensions > RenderDoc MCP Bridge")


def uninstall():
    """Uninstall the extension"""
    ext_dir = get_extension_dir()
    dest = ext_dir / "renderdoc_mcp_bridge"

    if dest.exists():
        shutil.rmtree(dest)
        print("Extension uninstalled from %s" % dest)
    else:
        print("Extension not found at %s" % dest)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        uninstall()
    else:
        install()
