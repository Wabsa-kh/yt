import yt_dlp

# --- CONFIGURATION ---
url = "https://www.youtube.com/watch?v=dKGIw93XTJ0" 
# ---------------------

print(f"Starting download for: {url}")

opts = {
    # 1. Put cookies back to bypass the "Sign in / Bot" block
    'cookiefile': 'cookies.txt',
    
    'format': 'bestvideo+bestaudio/best',
    
    # 2. Use 'tv' and 'mweb' clients. 
    # They support cookies AND bypass the "SABR" unreadable stream block!
    'extractor_args': {
        'youtube': {
            'player_client': ['tv', 'mweb']
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
