"""Linux desktop backend with narrow argv-only adapters and honest feature detection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from .core import DesktopEvent, DesktopError, FeatureUnavailable


class LinuxBackend:
    name = "linux"

    def __init__(self, *, runner: Callable | None = None, popen: Callable | None = None) -> None:
        self._runner = runner or subprocess.run
        self._popen = popen or subprocess.Popen
        self._sway = shutil.which("swaymsg")
        self._wl_paste = shutil.which("wl-paste")
        self._wl_copy = shutil.which("wl-copy")
        self._grim = shutil.which("grim")

    def capabilities(self) -> dict[str, bool]:
        return {
            "launch": True,
            "windows": bool(self._sway),
            "workspaces": bool(self._sway),
            "clipboard": bool(self._wl_paste and self._wl_copy),
            "screenshot": bool(self._grim),
            "events": False,
        }

    def launch(self, argv: Sequence[str]) -> dict:
        try:
            process = self._popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                shell=False,
            )
        except OSError as error:
            raise DesktopError(f"application launch failed: {error}") from error
        return {"pid": int(process.pid), "argv0": str(argv[0])}

    def _run_json(self, argv: Sequence[str]):
        try:
            result = self._runner(
                list(argv),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DesktopError(f"desktop adapter failed: {error}") from error
        if result.returncode != 0:
            raise DesktopError(str(result.stderr or "desktop adapter failed").strip()[:512])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DesktopError("desktop adapter returned malformed JSON") from error

    def _require_sway(self, feature: str) -> str:
        if not self._sway:
            raise FeatureUnavailable(feature, backend=self.name)
        return self._sway

    @staticmethod
    def _flatten_sway(node: dict, output: list[dict]) -> None:
        if node.get("type") in {"con", "floating_con"} and node.get("pid") is not None:
            output.append(
                {
                    "id": str(node.get("id")),
                    "title": str(node.get("name") or ""),
                    "app": str(node.get("app_id") or node.get("window_properties", {}).get("class") or ""),
                    "focused": bool(node.get("focused")),
                    "pid": int(node.get("pid")),
                }
            )
        for child in list(node.get("nodes", [])) + list(node.get("floating_nodes", [])):
            if isinstance(child, dict):
                LinuxBackend._flatten_sway(child, output)

    def list_windows(self) -> list[dict]:
        sway = self._require_sway("windows")
        tree = self._run_json([sway, "-r", "-t", "get_tree"])
        windows: list[dict] = []
        if isinstance(tree, dict):
            self._flatten_sway(tree, windows)
        return windows[:256]

    def focus_window(self, window_id: str) -> dict:
        sway = self._require_sway("windows")
        try:
            con_id = int(window_id)
        except ValueError as error:
            raise DesktopError("Sway window id must be numeric") from error
        result = self._run_json([sway, "-r", f"[con_id={con_id}]", "focus"])
        if not isinstance(result, list) or not result or not result[0].get("success"):
            raise DesktopError("Sway did not acknowledge window focus")
        observed = next((window for window in self.list_windows() if window["id"] == str(con_id)), None)
        if not observed or not observed.get("focused"):
            raise DesktopError("window focus was not observed after acknowledgement")
        return observed

    def close_window(self, window_id: str) -> dict:
        sway = self._require_sway("windows")
        try:
            con_id = int(window_id)
        except ValueError as error:
            raise DesktopError("Sway window id must be numeric") from error
        result = self._run_json([sway, "-r", f"[con_id={con_id}]", "kill"])
        if not isinstance(result, list) or not result or not result[0].get("success"):
            raise DesktopError("Sway did not acknowledge window close")
        remaining = any(window["id"] == str(con_id) for window in self.list_windows())
        if remaining:
            raise DesktopError("window close was not observed after acknowledgement")
        return {"id": str(con_id), "closed": True}

    def list_workspaces(self) -> list[dict]:
        sway = self._require_sway("workspaces")
        workspaces = self._run_json([sway, "-r", "-t", "get_workspaces"])
        if not isinstance(workspaces, list):
            raise DesktopError("Sway returned malformed workspace state")
        return [
            {
                "id": str(item.get("num")),
                "name": str(item.get("name") or ""),
                "active": bool(item.get("focused")),
                "output": str(item.get("output") or ""),
            }
            for item in workspaces[:128]
            if isinstance(item, dict) and isinstance(item.get("num"), int)
        ]

    def switch_workspace(self, workspace_id: str) -> dict:
        sway = self._require_sway("workspaces")
        try:
            number = int(workspace_id)
        except ValueError as error:
            raise DesktopError("Sway workspace id must be numeric") from error
        result = self._run_json([sway, "-r", "workspace", "number", str(number)])
        if not isinstance(result, list) or not result or not result[0].get("success"):
            raise DesktopError("Sway did not acknowledge workspace switch")
        observed = next((workspace for workspace in self.list_workspaces() if workspace["id"] == str(number)), None)
        if not observed or not observed.get("active"):
            raise DesktopError("workspace switch was not observed after acknowledgement")
        return observed

    def clipboard_get(self) -> str:
        if not self._wl_paste:
            raise FeatureUnavailable("clipboard", backend=self.name)
        result = self._runner(
            [self._wl_paste, "--no-newline", "--type", "text"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise DesktopError("wl-paste failed")
        return str(result.stdout)

    def clipboard_set(self, text: str) -> dict:
        if not self._wl_copy:
            raise FeatureUnavailable("clipboard", backend=self.name)
        result = self._runner(
            [self._wl_copy, "--type", "text/plain;charset=utf-8"],
            input=text,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise DesktopError("wl-copy failed")
        return {"bytes": len(text.encode("utf-8")), "acknowledged": True}

    def screenshot(self) -> dict:
        if not self._grim:
            raise FeatureUnavailable("screenshot", backend=self.name)
        root = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "zara-desktop"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="screenshot-", suffix=".png", dir=root)
        os.close(fd)
        target = Path(path)
        try:
            result = self._runner([self._grim, str(target)], capture_output=True, timeout=10, check=False, shell=False)
            if result.returncode != 0 or not target.exists():
                raise DesktopError("grim did not produce a screenshot")
            size = target.stat().st_size
            if size <= 0 or size > 32 * 1024 * 1024:
                raise DesktopError("screenshot size is outside configured safety bounds")
            return {"path": str(target), "bytes": size, "acknowledged": True}
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def poll_events(self, limit: int) -> list[DesktopEvent]:
        return []
