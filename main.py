import os
import json
import subprocess
from datetime import datetime, timezone
from dateutil.parser import isoparse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIG ---
CONFIG_FILE = "config/channels.json"
STATE_DIR = "state"
VIDEO_FILE = "video.mp4"
THUMB_FILE = "thumb.jpg"

def load_json(path, default_val):
    if not os.path.exists(path): return default_val
    with open(path, 'r') as f: return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f: json.dump(data, f, indent=2)

def get_yt_client():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"]
    )
    return build("youtube", "v3", credentials=creds)

def download_video(video_id):
    print(f"⬇️ Downloading: {video_id}")
    if os.path.exists(VIDEO_FILE): os.remove(VIDEO_FILE)

    # Use cookies if the file was created by the workflow
    cookie_args = ["--cookies", "cookies.txt"] if os.path.exists("cookies.txt") else []

    cmd = [
        "yt-dlp",
        *cookie_args,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", VIDEO_FILE,
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    
    # Run download
    subprocess.run(cmd, check=True)

def upload_video(youtube, snippet, privacy):
    print(f"⬆️ Uploading: {snippet['title']}")
    body = {
        "snippet": {
            "title": snippet["title"], 
            "description": snippet["description"],
            "tags": snippet.get("tags", [])
        },
        "status": {"privacyStatus": privacy}
    }
    media = MediaFileUpload(VIDEO_FILE, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    return request.execute()["id"]

# ... (Include previous download_thumbnail and fetch_videos functions here) ...

def main():
    if not os.path.exists(STATE_DIR): os.makedirs(STATE_DIR)
    
    uploaded = load_json(f"{STATE_DIR}/uploaded.json", {})
    queues = load_json(f"{STATE_DIR}/queues.json", {})
    last_check = load_json(f"{STATE_DIR}/last_check.json", {})
    config = load_json(CONFIG_FILE, {"channels": []})
    
    youtube = get_yt_client()

    for ch in config["channels"]:
        src = ch["source_channel_id"]
        uploaded.setdefault(src, [])
        queues.setdefault(src, [])
        
        last_dt_str = last_check.get(src)
        last_dt = isoparse(last_dt_str) if last_dt_str else datetime.min.replace(tzinfo=timezone.utc)
        
        print(f"🔍 Checking: {src}")
        vids = [] # fetch_videos logic here...
        
        # logic to sort into new/old and then:
        # download_video(vid)
        # upload_video(youtube, snippet, privacy)
        # ... (Same logic as previous versions) ...

if __name__ == "__main__":
    main()