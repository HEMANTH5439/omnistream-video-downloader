# OmniStream - Universal HD Video & Playlist Downloader

OmniStream is a modern, feature-rich local web application designed to download videos and full playlists from over 1,000+ supported websites (including YouTube, TikTok, Twitter/X, Vimeo, Twitch, Reddit, Instagram, Dailymotion, etc.) with custom resolution selection, live progress tracking, and native macOS folder integration.

![OmniStream Banner](https://raw.githubusercontent.com/HEMANTH5439/omnistream-video-downloader/main/public/index.html)

## 🌟 Key Features

- **Resolution & Quality Selection**:
  - Automatically parses video metadata and provides options for 4K (2160p), 2K (1440p), 1080p Full HD, 720p HD, 480p, 360p, 240p, and high-bitrate Audio MP3/M4A.
  - Displays estimated file sizes for each format option.

- **Full Playlist Download Support**:
  - Automatically detects YouTube & platform playlists.
  - Previews item count, video titles, and thumbnails, allowing 1-click batch playlist downloads.

- **Native macOS Folder Chooser**:
  - Features a **"Browse..."** button that launches the native macOS Finder Folder Picker window.
  - Easily set any destination folder on your Mac.

- **Live Progress & Download Stats**:
  - Real-time download progress bar, speed (`MB/s`), total size downloaded, and estimated time remaining (`ETA`).

- **Download History & macOS Finder Integration**:
  - View download history with instant **"Play Video"** and **"Reveal in Finder"** actions.

- **Dark Mode Glassmorphism UI**:
  - Ultra-sleek design with animated background glow orbs, responsive glass cards, and modern typography (`Outfit` & `Plus Jakarta Sans`).

---

## 🚀 Getting Started

### Prerequisites
- macOS (or Linux / Windows)
- Python 3.10+ (Python 3.12 recommended)
- `yt-dlp` executable

### Quick Run

1. Clone repository:
   ```bash
   git clone https://github.com/HEMANTH5439/omnistream-video-downloader.git
   cd omnistream-video-downloader
   ```

2. Run local web server:
   ```bash
   python3 server.py
   ```

3. Open your browser at **[http://localhost:8888](http://localhost:8888)**.

---

## 🛠️ Architecture

- **Backend**: Python 3.12 HTTP server (`server.py`), subprocess task manager, and `osascript` native folder chooser.
- **Frontend**: Single-Page Application (HTML5, Vanilla CSS3 Glassmorphism, JavaScript ES6).
- **Core Engine**: `yt-dlp` integration with smart cookie fallbacks for bot/age-restricted content.

---

## 📜 License
MIT License - feel free to use and customize!
