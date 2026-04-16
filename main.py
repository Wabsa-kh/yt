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

# --- ADVANCED METADATA ---
CATEGORY_ID = "24"     # Entertainment
LANGUAGE = "en"        # English
MADE_FOR_KIDS = False 

def load_text_list(filepath):
    if not os.path.exists(filepath): return []
    with open(filepath, "r", encoding="utf-8") as f: 
        return [line.strip() for line in f if line.strip()]

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
    if not url: return None
    # Matches standard URLs, Shorts, and mobile shares
    match = re.search(r"(?:v=|\/shorts\/|\/)([0-9A-Za-z_-]{11})", url)
    return match.group(1) if match else None

def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(
        token=None, 
        refresh_token=refresh_token, 
        token_uri="https://oauth2.googleapis.com/token", 
        client_id=client_id, 
        client_secret=client_secret
    )
    return build('youtube', 'v3', credentials=creds)

# ==========================================
# 1. SMART SCANNER (FIXED)
# ==========================================
def update_channel_queues(config_channels, uploaded_ids, all_queues):
    for channel in config_channels:
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'tv']}}
        }
        
        if channel not in all_queues:
            all_queues[channel] = []
            print(f"\n🚨 NEW CHANNEL: {channel} -> Scanning ENTIRE history.")
        else:
            print(f"\n⚡ SCANNING: {channel} -> Checking newest videos.")
            ydl_opts['playlistend'] = 15
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                if 'entries' in info:
                    fresh = []
                    for entry in info['entries']:
                        if entry and entry.get('id'):
                            v_id = entry['id']
                            v_url = f"https://www.youtube.com/watch?v={v_id}"
                            
                            # Only add if not already uploaded and not already in current queue
                            if v_id not in uploaded_ids and v_url not in all_queues[channel]:
                                fresh.append(v_url)
                    
                    if fresh:
                        # Add new videos to the top of the queue
                        all_queues[channel] = fresh + all_queues[channel]
                        print(f"   -> Added {len(fresh)} new videos.")
                    else:
                        print("   -> No new videos found.")
        except Exception as e:
            print(f"   ❌ Scan failed: {e}")
    return all_queues

# ==========================================
# 2. SMART DRAIN SELECTOR
# ==========================================
def get_next_video_to_upload(all_queues, last_index):
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
# 3. DOWNLOADER
# ==========================================
def download_video(url):
    print(f"\n--- DOWNLOADING: {url} ---")
    
    # Sequential strategies to bypass bot detection
    attempt_configs = [
        { 'extractor_args': {'youtube': {'player_client': ['ios', 'android']}} },
        { 'cookiefile': COOKIES_FILE, 'extractor_args': {'youtube': {'player_client': ['tv']}} },
        { 'cookiefile': COOKIES_FILE, 'extractor_args': {'youtube': {'player_client':['web_safari']}} }
    ]

    for i, extra_opts in enumerate(attempt_configs):
        base_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'outtmpl': 'downloaded_video.%(ext)s',
            'writethumbnail': True,
            'postprocessors': [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
            'quiet': False,
            'overwrites': True
        }
        base_opts.update(extra_opts)

        print(f"   -> Strategy {i+1}...")
        try:
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ("downloaded_video.mp4", "downloaded_video.jpg", 
                        info.get('title', 'Video'), info.get('description', ''), info.get('id'))
        except Exception as e:
            print(f"   ⚠️ Strategy {i+1} failed: {e}")
            continue
    
    return None, None, None, None, None

# ==========================================
# 4. UPLOADER
# ==========================================
def attempt_upload(video_file, thumb_file, title, description):
    api_accounts = [
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]
    
    accounts_to_try = [acc for acc in api_accounts if acc['id'] and acc['sec'] and acc['tok']]

    body = {
        'snippet': {
            'title': title[:100], 'description': description[:5000],
            'categoryId': CATEGORY_ID, 'defaultLanguage': LANGUAGE
        },
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': MADE_FOR_KIDS}
    }

    for account in accounts_to_try:
        print(f"\n--- Checking Account: {account['name']} ---")
        try:
            youtube = get_auth_service(account['id'], account['sec'], account['tok'])
            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: print(f"   -> Progress: {int(status.progress() * 100)}%")
                    
            vid_id = response['id']
            print(f"✅ SUCCESS! {account['name']} uploaded ID: {vid_id}")
            
            if os.path.exists(thumb_file):
                try:
                    youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(thumb_file)).execute()
                    print("   -> Thumbnail Attached!")
                except: print("   -> Thumbnail failed.")
            return True 

        except HttpError as e:
            err_msg = str(e)
            print(f"❌ API Error on {account['name']}: {err_msg}")
            if "quotaExceeded" in err_msg or "rateLimitExceeded" in err_msg: continue
            else: return False
        except Exception as e:
            print(f"❌ System Error: {e}")
            continue

    return False

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    config_channels = load_text_list(CONFIG_FILE)
    uploaded_ids = load_text_list(UPLOADED_FILE)
    all_queues = load_json(QUEUES_FILE, {})
    state = load_json(STATE_FILE, {"last_index": -1})

    # 1. Update scanning queue
    if config_channels:
        all_queues = update_channel_queues(config_channels, uploaded_ids, all_queues)
        save_json(QUEUES_FILE, all_queues)

    # 2. Try to process one video
    while True:
        target_url, channel_owner, new_index = get_next_video_to_upload(all_queues, state['last_index'])
        
        if not target_url:
            print("\n💤 All queues are empty.")
            break

        vid_id = extract_video_id(target_url)
        if vid_id in uploaded_ids:
            print(f"♻️ Skipping {vid_id}: Already uploaded.")
            all_queues[channel_owner].pop(0)
            save_json(QUEUES_FILE, all_queues)
            state['last_index'] = new_index
            continue 
        
        v_file, t_file, title, desc, orig_id = download_video(target_url)
        
        if v_file and orig_id:
            if attempt_upload(v_file, t_file, title, desc):
                # Clean up after successful upload
                all_queues[channel_owner].pop(0)
                uploaded_ids.append(orig_id)
                state['last_index'] = new_index
                
                save_json(QUEUES_FILE, all_queues)
                save_text_list(UPLOADED_FILE, uploaded_ids)
                save_json(STATE_FILE, state)
                print(f"🎉 TASK COMPLETE.")
            else:
                print("❌ Upload failed. Video kept in queue.")
        else:
            print("❌ Download failed. Video kept in queue.")
            
        break # Process 1 video per run
