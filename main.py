import os
import json
import yt_dlp
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
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
    return build('youtube', 'v3', credentials=creds)

# ==========================================
# MULTI-API UPLOADER (WITH TEST FORCE)
# ==========================================
def attempt_upload(video_file, thumb_file, title, description):
    # 1. Setup the list of accounts
    api_accounts = [
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]

    # 2. Check if we are forcing a specific account for testing
    force_acc = os.environ.get('FORCE_ACCOUNT') # e.g., "C2" or "C3"
    
    if force_acc:
        print(f"\n🧪 TEST MODE: Forcing upload through {force_acc} only!")
        accounts_to_try = [acc for acc in api_accounts if acc['name'] == force_acc]
        if not accounts_to_try:
            print(f"❌ Error: Forced account '{force_acc}' not found in secrets.")
            return False
    else:
        # Normal Mode: Use all valid accounts
        accounts_to_try = [acc for acc in api_accounts if acc['id'] and acc['sec'] and acc['tok']]

    request_body = {
        'snippet': {'title': title[:100], 'description': description[:5000], 'categoryId': '22'},
        'status': {'privacyStatus': 'public'}
    }

    for account in accounts_to_try:
        print(f"\n--- Trying Account {account['name']} ---")
        try:
            youtube = get_auth_service(account['id'], account['sec'], account['tok'])
            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=request_body, media_body=media)
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: print(f"Progress: {int(status.progress() * 100)}%")
                    
            vid_id = response['id']
            print(f"✅ SUCCESS! Video ID: {vid_id}")
            if os.path.exists(thumb_file):
                try: youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(thumb_file)).execute()
                except: pass
            return True 

        except HttpError as e:
            try:
                err_content = json.loads(e.content.decode())
                reason = err_content.get('error', {}).get('errors', [{}])[0].get('reason', 'Unknown Reason')
                message = err_content.get('error', {}).get('message', 'No message')
                print(f"❌ API Error on {account['name']}: {reason} - {message}")
            except:
                print(f"❌ API Error on {account['name']}: {str(e)}")

            if force_acc:
                # If we are in test mode, don't try other accounts, just stop here
                return False
            continue # In normal mode, try next
        except Exception as e:
            print(f"❌ System Error on {account['name']}: {e}")
            continue

    return False

# ==========================================
# 1. PER-CHANNEL SCANNER & OTHER FUNCTIONS
# ==========================================
def update_channel_queues(channels, uploaded_ids, all_queues):
    for channel in channels:
        ydl_opts = {
            'extract_flat': True, 'quiet': True, 'cookiefile': COOKIES_FILE,
            'extractor_args': {'youtube': {'player_client': ['tv']}}
        }
        if channel not in all_queues:
            all_queues[channel] = []
            print(f"\n🚨 NEW CHANNEL: {channel}")
        else:
            print(f"\n⚡ CHECKING: {channel}")
            ydl_opts['playlistend'] = 15
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                if 'entries' in info:
                    entries = list(info['entries']) 
                    fresh = [f"https://www.youtube.com/watch?v={e['id']}" for e in entries if e['id'] and e['id'] not in uploaded_ids and f"https://www.youtube.com/watch?v={e['id']}" not in all_queues[channel]]
                    if fresh:
                        all_queues[channel] = fresh + all_queues[channel]
                        print(f"   -> Added {len(fresh)} videos.")
        except Exception as e: print(f"   ❌ Error scanning: {e}")
    return all_queues

def get_next_video(channels, all_queues, last_index):
    total = len(channels)
    if total == 0: return None, None, last_index
    start = (last_index + 1) % total
    for i in range(total):
        idx = (start + i) % total
        url = channels[idx]
        if url in all_queues and len(all_queues[url]) > 0:
            return all_queues[url][0], url, idx
    return None, None, last_index

def download_video(url):
    print(f"\n--- DOWNLOADING: {url} ---")
    opts = {
        'cookiefile': COOKIES_FILE, 'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'extractor_args': {'youtube': {'player_client': ['tv']}}, 'outtmpl': 'downloaded_video.%(ext)s',
        'writethumbnail': True, 'postprocessors': [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
        'quiet': False
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return "downloaded_video.mp4", "downloaded_video.jpg", info.get('title'), info.get('description'), info.get('id')
    except Exception as e:
        print(f"Download Failed: {e}"); return None, None, None, None, None

if __name__ == "__main__":
    channels = load_text_list(CONFIG_FILE)
    uploaded_ids = load_text_list(UPLOADED_FILE)
    all_queues = load_json(QUEUES_FILE, {})
    state = load_json(STATE_FILE, {"last_index": -1})
    if not channels: exit(0)

    all_queues = update_channel_queues(channels, uploaded_ids, all_queues)
    save_json(QUEUES_FILE, all_queues)

    target_url, channel_owner, new_index = get_next_video(channels, all_queues, state['last_index'])
    if target_url:
        v_file, t_file, title, desc, orig_id = download_video(target_url)
        if v_file and orig_id:
            if attempt_upload(v_file, t_file, title, desc):
                all_queues[channel_owner].pop(0)
                uploaded_ids.append(orig_id)
                state['last_index'] = new_index
                save_json(QUEUES_FILE, all_queues); save_text_list(UPLOADED_FILE, uploaded_ids); save_json(STATE_FILE, state)
