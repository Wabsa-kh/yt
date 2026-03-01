import yt_dlp
import os

def download_video(url):
    print(f"Starting download for: {url}")
    
    ydl_opts = {
        'cookiefile': 'cookies.txt',
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': 'downloaded_video.%(ext)s',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print("Download successful!")
    except Exception as e:
        print(f"Error downloading: {e}")

if __name__ == "__main__":
    # Test URL - replace with any video you want to test
    target_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw" 
    download_video(target_url)
