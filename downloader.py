import yt_dlp

# --- CONFIGURATION ---
url = "https://www.youtube.com/watch?v=dKGIw93XTJ0" 
# ---------------------

print(f"Starting download for: {url}")

opts = {
    'cookiefile': 'cookies.txt', # Bypasses the bot login block
    
    'format': 'bestvideo+bestaudio/best',
    
    # Force the 'tv' client to bypass SABR unreadable streams
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
