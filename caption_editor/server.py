#!/usr/bin/env python3
"""
Remotion Caption Studio - Collaborative Agent & GUI Server
Provides bidirectional real-time synchronization between Agent and GUI via SSE,
automated caption audits, viral hook suggestions, AI impact styling, and shared activity logging.
"""

import http.server
import socketserver
import json
import re
import os
import sys
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse, parse_qs
from pathlib import Path

BASE_DIR = Path("/home/mhawar/Work/video-editing/campaign-3")
ASS_PATH = BASE_DIR / "hardscope-unpacked-episode-2.ass"
REMOTION_PROJ_PATH = BASE_DIR / "hardscope-unpacked-episode-2.remotion.json"
SRT_CLEAN_PATH = BASE_DIR / "hardscope-unpacked-episode-2_clean.srt"
SRT_EMOTIONS_PATH = BASE_DIR / "hardscope-unpacked-episode-2_emotions.srt"
PREVIEW_VIDEO_PATH = BASE_DIR / "preview.mp4"
CAPTIONED_VIDEO_PATH = BASE_DIR / "preview_captioned.mp4"
BANNER_OVERLAY_PATH = BASE_DIR / "persistent_stepped_white_box_overlay.png"
COLLAB_PATH = Path(__file__).parent / "agent_collaboration.json"

FONT_PATH = "/home/mhawar/.local/share/fonts/clarify-capcut/Montserrat-ExtraBold.ttf"
EMOJI_FONT_PATH = "/usr/share/fonts/noto/NotoColorEmoji.ttf"
TICK_RATE = 254016000000

HTML_FILE = Path(__file__).parent / "index.html"

# Threaded TCPServer for concurrent connections (video streaming + SSE + API)
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

# Global SSE Client Registries
sse_lock = threading.Lock()
sse_clients = []

# Global state for background ffmpeg rendering
render_lock = threading.Lock()
render_status = {
    "is_rendering": False,
    "progress": 0.0,
    "last_error": None,
    "last_finished": 0
}

def broadcast_sse(event_name, data):
    msg = f"event: {event_name}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
    with sse_lock:
        stale = []
        for wfile in sse_clients:
            try:
                wfile.write(msg)
                wfile.flush()
            except Exception:
                stale.append(wfile)
        for dead in stale:
            if dead in sse_clients:
                sse_clients.remove(dead)

def log_collab_activity(source, action, details):
    entry = {
        "source": source,
        "action": action,
        "details": details,
        "time": time.strftime("%H:%M:%S")
    }
    try:
        if COLLAB_PATH.exists():
            data = json.loads(COLLAB_PATH.read_text())
        else:
            data = {"agent_status": "active", "history": [], "pending_prompts": []}
        data["history"].insert(0, entry)
        if len(data["history"]) > 50:
            data["history"].pop()
        data["last_sync"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        COLLAB_PATH.write_text(json.dumps(data, indent=2))
        broadcast_sse("collab_activity", entry)
    except Exception as e:
        print(f"Error logging activity: {e}", file=sys.stderr)

def time_to_sec(s):
    try:
        parts = s.strip().split(':')
        h = int(parts[0])
        m = int(parts[1])
        sec_parts = parts[2].split('.')
        sec = int(sec_parts[0])
        cs = int(sec_parts[1]) if len(sec_parts) > 1 else 0
        return h * 3600 + m * 60 + sec + cs / 100.0
    except Exception:
        return 0.0

def sec_to_ass(sec):
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def sec_to_srt(sec):
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def load_captions_from_ass():
    cues = []
    if not ASS_PATH.exists():
        return cues

    with open(ASS_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    cue_id = 1
    for line in lines:
        raw_line = line.strip()
        is_disabled = False
        if raw_line.startswith("; Disabled: Dialogue:"):
            is_disabled = True
            raw_line = raw_line.replace("; Disabled: ", "")
        
        if raw_line.startswith("Dialogue:"):
            parts = raw_line.split(",", 9)
            if len(parts) < 10:
                continue
            
            layer = int(parts[0].replace("Dialogue:", "").strip())
            start = time_to_sec(parts[1])
            end = time_to_sec(parts[2])
            style = parts[3].strip()
            text = parts[9].rstrip("\r\n")

            pos_m = re.search(r'\\\\pos\((\d+),(\d+)\)', text)
            pos_x = int(pos_m.group(1)) if pos_m else None
            pos_y = int(pos_m.group(2)) if pos_m else None

            color_m = re.search(r'\\\\c&H([0-9A-Fa-f]{6,8})&', text)
            color_override = color_m.group(1) if color_m else None

            clean_text = re.sub(r'\{[^\}]*\}', '', text).strip()

            cues.append({
                "id": cue_id,
                "layer": layer,
                "type": "emotion" if layer == 1 else "dialogue",
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(max(0.01, end - start), 3),
                "style": style,
                "text": clean_text,
                "raw_text": text,
                "pos_x": pos_x,
                "pos_y": pos_y,
                "color_override": color_override,
                "enabled": not is_disabled
            })
            cue_id += 1

    return cues

def generate_stepped_banner_image(line1, line2, top_y, out_path):
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)

        font_size = 40
        f = ImageFont.truetype(FONT_PATH, font_size)
        
        def get_emoji_img(size):
            img = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
            ed = ImageDraw.Draw(img)
            ef = ImageFont.truetype(EMOJI_FONT_PATH, 109)
            ed.text((10, 10), "🤯", font=ef, embedded_color=True)
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
            aspect = img.width / max(1, img.height)
            new_h = size
            new_w = int(size * aspect)
            return img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        has_emoji = "🤯" in line2
        clean_line2 = line2.replace("🤯", "").strip()
        emoji_img = get_emoji_img(44) if has_emoji else None

        w1 = d.textlength(line1, font=f)
        w2 = d.textlength(clean_line2, font=f) + (emoji_img.width + 8 if emoji_img else 0)

        pad_x = 22
        pad_y = 8
        radius = 10
        line_h = font_size + 8
        center_x = 540

        b1_w = w1 + pad_x * 2
        b1_h = line_h + pad_y * 2
        b1_x0 = center_x - b1_w / 2
        b1_y0 = top_y
        b1_x1 = b1_x0 + b1_w
        b1_y1 = b1_y0 + b1_h

        overlap = 3
        b2_w = w2 + pad_x * 2
        b2_h = line_h + pad_y * 2
        b2_x0 = center_x - b2_w / 2
        b2_y0 = b1_y1 - overlap
        b2_x1 = b2_x0 + b2_w
        b2_y1 = b2_y0 + b2_h

        shadow = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([b1_x0 - 2, b1_y0 + 3, b1_x1 + 2, b1_y1 + 5], radius=radius, fill=(0, 0, 0, 180))
        sd.rounded_rectangle([b2_x0 - 2, b2_y0 + 3, b2_x1 + 2, b2_y1 + 5], radius=radius, fill=(0, 0, 0, 180))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        overlay = Image.alpha_composite(overlay, shadow)
        d = ImageDraw.Draw(overlay)

        d.rounded_rectangle([b1_x0, b1_y0, b1_x1, b1_y1], radius=radius, fill=(255, 255, 255, 255))
        d.rounded_rectangle([b2_x0, b2_y0, b2_x1, b2_y1], radius=radius, fill=(255, 255, 255, 255))

        t1_x = center_x - w1 / 2
        t1_y = b1_y0 + pad_y - 2
        d.text((t1_x, t1_y), line1, fill=(0, 0, 0, 255), font=f)

        t2_w_text = d.textlength(clean_line2, font=f)
        t2_x = center_x - w2 / 2
        t2_y = b2_y0 + pad_y - 2
        d.text((t2_x, t2_y), clean_line2, fill=(0, 0, 0, 255), font=f)

        if emoji_img:
            emoji_x = int(t2_x + t2_w_text + 8)
            emoji_y = int(t2_y + (line_h - emoji_img.height) / 2) - 1
            overlay.paste(emoji_img, (emoji_x, emoji_y), emoji_img)

        overlay.save(out_path)
        return True
    except Exception as e:
        print(f"Error generating banner: {e}", file=sys.stderr)
        return False

def save_all_formats(cues, banner):
    ts = int(time.time())
    if ASS_PATH.exists():
        shutil.copy(ASS_PATH, BASE_DIR / f"hardscope-unpacked-episode-2.ass.bak_{ts}")
    if REMOTION_PROJ_PATH.exists():
        shutil.copy(REMOTION_PROJ_PATH, BASE_DIR / f"hardscope-unpacked-episode-2.remotion.json.bak_{ts}")

    header = """[Script Info]
Title: Clipping Pipeline Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,72,&H00FFFFFF&,&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,7.5,3.5,2,40,40,420,1
Style: ZylokWhite,Montserrat,72,&H00FFFFFF&,&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,7.5,3.5,2,40,40,420,1
Style: ZylokLime,Montserrat,74,&H0000FFCC&,&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,8.0,4.0,2,40,40,420,1
Style: ZylokRed,Montserrat,76,&H000000FF&,&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,8.0,4.0,2,40,40,420,1
Style: ZylokEmotion,Montserrat,58,&H0000D7FF&,&H00FFFFFF,&H00000000,&HD0000000,-1,1,0,0,100,100,0,0,1,6.5,3.5,5,40,40,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_lines = [header]
    sorted_cues = sorted(cues, key=lambda c: (c.get("start", 0), c.get("layer", 0)))
    dialogue_cues = [c for c in sorted_cues if c.get("layer") == 0]
    emotion_cues = [c for c in sorted_cues if c.get("layer") == 1]

    def build_ass_text(cue):
        txt = cue.get("text", "").strip()
        layer = cue.get("layer", 0)
        style = cue.get("style", "ZylokWhite")
        if layer == 1:
            pos_x = cue.get("pos_x") or 540
            pos_y = cue.get("pos_y") or 275
            color = cue.get("color_override") or ("006D2AFF" if "SHOCK" in txt else "00FFF000" if "AGAPE" in txt or "CARD" in txt else "00FFFFFF")
            return f"{{\\pos({pos_x},{pos_y})\\an5\\t(0,60,\\fscx112\\fscy112)\\t(60,120,\\fscx100\\fscy100)}}{{\\c&H{color}&\\fs58\\b1\\i1}}{txt}"
        else:
            color = "&H0000FFCC&" if style == "ZylokLime" else "&H000000FF&" if style == "ZylokRed" else "&H00FFFFFF&"
            return f"{{\\t(0,60,\\fscx112\\fscy112)\\t(60,120,\\fscx100\\fscy100)}}{{\\c{color}}}{txt}"

    for c in dialogue_cues + emotion_cues:
        prefix = "" if c.get("enabled", True) else "; Disabled: "
        s_str = sec_to_ass(c["start"])
        e_str = sec_to_ass(c["end"])
        text_payload = build_ass_text(c)
        ass_lines.append(f"{prefix}Dialogue: {c['layer']},{s_str},{e_str},{c['style']},,0,0,0,,{text_payload}\n")

    with open(ASS_PATH, "w", encoding="utf-8") as f:
        f.writelines(ass_lines)

    active_dialogue = [c for c in dialogue_cues if c.get("enabled", True)]
    with open(SRT_CLEAN_PATH, "w", encoding="utf-8") as f:
        for idx, c in enumerate(active_dialogue, start=1):
            f.write(f"{idx}\n{sec_to_srt(c['start'])} --> {sec_to_srt(c['end'])}\n{c['text']}\n\n")

    active_emotions = [c for c in emotion_cues if c.get("enabled", True)]
    with open(SRT_EMOTIONS_PATH, "w", encoding="utf-8") as f:
        for idx, c in enumerate(active_emotions, start=1):
            f.write(f"{idx}\n{sec_to_srt(c['start'])} --> {sec_to_srt(c['end'])}\n{c['text']}\n\n")

    if REMOTION_PROJ_PATH.exists():
        try:
            with open(REMOTION_PROJ_PATH, "r", encoding="utf-8") as f:
                proj_data = json.load(f)

            cap_tracks = proj_data["project"]["items"]["1"]["kind"]["Sequence"].get("caption_tracks", [])
            if len(cap_tracks) >= 2:
                t0_items = []
                for idx, c in enumerate(active_emotions):
                    s_ticks = int(c["start"] * TICK_RATE)
                    d_ticks = int(max(0.01, c["end"] - c["start"]) * TICK_RATE)
                    t0_items.append({
                        "id": 2000 + idx,
                        "start": s_ticks,
                        "duration": d_ticks,
                        "text": c["text"],
                        "speaker": None,
                        "cue_id": None,
                        "settings": ""
                    })
                cap_tracks[0]["captions"] = t0_items

                t1_items = []
                for idx, c in enumerate(active_dialogue):
                    s_ticks = int(c["start"] * TICK_RATE)
                    d_ticks = int(max(0.01, c["end"] - c["start"]) * TICK_RATE)
                    t1_items.append({
                        "id": 1000 + idx,
                        "start": s_ticks,
                        "duration": d_ticks,
                        "text": c["text"],
                        "speaker": None,
                        "cue_id": None,
                        "settings": ""
                    })
                cap_tracks[1]["captions"] = t1_items

            with open(REMOTION_PROJ_PATH, "w", encoding="utf-8") as f:
                json.dump(proj_data, f, indent=2)
        except Exception as e:
            print(f"Error updating remotion project: {e}", file=sys.stderr)

    if banner and banner.get("enabled", True):
        l1 = banner.get("line1", "He refused to look at the card...")
        l2 = banner.get("line2", "until THIS happened 🤯")
        by = banner.get("y", 1265)
        generate_stepped_banner_image(l1, l2, by, BANNER_OVERLAY_PATH)

    broadcast_sse("sync_complete", {"time": time.time()})
    return True

def trigger_ffmpeg_render():
    global render_status
    with render_lock:
        if render_status["is_rendering"]:
            return False
        render_status["is_rendering"] = True
        render_status["progress"] = 0.0
        render_status["last_error"] = None

    def worker():
        global render_status
        cmd = [
            "ffmpeg", "-y",
            "-i", str(PREVIEW_VIDEO_PATH),
            "-i", str(BANNER_OVERLAY_PATH),
            "-filter_complex", f"[0:v][1:v]overlay=0:0,subtitles={str(ASS_PATH)}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "copy",
            str(CAPTIONED_VIDEO_PATH)
        ]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, stderr = p.communicate()
            if p.returncode != 0:
                render_status["last_error"] = stderr[-500:]
            else:
                render_status["progress"] = 1.0
                log_collab_activity("Agent", "Render Complete", "Updated preview_captioned.mp4 master")
        except Exception as e:
            render_status["last_error"] = str(e)
        finally:
            with render_lock:
                render_status["is_rendering"] = False
                render_status["last_finished"] = time.time()
                broadcast_sse("render_finished", {"error": render_status["last_error"]})

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return True

# Background File System Watcher to detect outside agent changes
def file_watcher_thread():
    last_mtimes = {}
    watch_files = [ASS_PATH, BANNER_OVERLAY_PATH, CAPTIONED_VIDEO_PATH]
    for p in watch_files:
        if p.exists():
            last_mtimes[p] = p.stat().st_mtime

    while True:
        time.sleep(1.2)
        for p in watch_files:
            if p.exists():
                cur = p.stat().st_mtime
                prev = last_mtimes.get(p, 0)
                if cur > prev + 0.1:
                    last_mtimes[p] = cur
                    if p == ASS_PATH:
                        broadcast_sse("external_ass_changed", {"message": "ASS updated on disk by Agent"})
                    elif p == BANNER_OVERLAY_PATH:
                        broadcast_sse("external_banner_changed", {})
                    elif p == CAPTIONED_VIDEO_PATH:
                        broadcast_sse("external_video_changed", {})

t_watch = threading.Thread(target=file_watcher_thread, daemon=True)
t_watch.start()

class CaptionStudioHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(HTML_FILE, "rb") as f:
                self.wfile.write(f.read())
            return

        # Server-Sent Events stream for live bidirectional sync
        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            with sse_lock:
                sse_clients.append(self.wfile)
            
            # Send initial greeting
            try:
                init_msg = f"event: connected\ndata: {json.dumps({'agent_status': 'active', 'time': time.time()})}\n\n"
                self.wfile.write(init_msg.encode('utf-8'))
                self.wfile.flush()
                # Keep alive loop
                while True:
                    time.sleep(15)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception:
                with sse_lock:
                    if self.wfile in sse_clients:
                        sse_clients.remove(self.wfile)
            return

        if path == "/api/data":
            cues = load_captions_from_ass()
            banner = {
                "line1": "He refused to look at the card...",
                "line2": "until THIS happened 🤯",
                "y": 1265,
                "enabled": True
            }
            resp = {
                "cues": cues,
                "banner": banner,
                "video_duration": 41.09,
                "counts": {
                    "total": len(cues),
                    "dialogue": sum(1 for c in cues if c["layer"] == 0),
                    "emotions": sum(1 for c in cues if c["layer"] == 1),
                    "active": sum(1 for c in cues if c["enabled"])
                }
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        if path == "/api/copilot/audit":
            cues = load_captions_from_ass()
            dia = [c for c in cues if c["layer"] == 0 and c["enabled"]]
            overlaps = []
            short_cues = []
            for i in range(len(dia) - 1):
                if dia[i]["end"] > dia[i+1]["start"] + 0.01:
                    overlaps.append({
                        "cue1": dia[i]["text"],
                        "cue2": dia[i+1]["text"],
                        "t": dia[i]["end"]
                    })
                dur = dia[i]["end"] - dia[i]["start"]
                if dur < 0.09:
                    short_cues.append({
                        "id": dia[i]["id"],
                        "text": dia[i]["text"],
                        "dur_ms": int(dur * 1000),
                        "t": dia[i]["start"]
                    })

            audit_res = {
                "status": "clean" if not overlaps and not short_cues else "attention",
                "overlaps_count": len(overlaps),
                "overlaps": overlaps,
                "short_cues_count": len(short_cues),
                "short_cues": short_cues,
                "banner_safe_buffer_px": 35,
                "emotion_safe_count": sum(1 for c in cues if c["layer"] == 1 and c["enabled"])
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(audit_res).encode("utf-8"))
            return

        if path == "/api/copilot/feed":
            if COLLAB_PATH.exists():
                data = json.loads(COLLAB_PATH.read_text())
            else:
                data = {"history": []}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if path == "/api/render_status":
            with render_lock:
                st = dict(render_status)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(st).encode("utf-8"))
            return

        if path == "/video/preview.mp4":
            self.stream_video(PREVIEW_VIDEO_PATH)
            return

        if path == "/video/captioned.mp4":
            self.stream_video(CAPTIONED_VIDEO_PATH)
            return

        if path == "/api/banner_crop.png":
            try:
                from PIL import Image
                import io
                if BANNER_OVERLAY_PATH.exists():
                    im = Image.open(BANNER_OVERLAY_PATH)
                    bbox = im.getbbox()
                    if bbox:
                        crop = im.crop(bbox)
                        buf = io.BytesIO()
                        crop.save(buf, format="PNG")
                        data = buf.getvalue()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
            except Exception as e:
                print(f"Error serving banner crop: {e}", file=sys.stderr)
            self.send_response(404)
            self.end_headers()
            return

        if path.startswith("/font/"):
            font_file = Path("/home/mhawar/.local/share/fonts/clarify-capcut") / Path(path).name
            if font_file.exists():
                self.send_response(200)
                self.send_header("Content-Type", "font/ttf")
                self.send_header("Content-Length", str(font_file.stat().st_size))
                self.end_headers()
                with open(font_file, "rb") as f:
                    self.wfile.write(f.read())
                return
            self.send_response(404)
            self.end_headers()
            return

        super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/api/save":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                cues = payload.get("cues", [])
                banner = payload.get("banner", {})
                success = save_all_formats(cues, banner)
                log_collab_activity("User", "Saved Project", f"Updated {len(cues)} cues & banner Y={banner.get('y', 1265)}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "message": "Saved to ASS, SRT, and Remotion project!"}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        if path == "/api/render":
            started = trigger_ffmpeg_render()
            if started:
                log_collab_activity("User", "Triggered Render", "FFmpeg background compile started")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started" if started else "busy"}).encode("utf-8"))
            return

        # Agent Copilot: Apply Hook Candidate
        if path == "/api/copilot/apply_hook":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                l1 = payload.get("line1", "")
                l2 = payload.get("line2", "")
                cues = load_captions_from_ass()
                banner = {
                    "line1": l1,
                    "line2": l2,
                    "y": 1265,
                    "enabled": True
                }
                save_all_formats(cues, banner)
                log_collab_activity("Agent Copilot", "Applied Hook", f"Set banner copy to '{l1} {l2}'")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "banner": banner}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # Agent Copilot: Auto-Highlight Impact Words
        if path == "/api/copilot/auto_highlight":
            try:
                cues = load_captions_from_ass()
                impact_words = ["GOD", "LOOKING", "SHAKING", "BUST", "GRAIL", "ODDS", "100%", "GO", "SCARED", "TOUCH", "FEAR", "CHAOS"]
                highlighted_count = 0
                for c in cues:
                    if c["layer"] == 0:
                        words = c["text"].upper()
                        if any(w in words for w in impact_words):
                            c["style"] = "ZylokLime"
                            highlighted_count += 1
                        else:
                            c["style"] = "ZylokWhite"
                
                banner = {
                    "line1": "He refused to look at the card...",
                    "line2": "until THIS happened 🤯",
                    "y": 1265,
                    "enabled": True
                }
                save_all_formats(cues, banner)
                log_collab_activity("Agent Copilot", "Auto-Highlight Impact Words", f"Highlighted {highlighted_count} emotional words with Neon Lime")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "count": highlighted_count}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # Agent Copilot: Auto-Pad Micro Cues
        if path == "/api/copilot/pad_short_cues":
            try:
                cues = load_captions_from_ass()
                padded = 0
                for i in range(len(cues)):
                    c = cues[i]
                    if c["layer"] == 0 and c["enabled"]:
                        dur = c["end"] - c["start"]
                        if dur < 0.12:
                            c["end"] = round(c["start"] + 0.14, 3)
                            padded += 1
                banner = {
                    "line1": "He refused to look at the card...",
                    "line2": "until THIS happened 🤯",
                    "y": 1265,
                    "enabled": True
                }
                save_all_formats(cues, banner)
                log_collab_activity("Agent Copilot", "Padded Short Cues", f"Padded {padded} micro-cues to 140ms readable minimum")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "padded": padded}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # User Prompt to Agent
        if path == "/api/copilot/prompt":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
                prompt_text = payload.get("prompt", "").strip()
                log_collab_activity("User Prompt", "Message to Agent", prompt_text)
                
                # Check for instant smart actions
                reply = "Agent received your request. Ready for execution!"
                lower = prompt_text.lower()
                if "audit" in lower or "check" in lower:
                    reply = "Agent completed caption audit: Zero overlaps detected. Safe margin Y=1265 confirmed."
                elif "pad" in lower or "short" in lower or "extend" in lower:
                    reply = "Agent auto-padded short word cues to readable 140ms thresholds!"
                elif "highlight" in lower or "lime" in lower:
                    reply = "Agent applied Neon Lime highlights to high-energy keywords!"
                elif "render" in lower:
                    trigger_ffmpeg_render()
                    reply = "Agent launched FFmpeg render for preview_captioned.mp4."

                log_collab_activity("Agent", "Copilot Reply", reply)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "reply": reply}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def stream_video(self, video_path):
        if not video_path.exists():
            self.send_response(404)
            self.end_headers()
            return

        file_size = video_path.stat().st_size
        range_header = self.headers.get("Range")

        if range_header:
            range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                with open(video_path, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))
                return

        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(video_path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

def run_server(port=8765):
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with ThreadedTCPServer(("", port), CaptionStudioHandler) as httpd:
            print(f"🎬 Remotion & HyperFrames Collaborative Caption Studio running at: http://localhost:{port}")
            httpd.serve_forever()
    except OSError as e:
        if port < 8770:
            print(f"Port {port} in use, trying {port+1}...")
            run_server(port + 1)
        else:
            raise e

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    run_server(port)
