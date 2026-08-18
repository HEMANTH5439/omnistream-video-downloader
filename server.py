import http.server
import socketserver
import json
import urllib.parse
import subprocess
import os
import sys
import threading
import time
import re
import uuid
from pathlib import Path

PORT = 8888
BASE_DIR = Path(__file__).parent.resolve()
PUBLIC_DIR = BASE_DIR / "public"
DOWNLOADS_DIR = BASE_DIR.parent / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = BASE_DIR / "history.json"

# Python & yt-dlp binary locations
PYTHON_BIN = "/Users/chillsyeah/.gemini/antigravity/scratch/py312/python/bin/python3"
YTDLP_BIN = "/Users/chillsyeah/.gemini/antigravity/scratch/yt-dlp-latest"

if not os.path.exists(PYTHON_BIN):
    PYTHON_BIN = sys.executable

if not os.path.exists(YTDLP_BIN):
    YTDLP_BIN = "yt-dlp"

# In-memory download tasks state
# task_id -> { "id", "url", "title", "thumbnail", "format", "status", "percent", "speed", "eta", "size", "filepath", "error" }
active_tasks = {}
process_store = {}
active_lock = threading.Lock()

def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(entry):
    history = load_history()
    # Prepend new entry, keep last 50
    history = [e for e in history if e.get("id") != entry.get("id")]
    history.insert(0, entry)
    history = history[:50]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def format_bytes(b):
    if not b or b <= 0:
        return "Unknown size"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"

def format_duration(seconds):
    if not seconds:
        return "Unknown"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def get_video_info(url):
    is_playlist_url = "list=" in url or "playlist" in url.lower()
    base_flags = ["--flat-playlist", "-J", "--no-warnings"] if is_playlist_url else ["-J", "--no-warnings"]

    attempts = [
        [PYTHON_BIN, YTDLP_BIN] + base_flags + [url],
        [PYTHON_BIN, YTDLP_BIN, "--extractor-args", "youtube:player_client=mweb,android,web_creator"] + base_flags + [url],
        [PYTHON_BIN, YTDLP_BIN, "--extractor-args", "youtube:player_client=ios,android"] + base_flags + [url]
    ]

    res = None
    last_err = ""
    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip().startswith("{"):
                res = r
                break
            else:
                err_msg = r.stderr.strip() or r.stdout.strip()
                if "Operation not permitted" not in err_msg and "could not find" not in err_msg:
                    last_err = err_msg
        except Exception as e:
            last_err = str(e)

    if not res or res.returncode != 0:
        return { "error": last_err or "Unable to extract video details. YouTube bot protection may require cookies or signed-in browser." }

    try:
        data = json.loads(res.stdout)

        # Check if playlist
        if data.get('_type') == 'playlist' or ('entries' in data and isinstance(data.get('entries'), list)):
            entries = [e for e in data.get('entries', []) if e]
            parsed_entries = []
            for entry in entries[:50]:
                parsed_entries.append({
                    "id": entry.get("id"),
                    "title": entry.get("title", "Video"),
                    "url": entry.get("url") or entry.get("webpage_url") or (f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get("id") else url),
                    "duration": format_duration(entry.get("duration")),
                    "thumbnail": entry.get("thumbnail") or (entry.get("thumbnails")[-1]["url"] if entry.get("thumbnails") else "")
                })

            return {
                "is_playlist": True,
                "title": data.get("title", "Playlist"),
                "uploader": data.get("uploader") or data.get("channel") or "Unknown Uploader",
                "entry_count": len(entries),
                "entries": parsed_entries,
                "extractor": data.get("extractor_key", "Playlist"),
                "presets": [
                    { "format_id": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "resolution": "Best Quality", "label": "Best Available Quality for All Videos (Auto MP4)", "ext": "mp4" },
                    { "format_id": "bestaudio/best", "resolution": "Audio MP3", "label": "Extract Audio MP3 for All Videos", "ext": "mp3", "is_audio": True }
                ]
            }

        title = data.get("title", "Video")
        thumbnail = data.get("thumbnail") or (data.get("thumbnails")[-1]["url"] if data.get("thumbnails") else "")
        duration = format_duration(data.get("duration"))
        uploader = data.get("uploader") or data.get("channel") or data.get("extractor_key") or "Unknown Uploader"
        view_count = data.get("view_count")
        view_str = f"{view_count:,} views" if view_count else None
        extractor = data.get("extractor_key", "Web")

        # Process formats
        raw_formats = data.get("formats", [])
        formats_map = {}
        audio_formats = []

        # Find best combined formats & video formats
        for f in raw_formats:
            format_id = f.get("format_id")
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            height = f.get("height")
            ext = f.get("ext", "mp4")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0
            fps = f.get("fps")
            note = f.get("format_note", "")

            # Video formats
            if vcodec != "none" and height:
                res_key = f"{height}p"
                # Store highest quality format for each resolution height
                if res_key not in formats_map or filesize > formats_map[res_key].get("filesize", 0):
                    fps_str = f" ({fps}fps)" if fps and fps > 30 else ""
                    formats_map[res_key] = {
                        "format_id": format_id if acodec != "none" else f"{format_id}+bestaudio/best",
                        "resolution": res_key,
                        "label": f"{res_key}{fps_str} - {ext.upper()}",
                        "ext": ext,
                        "filesize": filesize,
                        "filesize_formatted": format_bytes(filesize),
                        "height": height
                    }
            
            # Audio-only format
            if vcodec == "none" and acodec != "none":
                abr = f.get("abr") or f.get("tbr") or 128
                audio_formats.append({
                    "format_id": format_id,
                    "resolution": "Audio",
                    "label": f"Audio ({int(abr)} kbps) - {ext.upper()}",
                    "ext": ext,
                    "filesize": filesize,
                    "filesize_formatted": format_bytes(filesize),
                    "abr": abr
                })

        # Sort video formats descending by resolution height
        sorted_video_formats = sorted(formats_map.values(), key=lambda x: x["height"], reverse=True)

        # Standard preset formats
        presets = [
            { "format_id": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "resolution": "Best Available (Max Quality)", "label": "Best Available Quality (Auto MP4)", "ext": "mp4", "filesize_formatted": "Auto" },
            { "format_id": "bestaudio/best", "resolution": "Audio MP3 (320kbps)", "label": "Audio Only (MP3 / High Quality)", "ext": "mp3", "is_audio": True, "filesize_formatted": "Audio" }
        ]

        return {
            "title": title,
            "thumbnail": thumbnail,
            "duration": duration,
            "uploader": uploader,
            "views": view_str,
            "extractor": extractor,
            "video_formats": sorted_video_formats,
            "audio_formats": sorted(audio_formats, key=lambda x: x.get("abr", 0), reverse=True)[:3],
            "presets": presets
        }

    except Exception as e:
        return { "error": str(e) }

def start_download_thread(task_id, url, format_id, is_audio, output_dir, is_playlist=False):
    def run():
        with active_lock:
            active_tasks[task_id]["status"] = "downloading"

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception:
            pass

        if is_playlist:
            out_template = os.path.join(output_dir, "%(playlist_title,playlist)s", "%(playlist_index,item_number)s - %(title)s.%(ext)s")
        else:
            out_template = os.path.join(output_dir, "%(title)s.%(ext)s")

        cmd = [
            PYTHON_BIN, YTDLP_BIN, "--newline",
            "--concurrent-fragments", "10",
            "--http-chunk-size", "10M",
            "--buffer-size", "64K",
            "-o", out_template
        ]

        if is_audio:
            cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0"])
        elif format_id:
            cmd.extend(["-f", format_id])

        cmd.append(url)

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            with active_lock:
                process_store[task_id] = process
            
            # Progress regex: [download]  45.2% of  100.00MiB at   5.20MiB/s ETA 00:10
            progress_regex = re.compile(r'\[download\]\s+(\d+\.\d+)%\s+of\s+([~\d\.\w]+)\s+at\s+([\d\.\w/]+)\s+ETA\s+([\d:]+)')
            dest_regex = re.compile(r'\[download\] Destination:\s+(.+)')
            merge_regex = re.compile(r'\[Merger\] Merging formats into "(.+)"')

            filepath = None

            for line in process.stdout:
                line = line.strip()
                dest_match = dest_regex.search(line)
                if dest_match:
                    filepath = dest_match.group(1).strip()

                merge_match = merge_regex.search(line)
                if merge_match:
                    filepath = merge_match.group(1).strip().replace('"', '')

                prog_match = progress_regex.search(line)
                if prog_match:
                    pct = float(prog_match.group(1))
                    size = prog_match.group(2)
                    speed = prog_match.group(3)
                    eta = prog_match.group(4)
                    with active_lock:
                        active_tasks[task_id].update({
                            "percent": pct,
                            "size": size,
                            "speed": speed,
                            "eta": eta,
                            "status": "downloading"
                        })

            process.wait()

            if process.returncode == 0:
                with active_lock:
                    active_tasks[task_id].update({
                        "percent": 100.0,
                        "status": "completed",
                        "filepath": filepath or os.path.join(output_dir, f"{active_tasks[task_id]['title']}.mp4")
                    })
                    save_history(active_tasks[task_id])
            else:
                # If command failed with firefox cookies, try plain without cookies
                cmd_plain = [c for c in cmd if c not in ["--cookies-from-browser", "firefox"]]
                p2 = subprocess.Popen(cmd_plain, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in p2.stdout:
                    prog_match = progress_regex.search(line)
                    if prog_match:
                        with active_lock:
                            active_tasks[task_id].update({
                                "percent": float(prog_match.group(1)),
                                "size": prog_match.group(2),
                                "speed": prog_match.group(3),
                                "eta": prog_match.group(4),
                                "status": "downloading"
                            })
                p2.wait()
                if p2.returncode == 0:
                    with active_lock:
                        active_tasks[task_id].update({
                            "percent": 100.0,
                            "status": "completed",
                            "filepath": filepath or os.path.join(output_dir, f"{active_tasks[task_id]['title']}.mp4")
                        })
                        save_history(active_tasks[task_id])
                else:
                    with active_lock:
                        active_tasks[task_id].update({
                            "status": "failed",
                            "error": "Download failed. Please check URL or connection."
                        })
        except Exception as e:
            with active_lock:
                active_tasks[task_id].update({
                    "status": "failed",
                    "error": str(e)
                })

    t = threading.Thread(target=run, daemon=True)
    t.start()

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self.path = "/index.html"

        if path == "/api/info":
            url = query.get("url", [""])[0]
            if not url:
                self.send_json({"error": "No URL provided"}, 400)
                return
            info = get_video_info(url)
            self.send_json(info)
            return

        elif path == "/api/tasks":
            with active_lock:
                self.send_json(list(active_tasks.values()))
            return

        elif path == "/api/history":
            self.send_json(load_history())
            return

        # Serve static files from PUBLIC_DIR
        rel_path = path.lstrip("/")
        if not rel_path or rel_path == "index.html":
            target_file = PUBLIC_DIR / "index.html"
        else:
            target_file = PUBLIC_DIR / rel_path

        if target_file.exists() and target_file.is_file():
            content_type = "text/html"
            if target_file.suffix == ".css":
                content_type = "text/css"
            elif target_file.suffix == ".js":
                content_type = "application/javascript"
            elif target_file.suffix == ".json":
                content_type = "application/json"
            elif target_file.suffix in [".png", ".jpg", ".jpeg", ".svg", ".ico"]:
                content_type = f"image/{target_file.suffix.lstrip('.')}"

            with open(target_file, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        else:
            self.send_json({"error": "File Not Found"}, 404)
            return

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        if path == "/api/download":
            url = data.get("url")
            title = data.get("title", "Video")
            thumbnail = data.get("thumbnail", "")
            format_id = data.get("format_id")
            is_audio = data.get("is_audio", False)
            output_dir = data.get("output_dir", str(DOWNLOADS_DIR))

            if not url:
                self.send_json({"error": "URL is required"}, 400)
                return

            task_id = str(uuid.uuid4())[:8]
            task_info = {
                "id": task_id,
                "url": url,
                "title": title,
                "thumbnail": thumbnail,
                "format": data.get("format_label", "Standard"),
                "status": "queued",
                "percent": 0.0,
                "speed": "0 KB/s",
                "eta": "--:--",
                "size": "Calculating...",
                "filepath": "",
                "timestamp": time.time()
            }

            with active_lock:
                active_tasks[task_id] = task_info

            is_playlist = data.get("is_playlist", False)
            start_download_thread(task_id, url, format_id, is_audio, output_dir, is_playlist=is_playlist)
            self.send_json({"task_id": task_id, "status": "queued"})
            return

        elif path == "/api/cancel-task":
            task_id = data.get("task_id")
            if task_id and task_id in process_store:
                proc = process_store[task_id]
                try:
                    proc.terminate()
                    time.sleep(0.2)
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                with active_lock:
                    if task_id in active_tasks:
                        active_tasks[task_id]["status"] = "canceled"
                self.send_json({"success": True})
            else:
                self.send_json({"error": "Task not found"}, 404)
            return

        elif path == "/api/select-folder":
            try:
                script = 'tell application "System Events" to activate\nset chosenFolder to choose folder with prompt "Select OmniStream Download Folder"\nPOSIX path of chosenFolder'
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
                if res.returncode == 0 and res.stdout.strip():
                    folder_path = res.stdout.strip().rstrip('/')
                    self.send_json({"folder_path": folder_path})
                else:
                    self.send_json({"canceled": True})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        elif path == "/api/open-file":
            filepath = data.get("filepath")
            if filepath and os.path.exists(filepath):
                subprocess.run(["open", filepath])
                self.send_json({"success": True})
            else:
                self.send_json({"error": "File not found"}, 44)
            return

        elif path == "/api/open-folder":
            filepath = data.get("filepath") or str(DOWNLOADS_DIR)
            if os.path.exists(filepath):
                if os.path.isfile(filepath):
                    subprocess.run(["open", "-R", filepath])
                else:
                    subprocess.run(["open", filepath])
                self.send_json({"success": True})
            else:
                subprocess.run(["open", str(DOWNLOADS_DIR)])
                self.send_json({"success": True})
            return

        elif path == "/api/clear-history":
            with open(HISTORY_FILE, "w") as f:
                json.dump([], f)
            self.send_json({"success": True})
            return

        self.send_json({"error": "Not Found"}, 404)

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    os.chdir(str(PUBLIC_DIR))
    print(f"OmniStream Server starting on http://localhost:{PORT}")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
        httpd.serve_forever()
