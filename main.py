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
# 1. SMART SCANNER
# ==========================================
def update_channel_queues(config_channels, uploaded_ids, all_queues):
    for channel in config_channels:
        ydl_opts = {
            'extract_flat': 'in_playlist',
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
                
                def get_video_ids(data):
                    vids = []
                    if not data: return vids
                    if 'entries' in data:
                        for e in data['entries']: vids.extend(get_video_ids(e))
                    else:
                        v_id = data.get('id')
                        if v_id and isinstance(v_id, str) and len(v_id) == 11:
                            vids.append(v_id)
                    return vids

                video_ids = get_video_ids(info)
                fresh = []
                for v_id in video_ids:
                    v_url = f"https://www.youtube.com/watch?v={v_id}"
                    if v_id not in uploaded_ids and v_url not in all_queues[channel] and v_url not in fresh:
                        fresh.append(v_url)
                
                if fresh:
                    all_queues[channel] = fresh + all_queues[channel]
                    print(f"   -> Added {len(fresh)} new valid videos.")
        except Exception as e:
            print(f"   ❌ Scan failed for {channel}: {e}")
            
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
# 3. DOWNLOADER (WITH ERROR DETECTION)
# ==========================================
def download_video(url):
    print(f"\n--- DOWNLOADING: {url} ---")
    
    last_error = ""
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
            'quiet': True,
            'overwrites': True
        }
        base_opts.update(extra_opts)

        try:
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return "SUCCESS", ("downloaded_video.mp4", "downloaded_video.jpg", 
                        info.get('title', 'Video'), info.get('description', ''), info.get('id'))
        except Exception as e:
            last_error = str(e).lower()
            print(f"   ⚠️ Strategy {i+1} failed: {last_error[:100]}...")
            continue
    
    # Analyze why it failed after all strategies
    if any(x in last_error for x in ["unavailable", "private", "deleted", "removed", "copyright"]):
        return "PERMANENT_FAIL", None
    else:
        return "TRANSIENT_FAIL", None

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
        'snippet': {'title': title[:100], 'description': description[:5000], 'categoryId': CATEGORY_ID, 'defaultLanguage': LANGUAGE},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': MADE_FOR_KIDS}
    }

    for account in accounts_to_try:
        print(f"   -> Trying Account: {account['name']}...")
        try:
            youtube = get_auth_service(account['id'], account['sec'], account['tok'])
            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            
            response = None
            while response is None:
                status, response = request.next_chunk()
            
            vid_id = response['id']
            print(f"✅ SUCCESS! Uploaded ID: {vid_id}")
            if os.path.exists(thumb_file):
                try: youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(thumb_file)).execute()
                except: pass
            return True 
        except HttpError as e:
            if "quotaExceeded" in str(e): continue
            return False
        except: continue
    return False

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    config_channels = load_text_list(CONFIG_FILE)
    uploaded_ids = load_text_list(UPLOADED_FILE)
    all_queues = load_json(QUEUES_FILE, {})
    state = load_json(STATE_FILE, {"last_index": -1})

    if config_channels:
        all_queues = update_channel_queues(config_channels, uploaded_ids, all_queues)
        save_json(QUEUES_FILE, all_queues)

    # Loop until we successfully upload ONE video or run out of things to try
    while True:
        target_url, channel_owner, new_index = get_next_video_to_upload(all_queues, state['last_index'])
        
        if not target_url:
            print("\n💤 All queues are empty.")
            break

        vid_id = extract_video_id(target_url)
        if vid_id in uploaded_ids:
            all_queues[channel_owner].pop(0)
            save_json(QUEUES_FILE, all_queues)
            continue 
        
        status, data = download_video(target_url)
        
        if status == "SUCCESS":
            v_file, t_file, title, desc, orig_id = data
            if attempt_upload(v_file, t_file, title, desc):
                # SUCCESS: Remove from queue and mark as uploaded
                all_queues[channel_owner].pop(0)
                uploaded_ids.append(orig_id)
                state['last_index'] = new_index
                save_json(QUEUES_FILE, all_queues)
                save_text_list(UPLOADED_FILE, uploaded_ids)
                save_json(STATE_FILE, state)
                print("🎉 TASK COMPLETE.")
                break # Exit after one successful upload
            else:
                # UPLOAD FAIL: Keep at top but try next channel next time
                print("❌ Upload failed. Video kept in queue for next run.")
                state['last_index'] = new_index
                save_json(STATE_FILE, state)
                break 

        elif status == "PERMANENT_FAIL":
            # REMOVE: Video is gone from YouTube
            print(f"🗑️ Video unavailable/private. Removing from queue: {target_url}")
            all_queues[channel_owner].pop(0)
            save_json(QUEUES_FILE, all_queues)
            # Don't break, continue loop to try the next video
            continue

        elif status == "TRANSIENT_FAIL":
            # MOVE TO BOTTOM: Network error or temporary block
            print(f"🔄 Download error (Transient). Moving to bottom of {channel_owner} queue.")
            url_to_move = all_queues[channel_owner].pop(0)
            all_queues[channel_owner].append(url_to_move)
            save_json(QUEUES_FILE, all_queues)
            state['last_index'] = new_index
            save_json(STATE_FILE, state)
            # Don't break, continue loop to try the next video
            continue
