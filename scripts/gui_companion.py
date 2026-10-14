#!/usr/bin/env python3
"""
scripts/gui_companion.py

GUI Companion Sidecar Daemon for Storyteller FilmCraft in the Antigravity
Short-Form Clipping Pipeline Plugin.

Primary References:
- docs/research/filmcraft-control-server.md
- docs/research/fcproj-assembly-spec.md
- GLOSSARY.md ("Live GUI Companion", "Feedback Checkpoint", "Preference Store")
- GitHub Issues #22, #23, #25, #26, #27

This daemon manages the live FilmCraft process lifecycle (`filmcraft --control <port>`),
pings health over TCP JSON-lines RPC, dispatches timeline reloads on step completion,
seeks and triggers playback, and watches project files for human editor saves.

Zero external runtime dependencies (Python standard library only).
"""

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# --- Constants & Protocol Definitions ---

DEFAULT_PORT: int = 9876
DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_TIMEOUT: float = 5.0
TICKS_PER_SECOND: int = 254016000000

STATE_FILENAME: str = ".gui_companion.json"
DEFAULT_FLAG_FILENAME: str = ".gui_companion_saved.flag"
DEFAULT_LOG_FILENAME: str = ".gui_companion.log"


def _get_utc_now_iso() -> str:
    """Return current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def format_timecode(seconds: float, fps: float = 30.0) -> str:
    """Format seconds into standard SMPTE timecode (HH:MM:SS:FF)."""
    if seconds < 0:
        seconds = 0.0
    total_frames = int(round(seconds * fps))
    frames_per_sec = int(round(fps))
    frames_per_min = frames_per_sec * 60
    frames_per_hour = frames_per_min * 60

    h = total_frames // frames_per_hour
    rem = total_frames % frames_per_hour
    m = rem // frames_per_min
    rem %= frames_per_min
    s = rem // frames_per_sec
    f = rem % frames_per_sec
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def ticks_to_seconds(ticks: int) -> float:
    """Convert high-precision FilmCraft ticks to float seconds."""
    return float(ticks) / TICKS_PER_SECOND


def seconds_to_ticks(seconds: float) -> int:
    """Convert float seconds to high-precision FilmCraft ticks."""
    return int(round(seconds * TICKS_PER_SECOND))


def is_pid_alive(pid: Optional[int]) -> bool:
    """Check if a Unix process ID is currently running."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# --- FilmCraft Control Client ---


class FilmCraftControlClient:
    """Client for FilmCraft --control <port> JSON-lines RPC server.

    Maintains a streaming TCP connection over 127.0.0.1, formatting
    requests as newline-delimited JSON and parsing synchronous responses.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._rfile = None
        self._wfile = None
        self._req_id = 0

    def connect(self) -> None:
        """Establish TCP connection to FilmCraft control server."""
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))
        except (ConnectionRefusedError, socket.timeout) as e:
            sock.close()
            raise ConnectionRefusedError(
                f"Could not connect to FilmCraft control server at {self.host}:{self.port} - {e}"
            )
        self._sock = sock
        self._rfile = sock.makefile("r", encoding="utf-8")
        self._wfile = sock.makefile("w", encoding="utf-8")

    def is_connected(self) -> bool:
        """Return True if the socket is currently connected."""
        return self._sock is not None

    def close(self) -> None:
        """Close TCP socket and file handles."""
        if self._rfile:
            try:
                self._rfile.close()
            except Exception:
                pass
            self._rfile = None
        if self._wfile:
            try:
                self._wfile.close()
            except Exception:
                pass
            self._wfile = None
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Send a JSON-lines RPC request and return the result object."""
        if not self._sock:
            self.connect()

        self._req_id += 1
        req = {
            "id": self._req_id,
            "method": method,
            "params": params if params is not None else {},
        }
        payload = json.dumps(req) + "\n"
        try:
            self._wfile.write(payload)
            self._wfile.flush()
        except Exception as e:
            self.close()
            raise ConnectionResetError(f"Failed to transmit request to FilmCraft: {e}")

        try:
            line = self._rfile.readline()
        except Exception as e:
            self.close()
            raise ConnectionResetError(f"Failed to read response from FilmCraft: {e}")

        if not line:
            self.close()
            raise ConnectionResetError("FilmCraft closed control connection unexpectedly")

        try:
            resp = json.loads(line)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Malformed JSON response from FilmCraft: {line.strip()!r} - {e}")

        if not resp.get("ok"):
            error_msg = resp.get("error", "Unknown control server error")
            raise RuntimeError(f"FilmCraft RPC error ({method}): {error_msg}")

        return resp.get("result")

    def execute(self, command: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Dispatch an internal editor command via engine.execute."""
        return self.call("engine.execute", {"command": command, "params": params or {}})

    # --- High-Level Editor Operations ---

    def open_project(self, path: Union[str, Path]) -> Dict[str, Any]:
        """Open or reload a project file in FilmCraft via file.open."""
        abs_path = str(Path(path).resolve())
        return self.execute("file.open", {"path": abs_path})

    def revert_project(self) -> Dict[str, Any]:
        """Revert currently open project back to disk baseline via file.revert."""
        return self.execute("file.revert", {})

    def inspect_project(self) -> Dict[str, Any]:
        """Query project metadata, active sequence, revision counter, and dirty state."""
        return self.execute("project.inspect", {})

    def inspect_sequence(self, sequence_id: Optional[int] = None) -> Dict[str, Any]:
        """Query detailed track layout and timeline clip placements."""
        params = {"item": sequence_id} if sequence_id else {}
        return self.execute("sequence.inspect", params)

    def seek_seconds(self, seconds: float) -> float:
        """Seek playhead by seconds; returns updated playhead in seconds."""
        res = self.execute("playhead.set", {"seconds": float(seconds)})
        time_ticks = res.get("time", 0)
        return ticks_to_seconds(time_ticks)

    def seek_frame(self, frame: int) -> int:
        """Seek playhead by frame index; returns updated ticks."""
        res = self.execute("playhead.set", {"frame": int(frame)})
        return res.get("time", 0)

    def seek_timecode(self, timecode: str) -> int:
        """Seek playhead by SMPTE timecode string (HH:MM:SS:FF)."""
        res = self.execute("playhead.set", {"timecode": str(timecode)})
        return res.get("time", 0)

    def seek_ticks(self, ticks: int) -> int:
        """Seek playhead by exact integer ticks."""
        res = self.execute("playhead.set", {"time": int(ticks)})
        return res.get("time", 0)

    def play(self) -> Dict[str, Any]:
        """Start playback via ui.playback."""
        res = self.call("ui.playback", {"action": "play"})
        res["seconds"] = ticks_to_seconds(res.get("playhead", 0))
        res["timecode"] = format_timecode(res["seconds"])
        return res

    def stop(self) -> Dict[str, Any]:
        """Stop / pause playback via ui.playback."""
        res = self.call("ui.playback", {"action": "stop"})
        res["seconds"] = ticks_to_seconds(res.get("playhead", 0))
        res["timecode"] = format_timecode(res["seconds"])
        return res

    def get_playback_status(self) -> Dict[str, Any]:
        """Query playhead position and playback state."""
        res = self.call("ui.playback", {})
        res["seconds"] = ticks_to_seconds(res.get("playhead", 0))
        res["timecode"] = format_timecode(res["seconds"])
        return res

    def ping(self) -> bool:
        """Quick health probe; returns True if server responds."""
        try:
            self.get_playback_status()
            return True
        except Exception:
            return False

    def quit_app(self) -> None:
        """Request graceful shutdown of the FilmCraft application."""
        try:
            self.call("app.quit", {})
        except Exception:
            pass


# --- Companion State Manager ---


class CompanionStateManager:
    """Manages the .gui_companion.json runtime state file."""

    @staticmethod
    def get_state_path(base_dir: Optional[Union[str, Path]] = None) -> Path:
        base = Path(base_dir).resolve() if base_dir else Path.cwd()
        return base / STATE_FILENAME

    @classmethod
    def load_state(cls, base_dir: Optional[Union[str, Path]] = None) -> Optional[Dict[str, Any]]:
        path = cls.get_state_path(base_dir)
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @classmethod
    def save_state(
        cls, state: Dict[str, Any], base_dir: Optional[Union[str, Path]] = None
    ) -> Path:
        path = cls.get_state_path(base_dir)
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        temp_path.replace(path)
        return path

    @classmethod
    def clear_state(cls, base_dir: Optional[Union[str, Path]] = None) -> None:
        path = cls.get_state_path(base_dir)
        if path.is_file():
            try:
                path.unlink()
            except Exception:
                pass


# --- Process Lifecycle Manager ---


class ProcessManager:
    """Manages spawning, attaching, health checks, and termination of FilmCraft."""

    @staticmethod
    def find_filmcraft_binary() -> Optional[str]:
        """Locate FilmCraft executable in PATH or standard user directories."""
        env_bin = os.environ.get("FILMCRAFT_BIN")
        if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
            return env_bin

        which_bin = shutil.which("filmcraft")
        if which_bin:
            return which_bin

        search_paths = [
            Path("/home/mhawar/.local/bin/filmcraft"),
            Path("/home/mhawar/.local/share/filmcraft/squashfs-root/usr/bin/filmcraft"),
            Path.home() / ".local" / "bin" / "filmcraft",
            Path.home() / ".local" / "share" / "filmcraft" / "squashfs-root" / "usr" / "bin" / "filmcraft",
        ]
        for p in search_paths:
            if p.is_file() and os.access(str(p), os.X_OK):
                return str(p)

        return None

    @classmethod
    def is_port_listening(cls, port: int, host: str = DEFAULT_HOST) -> bool:
        """Check if TCP port is accepting connections."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect((host, port))
            sock.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False

    @classmethod
    def start(
        cls,
        port: int = DEFAULT_PORT,
        project_path: Optional[Union[str, Path]] = None,
        binary: Optional[str] = None,
        demo: bool = False,
        background: bool = True,
        timeout: float = 10.0,
        base_dir: Optional[Union[str, Path]] = None,
        log_file: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Start or attach to FilmCraft --control <port>.

        If already running and responsive, attaches cleanly without respawning.
        """
        base = Path(base_dir).resolve() if base_dir else Path.cwd()

        # Check if already listening and responsive
        if cls.is_port_listening(port):
            client = FilmCraftControlClient(port=port, timeout=1.5)
            try:
                client.connect()
                if client.ping():
                    status = client.get_playback_status()
                    proj_info = {}
                    try:
                        proj_info = client.inspect_project()
                    except Exception:
                        pass
                    client.close()

                    existing_state = CompanionStateManager.load_state(base) or {}
                    pid = existing_state.get("pid")
                    updated_state = {
                        "status": "attached",
                        "port": port,
                        "host": DEFAULT_HOST,
                        "pid": pid,
                        "project_path": proj_info.get("path") or (str(Path(project_path).resolve()) if project_path else None),
                        "started_at": existing_state.get("started_at") or _get_utc_now_iso(),
                        "last_heartbeat": _get_utc_now_iso(),
                    }
                    CompanionStateManager.save_state(updated_state, base)
                    return updated_state
            except Exception:
                client.close()

        bin_path = binary or cls.find_filmcraft_binary()
        if not bin_path:
            raise FileNotFoundError(
                "FilmCraft executable not found. Set FILMCRAFT_BIN or ensure filmcraft is installed in PATH."
            )

        cmd = [bin_path, "--control", str(port), "--no-recover"]
        resolved_proj = None
        if demo:
            cmd.append("--demo")
        elif project_path:
            resolved_proj = str(Path(project_path).resolve())
            cmd.append(resolved_proj)
        else:
            cmd.append("--empty")

        log_path = Path(log_file).resolve() if log_file else base / DEFAULT_LOG_FILENAME

        if background:
            log_out = open(log_path, "a", encoding="utf-8")
            proc = subprocess.Popen(
                cmd,
                stdout=log_out,
                stderr=log_out,
                start_new_session=True,
                cwd=str(base),
            )
        else:
            proc = subprocess.Popen(cmd, cwd=str(base))

        pid = proc.pid

        # Wait for socket to become connectable and responsive
        client = FilmCraftControlClient(port=port, timeout=1.0)
        start_time = time.time()
        connected = False

        while time.time() - start_time < timeout:
            if proc.poll() is not None:
                err_content = ""
                if log_path.is_file():
                    try:
                        with open(log_path, "r", encoding="utf-8") as f:
                            err_content = f.read()[-500:]
                    except Exception:
                        pass
                raise RuntimeError(
                    f"FilmCraft process exited prematurely with code {proc.returncode}. Log snippet:\n{err_content}"
                )
            try:
                client.connect()
                if client.ping():
                    connected = True
                    break
            except Exception:
                pass
            time.sleep(0.2)

        client.close()

        if not connected:
            if proc.poll() is None:
                proc.terminate()
            raise TimeoutError(
                f"Timed out waiting {timeout}s for FilmCraft control server on port {port} to respond."
            )

        state = {
            "status": "running",
            "port": port,
            "host": DEFAULT_HOST,
            "pid": pid,
            "binary": bin_path,
            "project_path": resolved_proj,
            "background": background,
            "started_at": _get_utc_now_iso(),
            "last_heartbeat": _get_utc_now_iso(),
        }
        CompanionStateManager.save_state(state, base)
        return state

    @classmethod
    def stop(
        cls,
        port: Optional[int] = None,
        base_dir: Optional[Union[str, Path]] = None,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Gracefully stop FilmCraft process via app.quit or SIGTERM."""
        base = Path(base_dir).resolve() if base_dir else Path.cwd()
        state = CompanionStateManager.load_state(base) or {}
        target_port = port or state.get("port") or DEFAULT_PORT
        target_pid = state.get("pid")

        stopped_cleanly = False

        # Attempt RPC app.quit
        if cls.is_port_listening(target_port):
            client = FilmCraftControlClient(port=target_port, timeout=2.0)
            try:
                client.connect()
                client.quit_app()
                client.close()
                stopped_cleanly = True
            except Exception:
                client.close()

        # If PID known, verify termination or send signals
        if target_pid and is_pid_alive(target_pid):
            start_wait = time.time()
            while time.time() - start_wait < 2.0:
                if not is_pid_alive(target_pid):
                    stopped_cleanly = True
                    break
                time.sleep(0.1)

            if is_pid_alive(target_pid):
                try:
                    os.kill(target_pid, signal.SIGTERM)
                    time.sleep(1.0)
                except OSError:
                    pass

            if is_pid_alive(target_pid):
                try:
                    os.kill(target_pid, signal.SIGKILL)
                    time.sleep(0.5)
                except OSError:
                    pass

        CompanionStateManager.clear_state(base)
        return {
            "status": "stopped",
            "port": target_port,
            "pid": target_pid,
            "clean": stopped_cleanly,
            "timestamp": _get_utc_now_iso(),
        }


# --- Status & Health Inspection ---


def check_health(
    port: Optional[int] = None,
    host: str = DEFAULT_HOST,
    timeout: float = 3.0,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Inspect FilmCraft health, process state, playhead position, and project."""
    base = Path(base_dir).resolve() if base_dir else Path.cwd()
    state = CompanionStateManager.load_state(base) or {}
    resolved_port = port or state.get("port") or DEFAULT_PORT
    pid = state.get("pid")
    proc_alive = is_pid_alive(pid) if pid else None

    client = FilmCraftControlClient(host=host, port=resolved_port, timeout=timeout)
    try:
        client.connect()
        playback = client.get_playback_status()
        project = {}
        try:
            project = client.inspect_project()
        except Exception:
            pass
        client.close()

        # Update heartbeat in state file if present
        if state:
            state["last_heartbeat"] = _get_utc_now_iso()
            CompanionStateManager.save_state(state, base)

        return {
            "status": "healthy",
            "connected": True,
            "host": host,
            "port": resolved_port,
            "pid": pid,
            "process_alive": proc_alive,
            "project_name": project.get("name"),
            "project_path": project.get("path") or state.get("project_path"),
            "dirty": project.get("dirty", False),
            "revision": project.get("revision", 0),
            "active_sequence": project.get("activeSequence"),
            "playhead_ticks": playback.get("playhead", 0),
            "playhead_seconds": playback.get("seconds", 0.0),
            "playhead_timecode": playback.get("timecode", "00:00:00:00"),
            "playing": playback.get("playing", False),
            "timestamp": _get_utc_now_iso(),
        }
    except Exception as e:
        client.close()
        return {
            "status": "disconnected",
            "connected": False,
            "host": host,
            "port": resolved_port,
            "pid": pid,
            "process_alive": proc_alive,
            "error": str(e),
            "timestamp": _get_utc_now_iso(),
        }


# --- Timeline Reload & Playback Control ---


def reload_timeline(
    project_path: Optional[Union[str, Path]] = None,
    port: Optional[int] = None,
    host: str = DEFAULT_HOST,
    timeout: float = DEFAULT_TIMEOUT,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Dispatch project reload to FilmCraft GUI.

    If project_path is specified, opens that project file. If omitted,
    reverts the current project from disk baseline.
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd()
    state = CompanionStateManager.load_state(base) or {}
    resolved_port = port or state.get("port") or DEFAULT_PORT

    client = FilmCraftControlClient(host=host, port=resolved_port, timeout=timeout)
    client.connect()

    action_taken = ""
    target_path = None
    if project_path:
        target_path = str(Path(project_path).resolve())
        # Inspect current project path
        curr_proj = {}
        try:
            curr_proj = client.inspect_project()
        except Exception:
            pass

        if curr_proj.get("path") == target_path:
            # Same path: try file.revert first, fall back to file.open
            try:
                client.revert_project()
                action_taken = "file.revert"
            except Exception:
                client.open_project(target_path)
                action_taken = "file.open"
        else:
            client.open_project(target_path)
            action_taken = "file.open"
    else:
        # Revert current project
        try:
            curr_proj = client.inspect_project()
            target_path = curr_proj.get("path")
        except Exception:
            pass

        try:
            client.revert_project()
            action_taken = "file.revert"
        except Exception as e:
            if target_path:
                client.open_project(target_path)
                action_taken = "file.open"
            else:
                client.close()
                raise RuntimeError(f"Failed to reload project: {e}")

    # Inspect refreshed project state
    refreshed_proj = {}
    try:
        refreshed_proj = client.inspect_project()
    except Exception:
        pass
    playback = client.get_playback_status()
    client.close()

    # Update companion state
    if state and target_path:
        state["project_path"] = target_path
        state["last_heartbeat"] = _get_utc_now_iso()
        CompanionStateManager.save_state(state, base)

    return {
        "status": "reloaded",
        "action": action_taken,
        "project_path": refreshed_proj.get("path") or target_path,
        "project_name": refreshed_proj.get("name"),
        "revision": refreshed_proj.get("revision", 0),
        "dirty": refreshed_proj.get("dirty", False),
        "active_sequence": refreshed_proj.get("activeSequence"),
        "playhead_seconds": playback.get("seconds", 0.0),
        "playhead_timecode": playback.get("timecode", "00:00:00:00"),
        "timestamp": _get_utc_now_iso(),
    }


def seek_timeline(
    seconds: Optional[float] = None,
    frame: Optional[int] = None,
    timecode: Optional[str] = None,
    ticks: Optional[int] = None,
    port: Optional[int] = None,
    host: str = DEFAULT_HOST,
    timeout: float = DEFAULT_TIMEOUT,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Seek timeline playhead to specified seconds, frame, timecode, or ticks."""
    base = Path(base_dir).resolve() if base_dir else Path.cwd()
    state = CompanionStateManager.load_state(base) or {}
    resolved_port = port or state.get("port") or DEFAULT_PORT

    client = FilmCraftControlClient(host=host, port=resolved_port, timeout=timeout)
    client.connect()

    if seconds is not None:
        client.seek_seconds(seconds)
    elif frame is not None:
        client.seek_frame(frame)
    elif timecode is not None:
        client.seek_timecode(timecode)
    elif ticks is not None:
        client.seek_ticks(ticks)
    else:
        client.close()
        raise ValueError("Must provide one of: --seconds, --frame, --timecode, or --ticks")

    status = client.get_playback_status()
    client.close()
    return status


def set_playback(
    action: str,
    port: Optional[int] = None,
    host: str = DEFAULT_HOST,
    timeout: float = DEFAULT_TIMEOUT,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Start ('play') or pause ('stop') timeline playback."""
    base = Path(base_dir).resolve() if base_dir else Path.cwd()
    state = CompanionStateManager.load_state(base) or {}
    resolved_port = port or state.get("port") or DEFAULT_PORT

    client = FilmCraftControlClient(host=host, port=resolved_port, timeout=timeout)
    client.connect()
    if action == "play":
        status = client.play()
    elif action == "stop":
        status = client.stop()
    else:
        client.close()
        raise ValueError(f"Unknown playback action: {action!r}")
    client.close()
    return status


# --- Project File Watcher ---


def watch_project_file(
    project_path: Union[str, Path],
    poll_interval: float = 0.5,
    timeout: Optional[float] = None,
    once: bool = False,
    flag_file: Optional[Union[str, Path]] = None,
    port: Optional[int] = None,
    host: str = DEFAULT_HOST,
    base_dir: Optional[Union[str, Path]] = None,
    on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[Dict[str, Any]]:
    """Monitor .fcproj file mtime to detect operator save events in FilmCraft GUI.

    When the user saves changes in FilmCraft (Ctrl+S / File -> Save), the
    file's mtime updates. This watcher captures the event, emits an alert,
    updates flag files, and notifies the pipeline.
    """
    proj_path = Path(project_path).resolve()
    base = Path(base_dir).resolve() if base_dir else proj_path.parent
    flag_path = Path(flag_file).resolve() if flag_file else base / DEFAULT_FLAG_FILENAME

    if not proj_path.exists():
        raise FileNotFoundError(f"Project file to watch does not exist: {proj_path}")

    last_stat = proj_path.stat()
    last_mtime = last_stat.st_mtime
    last_size = last_stat.st_size

    resolved_port = port
    if resolved_port is None:
        state = CompanionStateManager.load_state(base) or {}
        resolved_port = state.get("port")

    start_time = time.time()

    while True:
        if timeout is not None and (time.time() - start_time) >= timeout:
            return None

        time.sleep(poll_interval)

        try:
            curr_stat = proj_path.stat()
        except OSError:
            continue

        curr_mtime = curr_stat.st_mtime
        curr_size = curr_stat.st_size

        if curr_mtime > last_mtime or (curr_size != last_size and curr_mtime >= last_mtime):
            # Save event detected!
            last_mtime = curr_mtime
            last_size = curr_size

            # Probe FilmCraft control server if reachable
            proj_info = {}
            if resolved_port and ProcessManager.is_port_listening(resolved_port, host):
                client = FilmCraftControlClient(host=host, port=resolved_port, timeout=1.5)
                try:
                    client.connect()
                    proj_info = client.inspect_project()
                    client.close()
                except Exception:
                    client.close()

            event = {
                "event": "project_saved",
                "path": str(proj_path),
                "mtime": curr_mtime,
                "mtime_iso": datetime.fromtimestamp(curr_mtime, timezone.utc).isoformat(),
                "size": curr_size,
                "revision": proj_info.get("revision"),
                "dirty": proj_info.get("dirty", False),
                "active_sequence": proj_info.get("activeSequence"),
                "timestamp": _get_utc_now_iso(),
            }

            # Update flag file
            try:
                with open(flag_path, "w", encoding="utf-8") as f:
                    json.dump(event, f, indent=2)
                    f.write("\n")
            except Exception:
                pass

            # Update companion state file
            state = CompanionStateManager.load_state(base)
            if state:
                state["last_saved_mtime"] = curr_mtime
                state["last_heartbeat"] = _get_utc_now_iso()
                CompanionStateManager.save_state(state, base)

            if on_save_callback:
                on_save_callback(event)

            if once:
                return event


# --- Embedded Mock Control Server for Automated Testing ---


class MockFilmCraftServer(threading.Thread):
    """Minimal zero-dependency mock FilmCraft JSON-lines RPC server.

    Emulates the FilmCraft --control protocol for headless CI, unit tests,
    and environments lacking graphical X11 displays.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = 0):
        super().__init__(daemon=True)
        self.host = host
        self.requested_port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.requested_port))
        self.port = self.server_socket.getsockname()[1]
        self.running = False
        self.ready_event = threading.Event()

        # Simulated state
        self.playing: bool = False
        self.playhead_ticks: int = 0
        self.project_name: str = "Mock Project"
        self.project_path: Optional[str] = "/mock/path/project.fcproj"
        self.dirty: bool = False
        self.revision: int = 1
        self.active_sequence: int = 21

    def run(self):
        self.server_socket.listen(5)
        self.running = True
        self.ready_event.set()

        while self.running:
            try:
                self.server_socket.settimeout(0.5)
                client_sock, _ = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            client_thread = threading.Thread(
                target=self._handle_client, args=(client_sock,), daemon=True
            )
            client_thread.start()

    def _handle_client(self, client_sock: socket.socket):
        rfile = client_sock.makefile("r", encoding="utf-8")
        wfile = client_sock.makefile("w", encoding="utf-8")
        try:
            while self.running:
                line = rfile.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                    req_id = req.get("id")
                    method = req.get("method")
                    params = req.get("params") or {}
                    resp = self._dispatch(req_id, method, params)
                except Exception as e:
                    resp = {"id": None, "ok": False, "error": str(e)}

                wfile.write(json.dumps(resp) + "\n")
                wfile.flush()
        except Exception:
            pass
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _dispatch(self, req_id: Any, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if method == "ui.playback":
            action = params.get("action")
            if action == "play":
                self.playing = True
            elif action == "stop":
                self.playing = False
            return {
                "id": req_id,
                "ok": True,
                "result": {"playhead": self.playhead_ticks, "playing": self.playing},
            }

        elif method == "ui.inspect":
            return {
                "id": req_id,
                "ok": True,
                "result": {"activeSequence": self.active_sequence, "fps": 30.0},
            }

        elif method == "app.quit":
            self.running = False
            return {"id": req_id, "ok": True, "result": None}

        elif method == "engine.execute":
            command = params.get("command")
            cmd_params = params.get("params") or {}

            if command == "playhead.set":
                if "seconds" in cmd_params:
                    self.playhead_ticks = int(cmd_params["seconds"] * TICKS_PER_SECOND)
                elif "frame" in cmd_params:
                    self.playhead_ticks = int(cmd_params["frame"] * (TICKS_PER_SECOND / 30))
                elif "time" in cmd_params:
                    self.playhead_ticks = int(cmd_params["time"])
                return {"id": req_id, "ok": True, "result": {"time": self.playhead_ticks}}

            elif command == "project.inspect":
                return {
                    "id": req_id,
                    "ok": True,
                    "result": {
                        "name": self.project_name,
                        "path": self.project_path,
                        "dirty": self.dirty,
                        "revision": self.revision,
                        "activeSequence": self.active_sequence,
                    },
                }

            elif command == "sequence.inspect":
                return {
                    "id": req_id,
                    "ok": True,
                    "result": {
                        "id": self.active_sequence,
                        "name": "Main Sequence",
                        "duration": 2540160000000,
                    },
                }

            elif command == "file.open":
                self.project_path = cmd_params.get("path")
                self.revision += 1
                self.dirty = False
                return {
                    "id": req_id,
                    "ok": True,
                    "result": {
                        "path": self.project_path,
                        "schemaVersion": 12,
                        "missingMedia": 0,
                    },
                }

            elif command == "file.revert":
                self.dirty = False
                return {"id": req_id, "ok": True, "result": {"reverted": True}}

            return {
                "id": req_id,
                "ok": False,
                "error": f"Unknown engine command: {command!r}",
            }

        return {"id": req_id, "ok": False, "error": f"Unknown RPC method: {method!r}"}

    def stop_server(self):
        self.running = False
        try:
            self.server_socket.close()
        except Exception:
            pass


# --- Self-Test & Automated Verification Harness ---


def run_self_tests(live: bool = False, mock_only: bool = False) -> bool:
    """Run automated verification suite for client, daemon, and watcher."""
    print("=" * 70)
    print("RUNNING GUI COMPANION AUTOMATED SELF-TEST SUITE")
    print("=" * 70)
    passed = 0
    total = 0

    def assert_test(name: str, condition: bool, msg: str = ""):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}: {msg}")

    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # 1. Start Mock Server
        mock_server = MockFilmCraftServer()
        mock_server.start()
        mock_server.ready_event.wait(timeout=3.0)
        port = mock_server.port

        try:
            client = FilmCraftControlClient(port=port, timeout=2.0)
            client.connect()

            # Test 1: Ping & Handshake
            assert_test("Connection & Ping", client.ping())

            # Test 2: Playback Control
            status_stop = client.stop()
            assert_test(
                "Stop Playback",
                status_stop["playing"] is False and "seconds" in status_stop,
            )

            status_play = client.play()
            assert_test(
                "Start Playback",
                status_play["playing"] is True and status_play["playhead"] == 0,
            )

            # Test 3: Playhead Seeking
            target_sec = 4.5
            res_sec = client.seek_seconds(target_sec)
            assert_test("Seek Seconds", abs(res_sec - target_sec) < 0.001)

            res_ticks = client.seek_ticks(TICKS_PER_SECOND * 2)
            assert_test("Seek Ticks", res_ticks == TICKS_PER_SECOND * 2)

            pb = client.get_playback_status()
            assert_test("Playback Status Inspection", pb["seconds"] == 2.0)

            # Test 4: Project & Sequence Inspection
            proj = client.inspect_project()
            assert_test(
                "Project Inspection",
                proj.get("name") == "Mock Project" and proj.get("activeSequence") == 21,
            )

            seq = client.inspect_sequence()
            assert_test("Sequence Inspection", seq.get("name") == "Main Sequence")

            # Test 5: File Operations (open & revert)
            open_res = client.open_project(temp_path / "test.fcproj")
            assert_test(
                "File Open Command",
                open_res.get("path") == str((temp_path / "test.fcproj").resolve()),
            )

            revert_res = client.revert_project()
            assert_test("File Revert Command", revert_res.get("reverted") is True)

            # Test 6: Error Handling
            caught_error = False
            try:
                client.call("nonexistent.rpc.method")
            except RuntimeError as e:
                caught_error = "Unknown RPC method" in str(e)
            assert_test("Error Handling on Unknown Method", caught_error)

            client.close()

            # Test 7: State Management
            test_state = {
                "status": "running",
                "port": port,
                "pid": 99999,
                "started_at": _get_utc_now_iso(),
            }
            state_file = CompanionStateManager.save_state(test_state, temp_path)
            assert_test("Save State File", state_file.is_file())

            loaded_state = CompanionStateManager.load_state(temp_path)
            assert_test(
                "Load State File",
                loaded_state is not None and loaded_state.get("port") == port,
            )

            # Test 8: Health Check Function
            health = check_health(port=port, base_dir=temp_path)
            assert_test(
                "Health Check Function",
                health["status"] == "healthy" and health["connected"] is True,
            )

            # Test 9: Reload Timeline Function
            reload_res = reload_timeline(
                project_path=temp_path / "updated.fcproj",
                port=port,
                base_dir=temp_path,
            )
            assert_test("Reload Timeline Function", reload_res["status"] == "reloaded")

            # Test 10: Project File Watcher Detection
            dummy_proj = temp_path / "project.fcproj"
            with open(dummy_proj, "w", encoding="utf-8") as f:
                f.write('{"initial": true}\n')

            watcher_event = None

            def watcher_thread():
                nonlocal watcher_event
                watcher_event = watch_project_file(
                    project_path=dummy_proj,
                    poll_interval=0.1,
                    timeout=3.0,
                    once=True,
                    port=port,
                    base_dir=temp_path,
                )

            wt = threading.Thread(target=watcher_thread, daemon=True)
            wt.start()
            time.sleep(0.2)

            # Modify project file
            with open(dummy_proj, "w", encoding="utf-8") as f:
                f.write('{"initial": false, "saved": true}\n')

            wt.join(timeout=2.0)
            assert_test(
                "Project File Watcher Save Detection",
                watcher_event is not None and watcher_event.get("event") == "project_saved",
            )

            flag_file = temp_path / DEFAULT_FLAG_FILENAME
            assert_test("Flag File Generated", flag_file.is_file())

            # Test 11: Graceful App Quit
            client = FilmCraftControlClient(port=port, timeout=2.0)
            client.connect()
            client.quit_app()
            client.close()
            time.sleep(0.2)
            assert_test("Graceful App Quit", mock_server.running is False)

        finally:
            mock_server.stop_server()

        # Test 12: Live FilmCraft binary verification (if requested or available)
        bin_path = ProcessManager.find_filmcraft_binary()
        if (live or not mock_only) and bin_path and os.environ.get("DISPLAY"):
            print("\n  [LIVE TEST] Testing against real FilmCraft binary on PATH...")
            live_port = 9889
            try:
                started = ProcessManager.start(
                    port=live_port,
                    binary=bin_path,
                    demo=True,
                    background=True,
                    timeout=8.0,
                    base_dir=temp_path,
                )
                assert_test(
                    "Live FilmCraft Start & Attach",
                    started.get("status") in ("running", "attached"),
                )

                live_health = check_health(port=live_port, base_dir=temp_path)
                assert_test("Live Health Inspection", live_health["connected"] is True)

                live_seek = seek_timeline(seconds=1.5, port=live_port, base_dir=temp_path)
                assert_test("Live Playhead Seek", abs(live_seek["seconds"] - 1.5) < 0.1)

                stopped = ProcessManager.stop(port=live_port, base_dir=temp_path)
                assert_test("Live FilmCraft Clean Shutdown", stopped["clean"] is True)
            except Exception as e:
                assert_test("Live FilmCraft Verification", False, str(e))
            finally:
                ProcessManager.stop(port=live_port, base_dir=temp_path)
        else:
            print("\n  [INFO] Skipping live binary test (use --live or verify DISPLAY/binary).")

    print("=" * 70)
    print(f"RESULTS: {passed}/{total} assertions passed.")
    print("=" * 70)
    return passed == total


# --- Interactive Demonstration Walkthrough ---


def run_demo(
    port: int = DEFAULT_PORT,
    mock: bool = False,
    project_path: Optional[str] = None,
) -> None:
    """Run an interactive demonstration of the GUI companion workflow."""
    print("╔════════════════════════════════════════════════════════════════════════╗")
    print("║     STORYTELLER FILMCRAFT GUI COMPANION SIDECAR DAEMON DEMO            ║")
    print("╚════════════════════════════════════════════════════════════════════════╝\n")

    mock_server = None
    if mock:
        print("[DEMO 1/6] Launching embedded Mock FilmCraft Control Server...")
        mock_server = MockFilmCraftServer(port=port)
        mock_server.start()
        mock_server.ready_event.wait(timeout=2.0)
        port = mock_server.port
        print(f"  -> Mock server listening on 127.0.0.1:{port}\n")
    else:
        print(f"[DEMO 1/6] Starting / Attaching to FilmCraft on 127.0.0.1:{port}...")
        try:
            started = ProcessManager.start(port=port, project_path=project_path, background=True)
            print(f"  -> Process status: {started.get('status')}, PID: {started.get('pid')}\n")
        except Exception as e:
            print(f"  -> Failed to start live binary ({e}). Falling back to mock server...")
            mock_server = MockFilmCraftServer(port=port)
            mock_server.start()
            mock_server.ready_event.wait(timeout=2.0)
            port = mock_server.port

    try:
        # Step 2: Health Check
        print("[DEMO 2/6] Querying Live Health & Timeline Status...")
        health = check_health(port=port)
        print(f"  -> Status:             {health.get('status').upper()}")
        print(f"  -> Connected:          {health.get('connected')}")
        print(f"  -> Port:               {health.get('port')}")
        print(f"  -> Project Name:       {health.get('project_name')}")
        print(f"  -> Project Path:       {health.get('project_path')}")
        print(f"  -> Active Sequence:    {health.get('active_sequence')}")
        print(f"  -> Playhead:           {health.get('playhead_seconds'):.3f}s ({health.get('playhead_timecode')})")
        print(f"  -> Playing State:      {health.get('playing')}\n")

        # Step 3: Playhead Seek
        print("[DEMO 3/6] Seeking Timeline Playhead to 3.0 seconds...")
        seek_res = seek_timeline(seconds=3.0, port=port)
        print(f"  -> Updated Playhead:   {seek_res.get('seconds'):.3f}s ({seek_res.get('timecode')})\n")

        # Step 4: Playback Toggle
        print("[DEMO 4/6] Starting Playback for 1.0 second, then pausing...")
        set_playback("play", port=port)
        time.sleep(1.0)
        pb = set_playback("stop", port=port)
        print(f"  -> Playback Stopped at: {pb.get('seconds'):.3f}s ({pb.get('timecode')})\n")

        # Step 5: Timeline Reload Simulation
        print("[DEMO 5/6] Simulating Pipeline Step Completion (Timeline Reload)...")
        reload_res = reload_timeline(project_path=project_path, port=port)
        print(f"  -> Reload Action:      {reload_res.get('action')}")
        print(f"  -> Project Revision:   {reload_res.get('revision')}")
        print(f"  -> Reload Status:      {reload_res.get('status')}\n")

        # Step 6: Project File Watcher Demonstration
        print("[DEMO 6/6] Demonstrating Project File Save Watcher...")
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".fcproj", delete=False) as tf:
            tf.write('{"version": 1}\n')
            temp_fcproj = tf.name

        flag_file = temp_fcproj + ".flag"
        try:
            print(f"  -> Watching temporary project file: {temp_fcproj}")
            event_holder = []

            def watch_worker():
                ev = watch_project_file(
                    project_path=temp_fcproj,
                    poll_interval=0.1,
                    timeout=3.0,
                    once=True,
                    flag_file=flag_file,
                    port=port,
                )
                if ev:
                    event_holder.append(ev)

            wt = threading.Thread(target=watch_worker, daemon=True)
            wt.start()
            time.sleep(0.3)

            # Simulate editor saving changes
            print("  -> Simulating operator pressing Ctrl+S in FilmCraft GUI...")
            with open(temp_fcproj, "a", encoding="utf-8") as f:
                f.write('{"updated_by_operator": true}\n')

            wt.join(timeout=2.0)
            if event_holder:
                ev = event_holder[0]
                print(f"  -> SAVE EVENT DETECTED: mtime={ev.get('mtime_iso')} size={ev.get('size')}B")
                print(f"  -> Pipeline Flag Written: {flag_file}\n")
            else:
                print("  -> Watcher timeout without detected event.\n")
        finally:
            for p in (temp_fcproj, flag_file):
                if os.path.exists(p):
                    os.unlink(p)

        print("════════════════════════════════════════════════════════════════════════")
        print("DEMO COMPLETE: GUI Companion is fully operational and pipeline-ready!")
        print("════════════════════════════════════════════════════════════════════════\n")

    finally:
        if mock_server:
            mock_server.stop_server()


# --- CLI Entry Point ---


def main():
    parser = argparse.ArgumentParser(
        prog="gui_companion.py",
        description="GUI Companion Sidecar Daemon for Storyteller FilmCraft.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to execute")

    # start
    p_start = subparsers.add_parser("start", help="Start FilmCraft GUI or attach to running instance")
    p_start.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"TCP port (default: {DEFAULT_PORT})")
    p_start.add_argument("--project", type=str, default=None, help="Project .fcproj file to open on start")
    p_start.add_argument("--demo", action="store_true", help="Launch with FilmCraft built-in demo project")
    p_start.add_argument("--bin", type=str, default=None, help="Path to filmcraft binary")
    p_start.add_argument("--foreground", action="store_true", help="Run process in foreground instead of background")
    p_start.add_argument("--timeout", type=float, default=10.0, help="Startup timeout in seconds")
    p_start.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # stop
    p_stop = subparsers.add_parser("stop", help="Stop FilmCraft GUI companion process")
    p_stop.add_argument("-p", "--port", type=int, default=None, help="TCP port of instance")
    p_stop.add_argument("--timeout", type=float, default=5.0, help="Shutdown timeout in seconds")
    p_stop.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # status
    p_status = subparsers.add_parser("status", help="Inspect live health and timeline state")
    p_status.add_argument("-p", "--port", type=int, default=None, help="TCP port to probe")
    p_status.add_argument("--timeout", type=float, default=3.0, help="Probe timeout in seconds")
    p_status.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # reload
    p_reload = subparsers.add_parser("reload", help="Dispatch timeline reload on step completion")
    p_reload.add_argument("--project", type=str, default=None, help="Project .fcproj path to open/reload")
    p_reload.add_argument("-p", "--port", type=int, default=None, help="TCP port")
    p_reload.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # seek
    p_seek = subparsers.add_parser("seek", help="Seek playhead position")
    p_seek.add_argument("-s", "--seconds", type=float, default=None, help="Seek target in seconds")
    p_seek.add_argument("-f", "--frame", type=int, default=None, help="Seek target frame index")
    p_seek.add_argument("-t", "--timecode", type=str, default=None, help="Seek target SMPTE timecode (HH:MM:SS:FF)")
    p_seek.add_argument("--ticks", type=int, default=None, help="Seek target in exact FilmCraft ticks")
    p_seek.add_argument("-p", "--port", type=int, default=None, help="TCP port")
    p_seek.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # play
    p_play = subparsers.add_parser("play", help="Start playback in FilmCraft")
    p_play.add_argument("-p", "--port", type=int, default=None, help="TCP port")
    p_play.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # stop-playback
    p_pause = subparsers.add_parser("stop-playback", help="Stop / pause playback in FilmCraft")
    p_pause.add_argument("-p", "--port", type=int, default=None, help="TCP port")
    p_pause.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # watch
    p_watch = subparsers.add_parser("watch", help="Watch project file for operator save events")
    p_watch.add_argument("--project", type=str, required=True, help="Path to .fcproj file to monitor")
    p_watch.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds")
    p_watch.add_argument("--timeout", type=float, default=None, help="Watch timeout in seconds")
    p_watch.add_argument("--once", action="store_true", help="Exit after first save event")
    p_watch.add_argument("--flag-file", type=str, default=None, help="Flag file to write on save")
    p_watch.add_argument("-p", "--port", type=int, default=None, help="Optional port to query project revision")
    p_watch.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # test
    p_test = subparsers.add_parser("test", help="Run automated self-tests")
    p_test.add_argument("--live", action="store_true", help="Force live binary tests")
    p_test.add_argument("--mock", action="store_true", help="Mock tests only (skip live binary)")
    p_test.add_argument("--json", action="store_true", help="Output test results in JSON")

    # demo
    p_demo = subparsers.add_parser("demo", help="Run interactive demonstration walkthrough")
    p_demo.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help="Port to run demo on")
    p_demo.add_argument("--mock", action="store_true", help="Use mock server instead of live FilmCraft")
    p_demo.add_argument("--project", type=str, default=None, help="Project .fcproj file")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    try:
        if args.subcommand == "start":
            res = ProcessManager.start(
                port=args.port,
                project_path=args.project,
                binary=args.bin,
                demo=args.demo,
                background=not args.foreground,
                timeout=args.timeout,
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[GUI COMPANION] Started FilmCraft (status={res.get('status')}, port={res.get('port')}, pid={res.get('pid')})")

        elif args.subcommand == "stop":
            res = ProcessManager.stop(port=args.port, timeout=args.timeout)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[GUI COMPANION] Stopped FilmCraft (port={res.get('port')}, clean={res.get('clean')})")

        elif args.subcommand == "status":
            res = check_health(port=args.port, timeout=args.timeout)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                if res.get("connected"):
                    print(f"FilmCraft Companion: HEALTHY (port={res['port']}, pid={res.get('pid')})")
                    print(f"  Project:  {res.get('project_name')} ({res.get('project_path')})")
                    print(f"  Playhead: {res.get('playhead_seconds', 0.0):.3f}s [{res.get('playhead_timecode')}]")
                    print(f"  State:    {'PLAYING' if res.get('playing') else 'PAUSED'}, dirty={res.get('dirty')}, rev={res.get('revision')}")
                else:
                    print(f"FilmCraft Companion: DISCONNECTED (port={res['port']}) - {res.get('error')}")
            if not res.get("connected"):
                sys.exit(1)

        elif args.subcommand == "reload":
            res = reload_timeline(project_path=args.project, port=args.port)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[GUI COMPANION] Timeline reloaded via {res.get('action')}: {res.get('project_path')} (rev {res.get('revision')})")

        elif args.subcommand == "seek":
            res = seek_timeline(
                seconds=args.seconds,
                frame=args.frame,
                timecode=args.timecode,
                ticks=args.ticks,
                port=args.port,
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[GUI COMPANION] Playhead seeked to: {res.get('seconds', 0.0):.3f}s [{res.get('timecode')}]")

        elif args.subcommand == "play":
            res = set_playback("play", port=args.port)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[GUI COMPANION] Playback started at {res.get('seconds', 0.0):.3f}s")

        elif args.subcommand == "stop-playback":
            res = set_playback("stop", port=args.port)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"[GUI COMPANION] Playback stopped at {res.get('seconds', 0.0):.3f}s")

        elif args.subcommand == "watch":
            def notify_save(event: Dict[str, Any]):
                if not args.json:
                    print(f"[GUI COMPANION WATCHER] Project file saved! path={event.get('path')} mtime={event.get('mtime_iso')}")

            res = watch_project_file(
                project_path=args.project,
                poll_interval=args.interval,
                timeout=args.timeout,
                once=args.once,
                flag_file=args.flag_file,
                port=args.port,
                on_save_callback=notify_save,
            )
            if res:
                if args.json:
                    print(json.dumps(res, indent=2))
            else:
                if args.timeout is not None:
                    sys.stderr.write("Watcher timed out before any save event.\n")
                    sys.exit(2)

        elif args.subcommand == "test":
            success = run_self_tests(live=args.live, mock_only=args.mock)
            if args.json:
                print(json.dumps({"success": success}))
            sys.exit(0 if success else 1)

        elif args.subcommand == "demo":
            run_demo(port=args.port, mock=args.mock, project_path=args.project)

    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
