import yt_dlp

# --- CONFIGURATION ---
# Let's use a very standard video for testing first
url = "https://www.youtube.com/watch?v=dKGIw93XTJ0" 
# ---------------------

print(f"Starting download for: {url}")

opts = {
    'cookiefile': 'cookies.txt',
    
    # FIX 1: Don't force MP4 immediately. Get whatever is best (WebM/MKV), 
    # we can convert it later if needed.
    'format': 'bestvideo+bestaudio/best',
    
    # FIX 2: THE ANDROID TRICK
    # This tells YouTube we are an app, bypassing the "SABR" block.
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
