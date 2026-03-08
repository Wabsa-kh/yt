import os
import json
import yt_dlp
import re
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# --- FILE PATHS ---
CONFIG_FILE = "config.txt"
QUEUES_FILE = "queues.json"
STATE_FILE = "state.json"
UPLOADED_FILE = "uploaded.txt"
COOKIES_FILE = "cookies.txt"

# --- HELPERS ---
def load_text_list(filepath):
    if not os.path.exists(filepath): return []
    with open(filepath, "r", encoding="utf-8") as f: return [line.strip() for line in f if line.strip()]

def save_text_list(filepath, data_list):
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data_list: f.write(f"{item}\n")

def load_json(filepath, default_value):
    if not os.path.exists(filepath): return default_value
    try:
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except: return default_value

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)

def extract_video_id(url):
    """Extracts ID from YouTube URL safely."""
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
    return build('youtube', 'v3', credentials=creds)

# ==========================================
# 1. SMART SCANNER (Only scans config.txt)
# ==========================================
def update_channel_queues(config_channels, uploaded_ids, all_queues):
    # We only iterate through channels currently in config.txt
    for channel in config_channels:
        ydl_opts = {
            'extract_flat': True, 'quiet': True, 'cookiefile': COOKIES_FILE,
            'extractor_args': {'youtube': {'player_client': ['tv']}}
        }
        if channel not in all_queues:
            all_queues[channel] = []
            print(f"\n🚨 NEW CHANNEL: {channel}")
        else:
            print(f"\n⚡ SCANNING: {channel}")
            ydl_opts['playlistend'] = 15
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                if 'entries' in info:
                    entries = list(info['entries']) 
                    fresh = [f"https://www.youtube.com/watch?v={e['id']}" for e in entries if e['id'] and e['id'] not in uploaded_ids and f"https://www.youtube.com/watch?v={e['id']}" not in all_queues[channel]]
                    if fresh:
                        all_queues[channel] = fresh + all_queues[channel]
                        print(f"   -> Found {len(fresh)} new videos.")
        except Exception as e: print(f"   ❌ Error scanning: {e}")
    return all_queues

# ==========================================
# 2. SMART DRAIN SELECTOR (Uses queues.json)
# ==========================================
def get_next_video_to_upload(all_queues, last_index):
    """
    Looks at ALL channels in the JSON (even if removed from config).
    Provides a Round-Robin selection.
    """
    all_stored_channels = list(all_queues.keys())
    total = len(all_stored_channels)
    if total == 0: return None, None, last_index

    start = (last_index + 1) % total
    for i in range(total):
        idx = (start + i) % total
        channel_url = all_stored_channels[idx]
        if len(all_queues[channel_url]) > 0:
            return all_queues[channel_url][0], channel_url, idx
    return None, None, last_index

# ==========================================
# 3. UPLOADER
# ==========================================
def attempt_upload(video_file, thumb_file, title, description):
    api_accounts = [
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]
    request_body = {'snippet': {'title': title[:100], 'description': description[:5000], 'categoryId': '24'}, 'status': {'privacyStatus': 'public'}}

    for account in api_accounts:
        if not account['id']: continue
        print(f"\n--- Checking Account: {account['name']} ---")
        try:
            youtube = get_auth_service(account['id'], account['sec'], account['tok'])
            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=request_body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: print(f"   -> Progress: {int(status.progress() * 100)}%")
            print(f"✅ SUCCESS! ID: {response['id']}")
            if os.path.exists(thumb_file):
                try: youtube.thumbnails().set(videoId=response['id'], media_body=MediaFileUpload(thumb_file)).execute()
                except: pass
            return True 
        except HttpError as e:
            try: reason = json.loads(e.content.decode())['error']['errors'][0]['reason']
            except: reason = "unknown"
            print(f"❌ API Error: {reason}")
            if reason in ["quotaExceeded", "dailyLimitExceeded", "invalid_grant"]: continue
            elif reason == "uploadLimitExceeded": return False 
            elif e.resp.status == 409: return True
            else: continue
        except Exception: continue
    return False

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    config_channels = load_text_list(CONFIG_FILE)
    uploaded_ids = load_text_list(UPLOADED_FILE)
    all_queues = load_json(QUEUES_FILE, {})
    state = load_json(STATE_FILE, {"last_index": -1})

    # 1. Update Queues (Only for channels in config.txt)
    if config_channels:
        all_queues = update_channel_queues(config_channels, uploaded_ids, all_queues)
        save_json(QUEUES_FILE, all_queues)

    # 2. Infinite Selection Loop (To handle "Last-Second Check")
    while True:
        target_url, channel_owner, new_index = get_next_video_to_upload(all_queues, state['last_index'])
        
        if not target_url:
            print("\n💤 All queues are empty.")
            break

        # --- LAST-SECOND CHECK ---
        vid_id = extract_video_id(target_url)
        if vid_id in uploaded_ids:
            print(f"♻️ Skipping {vid_id}: Already found in uploaded.txt. Cleaning queue...")
            all_queues[channel_owner].pop(0)
            save_json(QUEUES_FILE, all_queues)
            state['last_index'] = new_index # Move turn to next channel
            continue # Try the next channel in the rotation
        
        # If we reach here, the video is truly new!
        print(f"\n🎯 SELECTED: {target_url} from {channel_owner}")
        
        # 3. Download & Upload
        opts = {
            'cookiefile': COOKIES_FILE, 'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'extractor_args': {'youtube': {'player_client': ['tv']}}, 'outtmpl': 'downloaded_video.%(ext)s',
            'writethumbnail': True, 'postprocessors': [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}], 'quiet': False
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                v_file, t_file, title, desc, orig_id = "downloaded_video.mp4", "downloaded_video.jpg", info.get('title'), info.get('description'), info.get('id')
                
                if attempt_upload(v_file, t_file, title, desc):
                    all_queues[channel_owner].pop(0)
                    uploaded_ids.append(orig_id)
                    state['last_index'] = new_index
                    save_json(QUEUES_FILE, all_queues); save_text_list(UPLOADED_FILE, uploaded_ids); save_json(STATE_FILE, state)
                    print(f"🎉 SYSTEM FINISHED.")
                else:
                    print("❌ Upload failed.")
                break # Exit the loop after trying 1 upload
        except Exception as e:
            print(f"❌ Process failed: {e}")
            all_queues[channel_owner].pop(0)
            save_json(QUEUES_FILE, all_queues)
            break
