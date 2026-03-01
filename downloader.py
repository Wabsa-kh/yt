import yt_dlp

# --- CONFIGURATION ---
url = "https://www.youtube.com/watch?v=dKGIw93XTJ0" 
# ---------------------

print(f"Starting download for: {url}")

opts = {
    # 1. Use cookies to bypass the "Sign in" bot block
    'cookiefile': 'cookies.txt',
    
    'format': 'bestvideo+bestaudio/best',
    
    # 2. FORCE the 'tv' client only. Do NOT use web browsers.
    'extractor_args': {
        'youtube': {
            'player_client':['tv']
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
