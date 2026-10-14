# FilmCraft Control Server Protocol & Command Schema

> **Document Type**: Technical Research & Protocol Specification  
> **Source Binary**: `/home/mhawar/.local/share/filmcraft/squashfs-root/usr/bin/filmcraft` (v2026.10, x86_64 ELF)  
> **Client Driver**: `/home/mhawar/.local/share/filmcraft/squashfs-root/usr/bin/filmcraft-cli`  
> **Primary References**: Issue #23, Parent Map #22 (Continuous Live-GUI Feedback & Preference Codification Engine), Blocking Issue #25 (`scripts/gui_companion.py`)

---

## 1. Executive Summary

FilmCraft embeds a high-performance localhost JSON-lines RPC control server designed to drive the live desktop editor from external daemons, shell scripts (`filmcraft-cli --bridge`), and companion processes (`scripts/gui_companion.py`).

The server operates over streaming TCP sockets bound strictly to `127.0.0.1`. It uses line-delimited JSON (`\n`) for both requests and responses. It exposes a dual-tier API:
1. **Direct RPC Methods**: 22 top-level methods for runtime UI inspection (`ui.inspect`), viewport screenshotting (`ui.screenshot`), panel management (`ui.panel.show`/`close`), input automation (`ui.click`, `ui.type`), telemetry (`perf.stats`), and real-time playback control (`ui.playback`).
2. **Command Dispatcher (`engine.execute`)**: An execution pipeline providing access to all **675 internal editor commands** across 40 namespaces (e.g., `file.open`, `file.revert`, `playhead.set`, `sequence.inspect`, `project.inspect`).

---

## 2. Server Configuration & Port Binding

### 2.1 Invocation Flags & Environment Variables

The control server can be enabled via CLI or environment variable:

| Mechanism | Syntax / Format | Description |
|---|---|---|
| **CLI Flag** | `filmcraft --control <port>` | Launches the control server on `127.0.0.1:<port>`. |
| **Env Variable** | `FILMCRAFT_CONTROL_PORT=<port>` | Equivalent to `--control <port>`. Read during app initialization. |

```bash
# Example invocation with control server enabled:
filmcraft --empty --no-recover --control 9876
# Or using the built-in demo project:
filmcraft --demo --control 9876
```

### 2.2 Network Binding & Interface Security

* **Listening Address**: `127.0.0.1:<port>` (IPv4 loopback only).
* **Socket Backlog**: 128.
* **Security Model**: The server binds exclusively to the loopback interface (`INADDR_LOOPBACK`). In `filmcraft-cli`, any remote non-loopback address passed to `--bridge` is explicitly rejected before connecting (`"bridge address must be loopback, got ..."`).
* **Port Conflict Behavior**: If the designated port is already occupied (e.g. by another running instance), the server outputs an error to `stderr` and the application continues to run without the control server:
  ```text
  filmcraft: control server failed to bind 127.0.0.1:<port>: Address already in use (os error 98)
  ```
* **Concurrency Limits**: The server permits up to **16 concurrent TCP client connections**. Attempting a 17th simultaneous connection immediately returns:
  ```json
  {"error":"too many control connections","ok":false}
  ```
* **Maximum Line / Request Size**: Exactly **4,194,304 bytes** (4 MiB). If a client transmits a line exceeding 4MB, the server returns:
  ```json
  {"error":"request line longer than 4194304 bytes; closing the connection","ok":false}
  ```
  and promptly terminates the TCP connection.

---

## 3. Wire Protocol & RPC Framing

### 3.1 Request Wire Format

Requests must be sent as a single line of valid UTF-8 JSON terminated by a newline (`\n`):

```json
{
  "id": 1,
  "method": "<method_name>",
  "params": {}
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `integer` \| `string` \| `null` | Optional | Request correlation identifier. Echoed verbatim in the response. |
| `method` | `string` | **Required** | The RPC method to call (e.g., `engine.execute`, `ui.playback`). |
| `params` | `object` | Optional | Method arguments (defaults to `{}` if omitted). |

### 3.2 Response Wire Format

Responses are returned as a single line of UTF-8 JSON terminated by `\n`:

**Success Response:**
```json
{
  "id": 1,
  "ok": true,
  "result": { ... }
}
```

**Failure Response:**
```json
{
  "id": 1,
  "ok": false,
  "error": "human-readable error description"
}
```

### 3.3 Connection & Pipelining Semantics

* **Persistent Streaming**: Connections remain open across requests. Multiple requests can be pipelined over a single persistent TCP connection.
* **Fatal Protocol Errors (Socket Terminated)**:
  * Malformed JSON syntax: `{"error":"bad JSON (...); expected one JSON request object per line; closing the connection","ok":false}`
  * Non-object root: `{"error":"not a control request (expected a JSON object); closing the connection","ok":false}`
  * Missing string `method`: `{"error":"not a control request (missing string `method`); closing the connection","ok":false}`
  * Non-UTF-8 bytes: `{"error":"not a control request (invalid UTF-8); closing the connection","ok":false}`
  * Frame buffer overflow: `{"error":"request line longer than 4194304 bytes; closing the connection","ok":false}`
* **Application Errors (Socket Remains Open)**:
  * Unknown method names, unknown command IDs, disabled commands, or invalid command parameters return `"ok": false` but **do not** close the connection. Subsequent requests on the same socket continue executing normally.

---

## 4. Full Catalog of RPC Methods

Binary disassembly of FilmCraft's control server (`0x3953a53` jump table) reveals 22 supported top-level methods:

| Method | Parameters | Returns | Purpose |
|---|---|---|---|
| `engine.execute` | `{"command": str, "params": obj}` | Command result object | Dispatches one of the 675 engine commands |
| `engine.commands` | `{}` | `Array<CommandDescriptor>` | Lists all available engine commands and parameter schemas |
| `ui.playback` | `{"action": "play" \| "stop"}?` | `{"playhead": u64, "playing": bool}` | Controls/queries playback state and playhead ticks |
| `ui.inspect` | `{}` | `{"activeSequence": id?, "fps": f64, ...}` | Queries viewport status, FPS, and element count |
| `ui.elements` | `{}` | `Array<UIElement>` | Dumps interactive UI widget tree with bounding boxes `[x, y, w, h]` |
| `ui.screenshot` | `{}` | `{"path": str, "width": u32, "height": u32}` | Renders full viewport to `/tmp/filmcraft-screenshot.png` |
| `ui.timeline.hit` | `{"id": str} \| {"x": f32, "y": f32}` | `{"hit": str, "time": u64, "clip": id?, "track": id?}` | Spatial hit-testing on the timeline canvas |
| `ui.timeline.locate` | `{"clip": id}` | `{"x": f32, "y": f32}` | Resolves screen pixel coordinates for a timeline clip |
| `ui.panel.show` | `{"panel": str}` | `null` | Focuses/opens a docked panel (e.g., `"Timeline"`, `"Project"`) |
| `ui.panel.close` | `{"panel": str}` | `null` | Closes a docked panel |
| `ui.click` | `{"id": str} \| {"x": f32, "y": f32}` | `null` | Simulates a pointer click on a UI widget or screen coordinate |
| `ui.move` | `{"id": str} \| {"x": f32, "y": f32}` | `null` | Moves cursor to widget or coordinate |
| `ui.drag` | `{"from": ..., "to": ...}` | `null` | Simulates pointer drag between coordinates |
| `ui.type` | `{"text": str}` | `null` | Sends text input events |
| `ui.key` | `{"key": str}` | `null` | Sends key press (e.g. `"Space"`, `"Enter"`, `"Delete"`) |
| `ui.scroll` | `{"id": str \| "x": f32, "y": f32, "deltaY": f32}` | `null` | Dispatches scrollwheel events |
| `ui.set` | `{"id": str, "value": ...}` | `null` | Sets state on an interactive input widget |
| `ui.focus` | `{"id": str}` | `null` | Focuses a UI element |
| `ui.resize` | `{"width": f32, "height": f32}` | `null` | Resizes application window |
| `ui.menu.list` | `{}` | `Array<MenuItem>` | Dumps application menu tree |
| `ui.menu.invoke` | `{"command": str}` | `null` | Invokes menu item by command ID |
| `perf.stats` | `{}` | `{"decode": { ... }}` | Telemetry on media decoder cache and dropped frames |
| `app.quit` | `{}` | `null` | Shuts down FilmCraft |

---

## 5. Core Targeted Workflows

### 5.1 Loading & Reloading Projects

Project management commands are dispatched via `engine.execute`:

#### 1. Open an Existing Project
```json
// Request
{
  "id": 1,
  "method": "engine.execute",
  "params": {
    "command": "file.open",
    "params": {
      "path": "/absolute/path/to/project.fcproj"
    }
  }
}

// Response
{
  "id": 1,
  "ok": true,
  "result": {
    "path": "/absolute/path/to/project.fcproj",
    "schemaVersion": 12,
    "missingMedia": 0,
    "migrated": false
  }
}
```

#### 2. Reload / Revert Project from Disk
To discard external changes or revert back to disk baseline:
```json
// Request
{
  "id": 2,
  "method": "engine.execute",
  "params": {
    "command": "file.revert",
    "params": {}
  }
}

// Response
{
  "id": 2,
  "ok": true,
  "result": {
    "path": "/absolute/path/to/project.fcproj",
    "schemaVersion": 12,
    "missingMedia": 0,
    "migrated": false
  }
}
```

#### 3. Save / Save Copy
```json
// Save active project in place
{"id": 3, "method": "engine.execute", "params": {"command": "file.save", "params": {}}}

// Save a copy without changing active project binding
{"id": 4, "method": "engine.execute", "params": {"command": "file.saveCopy", "params": {"path": "/tmp/backup.fcproj"}}}
```

#### 4. Close Project
```json
{"id": 5, "method": "engine.execute", "params": {"command": "file.closeProject", "params": {"force": true}}}
```

---

### 5.2 Querying Timeline & Project Status

#### 1. Lightweight Playback Status (`ui.playback`)
Returns playhead position and playback state immediately without timeline tree traversal overhead:
```json
// Request
{"id": 10, "method": "ui.playback", "params": {}}

// Response
{
  "id": 10,
  "ok": true,
  "result": {
    "playhead": 1260755496000,
    "playing": false
  }
}
```
> [!NOTE]
> Time in FilmCraft is measured in integer **ticks** at **254,016,000,000 ticks per second** (exact multiples for 23.976, 24, 25, 29.97, 30, 50, 59.94, and 60 fps).

#### 2. Deep Sequence Timeline Inspection (`sequence.inspect`)
Inspects the full active timeline DOM: tracks, clips, transitions, effects, and markers:
```json
// Request
{
  "id": 11,
  "method": "engine.execute",
  "params": {
    "command": "sequence.inspect",
    "params": {} // Optionally: {"item": sequenceId}
  }
}

// Response
{
  "id": 11,
  "ok": true,
  "result": {
    "id": 21,
    "name": "Main Edit",
    "duration": 6801722928000,
    "durationFrames": 642,
    "in": null,
    "out": null,
    "videoTracks": [
      {
        "id": 15,
        "name": "Video 1",
        "enabled": true,
        "locked": false,
        "muted": false,
        "solo": false,
        "syncLock": true,
        "items": [
          {
            "clip": 29,
            "item": 8,
            "name": "City_Sunset.mp4",
            "start": 0,
            "startFrame": 0,
            "end": 2404970568000,
            "endFrame": 227,
            "duration": 2404970568000,
            "durationFrames": 227,
            "sourceIn": 0,
            "sourceOut": 2404970568000,
            "speed": 1.0,
            "effects": [
              {
                "effect": "motion",
                "enabled": true,
                "masks": 0,
                "params": {
                  "position": {"value": "Vec2(960.0, 540.0)"},
                  "scale": {"value": "Float(100.0)"}
                }
              }
            ]
          }
        ],
        "transitions": []
      }
    ],
    "audioTracks": [ ... ],
    "markers": [
      {
        "id": 800000,
        "name": "Open",
        "color": "Green",
        "comment": "",
        "kind": "Comment",
        "start": 0,
        "duration": 0
      }
    ]
  }
}
```

#### 3. Overall Project Inspection (`project.inspect`)
Queries project dirty state, active sequence ID, revision counter, and bin structure:
```json
// Request
{"id": 12, "method": "engine.execute", "params": {"command": "project.inspect", "params": {}}}

// Response
{
  "id": 12,
  "ok": true,
  "result": {
    "name": "Demo",
    "path": "/home/mhawar/project.fcproj",
    "dirty": false,
    "activeSequence": 21,
    "revision": 4,
    "sourceItem": null,
    "root": {
      "id": 1,
      "name": "Root",
      "children": [ ... ]
    }
  }
}
```

---

### 5.3 Seeking Playhead Position

Seeking is executed via the `playhead.set` command through `engine.execute`. The command supports four polymorphic units:

```json
// 1. By fractional seconds (float)
{"id": 20, "method": "engine.execute", "params": {"command": "playhead.set", "params": {"seconds": 5.0}}}

// 2. By integer frame number
{"id": 21, "method": "engine.execute", "params": {"command": "playhead.set", "params": {"frame": 120}}}

// 3. By SMPTE timecode string
{"id": 22, "method": "engine.execute", "params": {"command": "playhead.set", "params": {"timecode": "00:00:05:00"}}}

// 4. By exact ticks (int)
{"id": 23, "method": "engine.execute", "params": {"command": "playhead.set", "params": {"time": 1260755496000}}}
```

**Response Format:**
The server automatically snaps the playhead to the nearest video frame boundary and returns the updated timestamp in ticks:
```json
{
  "id": 20,
  "ok": true,
  "result": {
    "time": 1260755496000
  }
}
```

**Relative Playhead Step Commands:**
* `playhead.step`: `{"frames": 5}` or `{"frames": -5}`
* `playhead.stepForward`: Step forward 1 frame
* `playhead.stepBack`: Step back 1 frame
* `playhead.stepForward5`: Step forward 5 frames
* `playhead.stepBack5`: Step back 5 frames
* `playhead.start`: Jump to timeline start (`time: 0`)
* `playhead.end`: Jump to sequence end

---

### 5.4 Triggering Playback

Playback runtime state is controlled directly via the `ui.playback` RPC method:

#### Start Playback
```json
// Request
{
  "id": 30,
  "method": "ui.playback",
  "params": {
    "action": "play"
  }
}

// Response
{
  "id": 30,
  "ok": true,
  "result": {
    "playhead": 1260755496000,
    "playing": true
  }
}
```

#### Stop / Pause Playback
```json
// Request
{
  "id": 31,
  "method": "ui.playback",
  "params": {
    "action": "stop"
  }
}

// Response
{
  "id": 31,
  "ok": true,
  "result": {
    "playhead": 1313728416000,
    "playing": false
  }
}
```

#### Alternative: Toggle Playback via Keypress
Playback can also be toggled by simulating the spacebar press through `ui.key`:
```json
{"id": 32, "method": "ui.key", "params": {"key": "Space"}}
```

---

## 6. Reference Python Client (`FilmCraftControlClient`)

The following minimal, zero-dependency client demonstrates connecting to the control server, maintaining a persistent pipelined connection, loading projects, seeking, and querying playback status:

```python
import json
import socket
from typing import Any, Dict, Optional


class FilmCraftControlClient:
    """Client for FilmCraft --control <port> JSON-lines RPC server."""

    TICKS_PER_SECOND = 254016000000

    def __init__(self, host: str = "127.0.0.1", port: int = 9876, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._rfile = None
        self._wfile = None
        self._req_id = 0

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        self._rfile = self._sock.makefile("r", encoding="utf-8")
        self._wfile = self._sock.makefile("w", encoding="utf-8")

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._req_id += 1
        req = {
            "id": self._req_id,
            "method": method,
            "params": params or {}
        }
        payload = json.dumps(req) + "\n"
        self._wfile.write(payload)
        self._wfile.flush()

        line = self._rfile.readline()
        if not line:
            raise ConnectionResetError("FilmCraft closed control connection")
        resp = json.loads(line)
        if not resp.get("ok"):
            raise RuntimeError(f"FilmCraft error: {resp.get('error')}")
        return resp.get("result")

    def execute(self, command: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.call("engine.execute", {"command": command, "params": params or {}})

    # --- High-level workflows ---

    def open_project(self, path: str) -> Dict[str, Any]:
        return self.execute("file.open", {"path": path})

    def revert_project(self) -> Dict[str, Any]:
        return self.execute("file.revert", {})

    def inspect_sequence(self, sequence_id: Optional[int] = None) -> Dict[str, Any]:
        params = {"item": sequence_id} if sequence_id else {}
        return self.execute("sequence.inspect", params)

    def inspect_project(self) -> Dict[str, Any]:
        return self.execute("project.inspect", {})

    def seek_seconds(self, seconds: float) -> float:
        res = self.execute("playhead.set", {"seconds": seconds})
        return res["time"] / self.TICKS_PER_SECOND

    def seek_frame(self, frame: int) -> int:
        res = self.execute("playhead.set", {"frame": frame})
        return res["time"]

    def play(self) -> Dict[str, Any]:
        return self.call("ui.playback", {"action": "play"})

    def stop(self) -> Dict[str, Any]:
        return self.call("ui.playback", {"action": "stop"})

    def get_playback_status(self) -> Dict[str, Any]:
        status = self.call("ui.playback", {})
        status["seconds"] = status["playhead"] / self.TICKS_PER_SECOND
        return status
```

---

## 7. Conclusions & Next Steps

1. **Protocol Readiness**: The JSON-lines RPC protocol is clean, synchronous, and fully functional for live companion operation.
2. **Sidecar Implementation**: Issue #25 (`scripts/gui_companion.py`) can directly leverage `FilmCraftControlClient` with zero external dependencies.
3. **Preference Codification & Feedback Loops**:
   - `project.inspect` exposes `dirty: bool` and `revision: u64` to immediately detect manual edits made by the operator.
   - `sequence.inspect` enables accurate timeline diffing against agent-generated baselines to extract and store human editorial decisions into `.clipping_preferences.json`.
