"""
Capture management service for RenderDoc.
"""

import datetime
import os

import renderdoc as rd


class CaptureManager:
    """Capture management service"""

    def __init__(self, ctx, invoke_fn):
        self.ctx = ctx
        self._invoke = invoke_fn

    def get_capture_status(self):
        """Check if a capture is loaded and get API info"""
        if not self.ctx.IsCaptureLoaded():
            return {"loaded": False}

        result = {"loaded": True, "api": None, "filename": None}

        try:
            result["filename"] = self.ctx.GetCaptureFilename()
        except Exception:
            pass

        result["api"] = self._read_api_type()
        return result

    def _read_api_type(self):
        """通过 replay 线程读取图形 API 类型，失败返回 None"""
        holder = {"api": None}

        def callback(controller):
            try:
                holder["api"] = str(controller.GetAPIProperties().pipelineType)
            except Exception:
                holder["api"] = None

        try:
            self._invoke(callback)
        except Exception:
            return None

        return holder["api"]

    def list_captures(self, directory):
        """
        List all .rdc files in the specified directory.

        Args:
            directory: Directory path to search

        Returns:
            dict with 'captures' list containing file info
        """
        # Validate directory exists
        if not os.path.isdir(directory):
            raise ValueError("Directory not found: %s" % directory)

        captures = []

        try:
            for filename in os.listdir(directory):
                if filename.lower().endswith(".rdc"):
                    filepath = os.path.join(directory, filename)
                    if os.path.isfile(filepath):
                        stat = os.stat(filepath)
                        # Format timestamp as ISO 8601
                        mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                        captures.append({
                            "filename": filename,
                            "path": filepath,
                            "size_bytes": stat.st_size,
                            "modified_time": mtime.isoformat(),
                        })
        except Exception as e:
            raise ValueError("Failed to list directory: %s" % str(e))

        # Sort by modified time (newest first)
        captures.sort(key=lambda x: x["modified_time"], reverse=True)

        return {
            "directory": directory,
            "count": len(captures),
            "captures": captures,
        }

    def open_capture(self, capture_path):
        """
        Open a capture file in RenderDoc.

        Args:
            capture_path: Full path to the .rdc file

        Returns:
            dict with success status and capture info
        """
        # Validate file exists
        if not os.path.isfile(capture_path):
            raise ValueError("Capture file not found: %s" % capture_path)

        # Validate extension
        if not capture_path.lower().endswith(".rdc"):
            raise ValueError("Invalid file type. Expected .rdc file: %s" % capture_path)

        # Create ReplayOptions with defaults
        opts = rd.ReplayOptions()

        # Open the capture
        # LoadCapture will automatically close any existing capture
        try:
            self.ctx.LoadCapture(
                capture_path,   # captureFile
                opts,           # ReplayOptions
                capture_path,   # origFilename (same as capture path)
                False,          # temporary (False = permanent load)
                True,           # local (True = local file)
            )
        except Exception as e:
            raise ValueError("Failed to open capture: %s" % str(e))

        # Verify the capture was loaded
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("Failed to load capture (unknown error)")

        # Get capture info
        result = {
            "success": True,
            "capture_path": capture_path,
            "filename": os.path.basename(capture_path),
        }

        # Get API type if possible (may require replay thread)
        api = self._read_api_type()
        if api:
            result["api"] = api

        return result
