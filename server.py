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
import signal
from pathlib import Path

try:
    import certifi
    ca_bundle = certifi.where()
    os.environ['SSL_CERT_FILE'] = ca_bundle
    os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle
    os.environ['CURL_CA_BUNDLE'] = ca_bundle
except ImportError:
    pass

import webbrowser

def get_resource_path(*paths):
    try:
        base = Path(sys._MEIPASS)
    except AttributeError:
        base = Path(__file__).parent.resolve()
    return base.joinpath(*paths)

PORT = 8888
BASE_DIR = get_resource_path()
PUBLIC_DIR = get_resource_path("public")
DOWNLOADS_DIR = Path.home() / "Downloads" / "OmniStream"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = Path.home() / "Library" / "Application Support" / "OmniStream" / "history.json"
HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

# Binaries
YTDLP_BIN = str(get_resource_path("bin", "yt-dlp"))
FFMPEG_BIN = str(get_resource_path("bin", "ffmpeg"))
FFMPEG_DIR = os.path.dirname(FFMPEG_BIN)

# In-memory download tasks state
# task_id -> { "id", "url", "title", "thumbnail", "format", "status", "percent", "speed", "eta", "size", "filepath", "error" }
active_tasks = {}
process_store = {}
active_lock = threading.Lock()
download_semaphore = threading.Semaphore(3)

def parse_bytes(size_str):
    if not size_str or size_str == '~': return 0
    size_str = size_str.upper().replace('IB', 'B').replace('I', '').strip()
    match = re.match(r"([\d\.]+)\s*([A-Z]+)?", size_str)
    if not match: return 0
    val = float(match.group(1))
    unit = match.group(2)
    multiplier = 1
    if unit == 'KB' or unit == 'K': multiplier = 1024
    elif unit == 'MB' or unit == 'M': multiplier = 1024**2
    elif unit == 'GB' or unit == 'G': multiplier = 1024**3
    elif unit == 'TB' or unit == 'T': multiplier = 1024**4
    return int(val * multiplier)

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
    is_playlist_url = any(k in url.lower() for k in ["list=", "playlist", "/space", "/lists", "/channel", "/fav"])
    base_flags = ["--flat-playlist", "-J", "--no-warnings", "--no-check-certificate"] if is_playlist_url else ["-J", "--no-warnings", "--no-check-certificate"]

    attempts = [
        [YTDLP_BIN, "--impersonate", "safari"] + base_flags + [url],
        [YTDLP_BIN] + base_flags + [url],
        [YTDLP_BIN, "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15"] + base_flags + [url]
    ]

    res = None
    last_err = ""
    env = os.environ.copy()
    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
            if r.returncode == 0 and r.stdout.strip().startswith("{"):
                res = r
                break
            else:
                err_msg = r.stderr.strip() or r.stdout.strip()
                if "Operation not permitted" not in err_msg and "could not find" not in err_msg:
                    last_err = err_msg
        except Exception as e:
            last_err = str(e)

    target_embed = None
    if not res or res.returncode != 0:
        # Deep HTML Link Scraper fallback for movie index pages & embed wrappers
        if "Unsupported URL" in last_err or "is not a valid URL" in last_err or "403" in last_err or "Forbidden" in last_err or not res:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    html = resp.read().decode('utf-8', errors='ignore')
                    found_urls = re.findall(r'https?://[^\s\"\'<>]+', html)
                    video_embeds = [u for u in found_urls if any(k in u.lower() for k in ['embed', 'player', 'm3u8', 'vidsrc', 'megacloud', 'filemoon', 'streamtape']) and u != url]
                    if video_embeds:
                        target_embed = video_embeds[0]
                        sub_cmd = [YTDLP_BIN, "-J", "--no-warnings", target_embed]
                        sub_res = subprocess.run(sub_cmd, capture_output=True, text=True, timeout=30)
                        if sub_res.returncode == 0 and sub_res.stdout.strip().startswith("{"):
                            res = sub_res
            except Exception:
                pass

        # Headless Chrome DOM rendering fallback if basic HTML scrape finds nothing
        if (not res or res.returncode != 0) and ("Unsupported URL" in last_err or "403" in last_err or "Forbidden" in last_err or not res):
            chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if os.path.exists(chrome_bin):
                try:
                    c_cmd = [chrome_bin, "--headless", "--disable-gpu", "--dump-dom", url]
                    c_res = subprocess.run(c_cmd, capture_output=True, text=True, timeout=25)
                    if c_res.returncode == 0 and c_res.stdout:
                        c_urls = re.findall(r'https?://[^\s\"\'<>]+', c_res.stdout)
                        c_embeds = [u for u in c_urls if any(k in u.lower() for k in ['embed', 'player', 'm3u8', 'vidsrc', 'megacloud', 'filemoon', 'streamtape']) and u != url]
                        if c_embeds:
                            target_embed = c_embeds[0]
                            sub_cmd = [YTDLP_BIN, "-J", "--no-warnings", target_embed]
                            sub_res = subprocess.run(sub_cmd, capture_output=True, text=True, timeout=30)
                            if sub_res.returncode == 0 and sub_res.stdout.strip().startswith("{"):
                                res = sub_res
                except Exception:
                    pass

    if not res or res.returncode != 0:
        # Check if user pasted a direct .m3u8, .ts, dash CDN, stream segment, or protected site video URL
        url_lower = url.lower()
        if any(k in url_lower for k in [".m3u8", ".ts", "seg-", "dash-", "cdn."]):
            return {
                "title": "Direct Media Stream",
                "uploader": "Direct Stream Link",
                "duration": "Dynamic",
                "thumbnail": "",
                "video_formats": [{"format_id": "best", "resolution": "Full HD / Best Quality", "ext": "mp4", "filesize_str": "Direct Stream"}],
                "audio_formats": [],
                "presets": [{"label": "Direct Video Stream (.mp4)", "format_id": "best", "is_audio": False}]
            }

        if "403" in last_err or "Forbidden" in last_err or "not allowed by policy" in last_err:
            return { "error": "This page/playlist enforces anti-bot protection (HTTP 403 Forbidden). For protected playlists or direct video streams, please paste individual video links or stream URLs (.m3u8/.ts) directly into OmniStream!" }

        if "Unsupported URL" in last_err:
            return { "error": "Unsupported video link. Please paste a direct stream URL (.m3u8 / .ts)." }
        return { "error": last_err or "Unable to extract video details. Please verify the link." }

    try:
        data = json.loads(res.stdout)

        if data.get('_type') == 'playlist' or ('entries' in data and isinstance(data.get('entries'), list)):
            entries = [e for e in data.get('entries', []) if e]
            parsed_entries = []
            for entry in entries:
                parsed_entries.append({
                    "id": entry.get("id"),
                    "title": entry.get("title", "Video"),
                    "url": entry.get("url") or entry.get("webpage_url") or url,
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
                    { "format_id": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best", "resolution": "1080p (Full HD)", "label": "1080p (Full HD) - If available", "ext": "mp4" },
                    { "format_id": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best", "resolution": "720p (HD)", "label": "720p (HD) - If available", "ext": "mp4" },
                    { "format_id": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best", "resolution": "480p (SD)", "label": "480p (SD) - If available", "ext": "mp4" },
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
                    final_ext = "MKV" if acodec == "none" else ext.upper()
                    formats_map[res_key] = {
                        "format_id": format_id if acodec != "none" else f"{format_id}+bestaudio/best",
                        "resolution": res_key,
                        "label": f"{res_key}{fps_str} - {final_ext}",
                        "ext": final_ext.lower(),
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
            "presets": presets,
            "resolved_url": target_embed or url
        }

    except Exception as e:
        return { "error": str(e) }

def start_download_thread(task_id, url, format_id, is_audio, output_dir, is_playlist=False, force_mp4=False, embed_subs=False):
    def run():
        with active_lock:
            active_tasks[task_id]["status"] = "downloading"
            active_tasks[task_id]["start_time"] = time.time()
            active_tasks[task_id]["speed_history"] = []

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception:
            pass

        if is_playlist:
            out_template = os.path.join(output_dir, "%(playlist_title,playlist)s", "%(playlist_index,item_number)s - %(title)s.%(ext)s")
        else:
            out_template = os.path.join(output_dir, "%(title)s.%(ext)s")

        # Convert segment .ts URL to master playlist URL if user pasted segment URL
        target_url = url
        if ".ts" in url.lower() or "seg-" in url.lower():
            target_url = re.sub(r'seg-\d+-v1-a1\.ts', 'master.m3u8', url)
            target_url = re.sub(r'seg-\d+-\w+\.ts', 'master.m3u8', target_url)

        cmd = [
            YTDLP_BIN, "--newline",
            "--no-check-certificate",
            "--ffmpeg-location", FFMPEG_DIR,
            "--impersonate", "safari",
            "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
            "--concurrent-fragments", "10",
            "--http-chunk-size", "10M",
            "--buffer-size", "64K",
            "-o", out_template
        ]

        if is_audio:
            cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0", "--embed-metadata", "--embed-thumbnail"])
        elif format_id:
            cmd.extend(["-f", format_id])
            if "mp4" in format_id:
                cmd.extend(["--merge-output-format", "mp4"])

        if embed_subs and not is_audio:
            cmd.extend(["--write-auto-subs", "--embed-subs"])

        if force_mp4 and not is_audio:
            cmd.extend(["--recode-video", "mp4"])

        if "bilibili.com" in target_url or "b23.tv" in target_url:
            aria_path = os.path.abspath("bin/aria2c")
            if os.path.exists(aria_path):
                cmd.extend([
                    "--downloader", aria_path,
                    "--downloader-args", "aria2c:-x 16 -s 16 -k 1M"
                ])

        cmd.append(target_url)

        env = os.environ.copy()
        
        with active_lock:
            active_tasks[task_id]["status"] = "queued"
            
        with download_semaphore:
            with active_lock:
                if active_tasks[task_id]["status"] != "canceled":
                    active_tasks[task_id]["status"] = "downloading"
                    
            if active_tasks[task_id]["status"] == "canceled":
                return
                
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env, start_new_session=True)
                with active_lock:
                    process_store[task_id] = process
                
                # Progress regex: [download]  45.2% of  100.00MiB at   5.20MiB/s ETA 00:10
                progress_regex = re.compile(r'\[download\]\s+(\d+\.\d+)%\s+of\s+([~\d\.\w]+)\s+at\s+([\d\.\w/]+)\s+ETA\s+([\d:]+)')
                aria2_regex = re.compile(r'\[#.*? \S+/([~\d\.\w]+)\((\d+)%\).*?DL:([~\d\.\w]+).*?ETA:([^\]]+)\]')
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
                    aria2_match = aria2_regex.search(line)
                    
                    pct, raw_size, raw_speed, raw_eta = None, None, None, None

                    if prog_match:
                        pct = float(prog_match.group(1))
                        raw_size = prog_match.group(2)
                        raw_speed = prog_match.group(3)
                    elif aria2_match:
                        raw_size = aria2_match.group(1)
                        pct = float(aria2_match.group(2))
                        raw_speed = aria2_match.group(3) + "/s"

                    if pct is not None:
                        total_bytes = parse_bytes(raw_size)
                        speed_bytes = parse_bytes(raw_speed)
                        downloaded_bytes = int(total_bytes * (pct / 100.0))

                        with active_lock:
                            # Smoothing Speed (last 10 samples)
                            history = active_tasks[task_id]["speed_history"]
                            history.append(speed_bytes)
                            if len(history) > 10:
                                history.pop(0)
                            
                            avg_speed = sum(history) / len(history) if history else speed_bytes
                            
                            smoothed_eta = 0
                            if avg_speed > 0:
                                smoothed_eta = int((total_bytes - downloaded_bytes) / avg_speed)

                            time_elapsed = int(time.time() - active_tasks[task_id].get("start_time", time.time()))

                            active_tasks[task_id].update({
                                "percent": pct,
                                "total_bytes": total_bytes,
                                "downloaded_bytes": downloaded_bytes,
                                "speed_bytes": avg_speed,
                                "eta_seconds": smoothed_eta,
                                "time_elapsed": time_elapsed,
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
                    # If command failed with impersonate, try plain without impersonate
                    cmd_plain = [c for c in cmd if c not in ["--impersonate", "safari"]]
                    p2 = subprocess.Popen(cmd_plain, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env, start_new_session=True)
                    with active_lock:
                        process_store[task_id] = p2
                    for line in p2.stdout:
                        prog_match = progress_regex.search(line)
                        aria2_match = aria2_regex.search(line)
                        
                        pct, raw_size, raw_speed, raw_eta = None, None, None, None
    
                        if prog_match:
                            pct = float(prog_match.group(1))
                            raw_size = prog_match.group(2)
                            raw_speed = prog_match.group(3)
                        elif aria2_match:
                            raw_size = aria2_match.group(1)
                            pct = float(aria2_match.group(2))
                            raw_speed = aria2_match.group(3) + "/s"
    
                        if pct is not None:
                            total_bytes = parse_bytes(raw_size)
                            speed_bytes = parse_bytes(raw_speed)
                            downloaded_bytes = int(total_bytes * (pct / 100.0))

                            with active_lock:
                                history = active_tasks[task_id]["speed_history"]
                                history.append(speed_bytes)
                                if len(history) > 10:
                                    history.pop(0)
                                
                                avg_speed = sum(history) / len(history) if history else speed_bytes
                                
                                smoothed_eta = 0
                                if avg_speed > 0:
                                    smoothed_eta = int((total_bytes - downloaded_bytes) / avg_speed)

                                time_elapsed = int(time.time() - active_tasks[task_id].get("start_time", time.time()))

                                active_tasks[task_id].update({
                                    "percent": pct,
                                    "total_bytes": total_bytes,
                                    "downloaded_bytes": downloaded_bytes,
                                    "speed_bytes": avg_speed,
                                    "eta_seconds": smoothed_eta,
                                    "time_elapsed": time_elapsed,
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
                                "error": "Download blocked by site policy (HTTP 403). The site requires session cookies. Export cookies.txt into the app directory to download."
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
            force_mp4 = data.get("force_mp4", False)
            start_download_thread(task_id, url, format_id, is_audio, output_dir, is_playlist=is_playlist, force_mp4=force_mp4)
            self.send_json({"task_id": task_id, "status": "queued"})
            return

        elif path == "/api/cancel-task":
            task_id = data.get("task_id")
            if task_id and task_id in process_store:
                proc = process_store[task_id]
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except:
                        pass
                with active_lock:
                    if task_id in active_tasks:
                        active_tasks[task_id]["status"] = "canceled"
                self.send_json({"success": True})
            else:
                self.send_json({"error": "Task not found"}, 404)
            return

        elif path == "/api/pause-task":
            task_id = data.get("task_id")
            if task_id and task_id in process_store:
                proc = process_store[task_id]
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGSTOP)
                    with active_lock:
                        if task_id in active_tasks:
                            active_tasks[task_id]["status"] = "paused"
                    self.send_json({"success": True})
                except Exception as e:
                    self.send_json({"error": f"Failed to pause: {str(e)}"}, 500)
            else:
                self.send_json({"error": "Task not found"}, 404)
            return

        elif path == "/api/resume-task":
            task_id = data.get("task_id")
            if task_id and task_id in process_store:
                proc = process_store[task_id]
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGCONT)
                    with active_lock:
                        if task_id in active_tasks:
                            active_tasks[task_id]["status"] = "downloading"
                    self.send_json({"success": True})
                except Exception as e:
                    self.send_json({"error": f"Failed to resume: {str(e)}"}, 500)
            else:
                self.send_json({"error": "Task not found"}, 404)
            return

        elif path == "/api/select-folder":
            try:
                script = 'tell application "Finder" to activate\nset chosenFolder to choose folder with prompt "Select OmniStream Download Folder"\nPOSIX path of chosenFolder'
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
                res = subprocess.run(["open", filepath])
                if res.returncode != 0:
                    subprocess.run(["osascript", "-e", f'tell application "Finder" to open POSIX file "{filepath}"'])
                self.send_json({"success": True})
            else:
                self.send_json({"error": "File not found"}, 404)
            return

        elif path == "/api/open-folder":
            filepath = data.get("filepath") or str(DOWNLOADS_DIR)
            if not os.path.exists(filepath):
                filepath = str(DOWNLOADS_DIR)
            
            if os.path.exists(filepath):
                if os.path.isfile(filepath):
                    res = subprocess.run(["open", "-R", filepath])
                    if res.returncode != 0:
                        subprocess.run(["osascript", "-e", f'tell application "Finder" to reveal POSIX file "{filepath}"', "-e", 'tell application "Finder" to activate'])
                else:
                    res = subprocess.run(["open", filepath])
                    if res.returncode != 0:
                        subprocess.run(["osascript", "-e", f'tell application "Finder" to open POSIX file "{filepath}"', "-e", 'tell application "Finder" to activate'])
                self.send_json({"success": True})
            else:
                self.send_json({"error": "Folder not found"}, 404)
            return

        elif path == "/api/clear-history":
            with open(HISTORY_FILE, "w") as f:
                json.dump([], f)
            self.send_json({"success": True})
            return

        elif path == "/api/update-engine":
            try:
                # Runs yt-dlp -U
                cmd = [YTDLP_BIN, "-U"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0:
                    self.send_json({"success": True, "output": res.stdout})
                else:
                    self.send_json({"error": res.stderr or res.stdout}, 500)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
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
    import webview
    os.chdir(str(PUBLIC_DIR))
    
    def run_server():
        print(f"OmniStream Server starting on http://localhost:{PORT}")
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
            httpd.serve_forever()

    # Start HTTP server in background thread
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    
    # Start native webview window
    webview.create_window("OmniStream", f"http://localhost:{PORT}", width=1000, height=800, background_color="#0d1117")
    webview.start()
