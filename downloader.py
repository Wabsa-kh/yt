import yt_dlp

# --- CONFIGURATION ---
url = "https://www.youtube.com/watch?v=dKGIw93XTJ0" 
# ---------------------

print(f"Starting download for: {url}")

opts = {
    'format': 'bestvideo+bestaudio/best',
    
    # Pretend to be an Android app (This ONLY works if cookies are NOT used)
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        }
    },
    
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
