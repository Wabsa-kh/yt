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

# --- CONFIG & PATHS ---
CONFIG_FILE = "config/channels.json"
STATE_DIR = "state"
VIDEO_FILE = "video.mp4"
THUMB_FILE = "thumb.jpg"

# --- HELPERS ---
def load_json(path, default_val):
    if not os.path.exists(path): return default_val
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return default_val

def save_json(path, data):
    if not os.path.exists(STATE_DIR): os.makedirs(STATE_DIR)
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

# --- DOWNLOAD LOGIC ---
def download_video(video_id):
    print(f"⬇️ Downloading video: {video_id}")
    if os.path.exists(VIDEO_FILE): os.remove(VIDEO_FILE)

    # --- ATTEMPT 1: YT-DLP WITH COOKIES ---
    if os.path.exists("cookies.txt"):
        print("🍪 Attempting download with cookies...")
        try:
            # We use a broader format selection to avoid "Format not available" errors
            cmd = [
                "yt-dlp",
                "--cookies", "cookies.txt",
                "-f", "bv+ba/b", # Download best available and merge
                "--merge-output-format", "mp4",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "-o", VIDEO_FILE,
                f"https://www.youtube.com/watch?v={video_id}"
            ]
            subprocess.run(cmd, check=True)
            if os.path.exists(VIDEO_FILE): 
                print("✅ YT-DLP download success!")
                return True
        except Exception as e:
            print(f"⚠️ YT-DLP failed: {e}")

    # --- ATTEMPT 2: COBALT FALLBACK (If YT-DLP is blocked) ---
    print("📡 YT-DLP blocked. Trying Cobalt Fallback (No cookies needed)...")
    # Using multiple instances in case one is down
    instances = ["https://api.cobalt.tools", "https://cobalt.xy24.eu", "https://cobalt.kanzi.date"]
    payload = {
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "videoQuality": "1080",
        "youtubeVideoCodec": "h264" # Ensures high quality mp4
    }
    
    for base in instances:
        try:
            print(f"Trying Cobalt instance: {base}")
            res = requests.post(base, json=payload, headers={"Accept": "application/json"}, timeout=20)
            data = res.json()
            if "url" in data:
                with requests.get(data["url"], stream=True) as r:
                    r.raise_for_status()
                    with open(VIDEO_FILE, 'wb') as f:
                        for chunk in r.iter_content(8192): f.write(chunk)
                print("✅ Cobalt download success!")
                return True
        except Exception as e:
            print(f"❌ Instance {base} failed: {e}")
            continue
        
    raise Exception("🔥 CRITICAL: All download methods failed. YouTube is heavily blocking this IP.")
def download_thumbnail(snippet):
    print("🖼️ Fetching thumbnail...")
    thumbs = snippet.get("thumbnails", {})
    # Try to get the highest resolution possible
    url = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
    
    if not url: return False

    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(THUMB_FILE, "wb") as f:
                f.write(r.content)
            return True
    except: pass
    return False

# --- UPLOAD LOGIC ---
def upload_video(youtube, snippet, privacy):
    print(f"⬆️ Uploading to YouTube: {snippet['title']}")
    
    body = {
        "snippet": {
            "title": snippet["title"], 
            "description": snippet["description"],
            "tags": snippet.get("tags", []),
            "categoryId": "22" # Default to 'People & Blogs'
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(VIDEO_FILE, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    return response["id"]

def set_thumbnail(youtube, video_id):
    if not os.path.exists(THUMB_FILE): return
    print("🎨 Applying thumbnail...")
    try:
        youtube.thumbnails().set(videoId=video_id, media_body=THUMB_FILE).execute()
    except Exception as e:
        print(f"⚠️ Thumbnail Error: {e}")

# --- API LOGIC ---
def fetch_videos(youtube, channel_id):
    try:
        # Get the 'Uploads' playlist ID for the channel (More reliable than search)
        ch_req = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        if not ch_req.get("items"): return []
        
        uploads_id = ch_req["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        # Get latest 50 items from that playlist
        res = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        
        vids = []
        for item in res.get("items", []):
            video_id = item["snippet"]["resourceId"]["videoId"]
            item["id"] = {"videoId": video_id} # Format to match script
            vids.append(item)
        
        print(f"📊 Found {len(vids)} videos on the source channel.")
        return vids
    except Exception as e:
        print(f"❌ API Error: {e}")
        return []

# --- MAIN ENGINE ---
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

        print(f"🔍 Checking channel: {src}")
        videos = fetch_videos(youtube, src)
        
        if not videos:
            print("⚠️ No videos found or API error.")
            continue

        new_vids = []
        for v in videos:
            vid = v["id"]["videoId"]
            pub = isoparse(v["snippet"]["publishedAt"])
            
            if vid in uploaded[src]: continue
            
            if pub > last_dt:
                new_vids.append(v)
            elif vid not in queues[src]:
                queues[src].append(vid)

        print(f"✨ New: {len(new_vids)} | In Queue: {len(queues[src])}")

        # 1. Process NEW Videos
        new_vids.reverse() # Upload oldest of the new first
        count = 0
        for v in new_vids:
            if count >= ch.get("max_new_per_run", 1): break
            vid = v["id"]["videoId"]
            
            try:
                download_video(vid)
                download_thumbnail(v["snippet"])
                new_id = upload_video(youtube, v["snippet"], ch["privacy_status"])
                set_thumbnail(youtube, new_id)
                uploaded[src].append(vid)
                count += 1
                time.sleep(10) # Prevent spam flags
            except Exception as e:
                print(f"❌ Error with {vid}: {e}")

        # 2. Process OLD Videos from Queue
        count = 0
        while count < ch.get("max_old_per_run", 1) and queues[src]:
            vid = queues[src].pop(0)
            try:
                # Need to fetch details since playlist snippet is limited
                v_res = youtube.videos().list(part="snippet", id=vid).execute()
                if not v_res["items"]: continue
                snippet = v_res["items"][0]["snippet"]

                download_video(vid)
                download_thumbnail(snippet)
                new_id = upload_video(youtube, snippet, ch["privacy_status"])
                set_thumbnail(youtube, new_id)
                uploaded[src].append(vid)
                count += 1
                time.sleep(10)
            except Exception as e:
                print(f"❌ Error with old video {vid}: {e}")

        # Save timestamp for next run
        last_check[src] = datetime.now(timezone.utc).isoformat()

    # Save State
    save_json(f"{STATE_DIR}/uploaded.json", uploaded)
    save_json(f"{STATE_DIR}/queues.json", queues)
    save_json(f"{STATE_DIR}/last_check.json", last_check)
    print("✅ All tasks complete.")

if __name__ == "__main__":
    main()
