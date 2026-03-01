import yt_dlp

# --- CONFIGURATION ---
url = "https://www.youtube.com/watch?v=dKGIw93XTJ0"
# ---------------------

print(f"Starting download for: {url}")

# Define options dictionary
opts = {
    'cookiefile': 'cookies.txt',
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
    'outtmpl': 'downloaded_video.%(ext)s',
    'verbose': True
}

# Run the download
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    print("Download successful!")
except Exception as e:
    print(f"Error downloading: {e}")
