import os
import json
import time
import requests
import subprocess
from datetime import datetime, timezone
from dateutil.parser import isoparse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONSTANTS ---
CONFIG_FILE = "config/channels.json"
STATE_DIR = "state"
VIDEO_FILE = "video.mp4"
THUMB_FILE = "thumb.jpg"

def load_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return default

def save_json(path, data):
    if not os.path.exists(STATE_DIR): os.makedirs(STATE_DIR)
    with open(path, 'w') as f: json.dump(data, f, indent=2)

# --- AUTH LOGIC (From your working script) ---
def get_yt_client():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"]
    )
    return build("youtube", "v3", credentials=creds)

# --- DOWNLOAD LOGIC (Tor Powered) ---
def download_video(video_id):
    print(f"🛡️ Downloading {video_id} via Tor Proxy...")
    if os.path.exists(VIDEO_FILE): os.remove(VIDEO_FILE)
    
    cookie_args = ["--cookies", "cookies.txt"] if os.path.exists("cookies.txt") else []
    
    cmd = [
        "yt-dlp",
        "--proxy", "socks5://127.0.0.1:9050",
        *cookie_args,
        "-f", "bv[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
        "--merge-output-format", "mp4",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "-o", VIDEO_FILE,
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        return os.path.exists(VIDEO_FILE)
    except Exception as e:
        print(f"⚠️ Tor download failed: {e}")
        return False

def download_thumbnail(snippet):
    thumbs = snippet.get("thumbnails", {})
    url = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
    if not url: return False
    try:
        r = requests.get(url, timeout=15)
        with open(THUMB_FILE, "wb") as f: f.write(r.content)
        return True
    except: return False

# --- UPLOAD LOGIC (Using your working Resumable Chunks) ---
def upload_video(youtube, snippet, privacy):
    print(f"🚀 Initializing upload: {snippet['title']}")
    
    body = {
        "snippet": {
            "title": snippet["title"][:100],
            "description": snippet["description"][:4000],
            "categoryId": "22", 
            "tags": snippet.get("tags", [])
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(VIDEO_FILE, chunksize=1024*1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    print("⏳ Uploading in chunks...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"   📊 Progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"✅ SUCCESS! Video ID: {video_id}")
    return video_id

def set_thumbnail(youtube, video_id):
    if not os.path.exists(THUMB_FILE): return
    try:
        print("🎨 Setting thumbnail...")
        youtube.thumbnails().set(videoId=video_id, media_body=THUMB_FILE).execute()
        print("✅ Thumbnail applied!")
    except Exception as e:
        print(f"⚠️ Thumbnail failed: {e}")

# --- API FETCH LOGIC ---
def fetch_videos(youtube, channel_id):
    try:
        ch_req = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        uploads_id = ch_req["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        res = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        
        vids = []
        for item in res.get("items", []):
            vid = item["snippet"]["resourceId"]["videoId"]
            item["id"] = {"videoId": vid}
            vids.append(item)
        return vids
    except: return []

# --- MAIN ENGINE ---
def main():
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

        videos = fetch_videos(youtube, src)
        new_vids = []
        for v in videos:
            vid = v["id"]["videoId"]
            pub = isoparse(v["snippet"]["publishedAt"])
            if vid in uploaded[src]: continue
            if pub > last_dt: new_vids.append(v)
            elif vid not in queues[src]: queues[src].append(vid)

        # 1. Process NEW
        new_vids.reverse()
        if new_vids:
            v = new_vids[0]
            print(f"🎬 New Video Detected: {v['snippet']['title']}")
            if download_video(v["id"]["videoId"]):
                download_thumbnail(v["snippet"])
                new_id = upload_video(youtube, v["snippet"], ch["privacy_status"])
                set_thumbnail(youtube, new_id)
                uploaded[src].append(v["id"]["videoId"])

        # 2. Process OLD from Queue
        if queues[src]:
            vid = queues[src].pop(0)
            print(f"⏳ Processing Queue: {vid}")
            try:
                v_res = youtube.videos().list(part="snippet", id=vid).execute()
                if v_res["items"]:
                    snippet = v_res["items"][0]["snippet"]
                    if download_video(vid):
                        download_thumbnail(snippet)
                        new_id = upload_video(youtube, snippet, ch["privacy_status"])
                        set_thumbnail(youtube, new_id)
                        uploaded[src].append(vid)
            except Exception as e:
                print(f"❌ Queue Error: {e}")

        last_check[src] = datetime.now(timezone.utc).isoformat()

    save_json(f"{STATE_DIR}/uploaded.json", uploaded)
    save_json(f"{STATE_DIR}/queues.json", queues)
    save_json(f"{STATE_DIR}/last_check.json", last_check)
    print("✅ Run Complete.")

if __name__ == "__main__":
    main()
