import yt_dlp

# --- CONFIGURATION ---
url = "https://www.youtube.com/watch?v=dKGIw93XTJ0" 
# ---------------------

print(f"Starting download for: {url}")

opts = {
    'cookiefile': 'cookies.txt',
    'format': 'bestvideo+bestaudio/best',
    
    # Drop 'mweb', use 'tv' and 'web_safari'
    'extractor_args': {
        'youtube': {
            'player_client': ['tv', 'web_safari']
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
