import os
import json
import requests
import time
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
COBALT_API = "https://api.cobalt.tools/api/json" # The magic tool

def load_json(path, default_val):
    if not os.path.exists(path): return default_val
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return default_val

def save_json(path, data):
    with open(path, 'w') as f: json.dump(data, f, indent=2)

def get_youtube_client():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"]
    )
    return build("youtube", "v3", credentials=creds)

def download_video_cobalt(video_id):
    print(f"⬇️ Downloading via Cobalt: {video_id}")
    if os.path.exists(VIDEO_FILE): os.remove(VIDEO_FILE)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    payload = {
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "vCodec": "h264",
        "vQuality": "1080",
        "filenamePattern": "basic"
    }

    # 1. Get Download Link
    try:
        response = requests.post(COBALT_API, json=payload, headers=headers)
        data = response.json()
        
        if "url" not in data:
            print(f"❌ Cobalt Error: {data}")
            return False
            
        download_url = data["url"]
        
        # 2. Download File
        print("🔗 Link acquired. Saving file...")
        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            with open(VIDEO_FILE, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"❌ Download Failed: {e}")
        return False

def download_thumbnail(snippet):
    thumbs = snippet.get("thumbnails", {})
    url = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
    if not url: return False
    
    try:
        r = requests.get(url, timeout=10)
        with open(THUMB_FILE, "wb") as f:
            f.write(r.content)
        return True
    except:
        return False

def upload_video(youtube, snippet, privacy):
    print(f"⬆️ Uploading: {snippet['title']}")
    body = {
        "snippet": {
            "title": snippet["title"], 
            "description": snippet["description"],
            "tags": snippet.get("tags", [])
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(VIDEO_FILE, chunksize=-1, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    return req.execute()["id"]

def set_thumbnail(youtube, video_id):
    if not os.path.exists(THUMB_FILE): return
    print("🖼️ Setting thumbnail...")
    try:
        youtube.thumbnails().set(videoId=video_id, media_body=THUMB_FILE).execute()
    except Exception as e:
        print(f"⚠️ Thumbnail Error: {e}")

def fetch_videos(youtube, channel_id):
    vids = []
    req = youtube.search().list(part="snippet", channelId=channel_id, maxResults=50, order="date", type="video")
    while req:
        res = req.execute()
        vids.extend(res.get("items", []))
        req = youtube.search().list_next(req, res)
        if len(vids) >= 50: break
    return vids

def main():
    if not os.path.exists(STATE_DIR): os.makedirs(STATE_DIR)
    
    uploaded = load_json(f"{STATE_DIR}/uploaded.json", {})
    queues = load_json(f"{STATE_DIR}/queues.json", {})
    last_check = load_json(f"{STATE_DIR}/last_check.json", {})
    config = load_json(CONFIG_FILE, {"channels": []})
    
    youtube = get_youtube_client()

    for ch in config["channels"]:
        src = ch["source_channel_id"]
        uploaded.setdefault(src, [])
        queues.setdefault(src, [])
        
        last_dt = isoparse(last_check.get(src)) if last_check.get(src) else datetime.min.replace(tzinfo=timezone.utc)
        
        print(f"🔍 Checking: {src}")
        videos = fetch_videos(youtube, src)
        
        new_vids = []
        for v in videos:
            vid = v["id"]["videoId"]
            pub = isoparse(v["snippet"]["publishedAt"])
            
            if vid in uploaded[src]: continue
            
            if pub > last_dt:
                new_vids.append(v)
            elif vid not in queues[src]:
                queues[src].append(vid)

        # PROCESS NEW (Reverse to upload oldest 'New' first)
        new_vids.reverse()
        count = 0
        for v in new_vids:
            if count >= ch["max_new_per_run"]: break
            vid = v["id"]["videoId"]
            
            if download_video_cobalt(vid):
                download_thumbnail(v["snippet"])
                new_id = upload_video(youtube, v["snippet"], ch["privacy_status"])
                set_thumbnail(youtube, new_id)
                uploaded[src].append(vid)
                count += 1
                time.sleep(5) # Safety buffer

        # PROCESS OLD
        count = 0
        while count < ch["max_old_per_run"] and queues[src]:
            vid = queues[src].pop(0)
            
            # Fetch full snippet for old video
            try:
                details = youtube.videos().list(part="snippet", id=vid).execute()
                if not details["items"]: continue
                snippet = details["items"][0]["snippet"]
                
                if download_video_cobalt(vid):
                    download_thumbnail(snippet)
                    new_id = upload_video(youtube, snippet, ch["privacy_status"])
                    set_thumbnail(youtube, new_id)
                    uploaded[src].append(vid)
                    count += 1
                    time.sleep(5)
            except Exception as e:
                print(f"❌ Error on old video {vid}: {e}")

        last_check[src] = datetime.now(timezone.utc).isoformat()

    save_json(f"{STATE_DIR}/uploaded.json", uploaded)
    save_json(f"{STATE_DIR}/queues.json", queues)
    save_json(f"{STATE_DIR}/last_check.json", last_check)
    print("✅ Done.")

if __name__ == "__main__":
    main()