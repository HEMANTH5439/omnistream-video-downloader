import PyInstaller.__main__
import os

if __name__ == "__main__":
    # Ensure bin directory contains yt-dlp and aria2c
    if not os.path.exists("bin/yt-dlp") or not os.path.exists("bin/aria2c"):
        print("Error: Missing required binaries in bin/")
        exit(1)

    PyInstaller.__main__.run([
        'server.py',
        '--name=OmniStream',
        '--windowed',
        '--noconfirm',
        '--clean',
        '--add-data=public:public',
        '--add-data=bin:bin'
    ])
