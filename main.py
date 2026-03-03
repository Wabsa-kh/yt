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

def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
    return build('youtube', 'v3', credentials=creds)

# ==========================================
# MULTI-API UPLOADER (THE "NEVER GIVE UP" VERSION)
# ==========================================
def attempt_upload(video_file, thumb_file, title, description):
    api_accounts = [
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]

    force_acc = os.environ.get('FORCE_ACCOUNT')
    if force_acc:
        print(f"\n🧪 TEST MODE: Only trying {force_acc}")
        accounts_to_try = [acc for acc in api_accounts if acc['name'] == force_acc]
    else:
        accounts_to_try = [acc for acc in api_accounts if acc['id'] and acc['sec'] and acc['tok']]

    request_body = {
        'snippet': {'title': title[:100], 'description': description[:5000], 'categoryId': '22'},
        'status': {'privacyStatus': 'public'}
    }

    for account in accounts_to_try:
        print(f"\n--- Checking Account: {account['name']} ---")
        try:
            # Generate a FRESH service for every attempt
            youtube = get_auth_service(account['id'], account['sec'], account['tok'])
            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=request_body, media_body=media)
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: print(f"   -> Upload Progress: {int(status.progress() * 100)}%")
                    
            vid_id = response['id']
            print(f"✅ SUCCESS! {account['name']} finished the upload. ID: {vid_id}")
            
            if os.path.exists(thumb_file):
                try:
                    youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(thumb_file)).execute()
                    print("   -> Thumbnail Attached!")
                except: print("   -> Thumbnail failed (Channel verification needed).")
            return True 

        except HttpError as e:
            try:
                err_content = json.loads(e.content.decode())
                reason = err_content['error']['errors'][0]['reason']
                message = err_content['error']['message']
            except:
                reason = "unknown"
                message = str(e)

            print(f"❌ API Error on {account['name']}: [{reason}] {message}")

            # CASE 1: Account Quota is dead -> MOVE TO NEXT ACCOUNT
            if reason in ["quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"]:
                print(f"⚠️ {account['name']} is out of API points. The system will now try the next account...")
                continue # This triggers the loop to move to C2 or C3
            
            # CASE 2: The Channel itself is blocked for today -> STOP ENTIRE PROGRAM
            elif reason == "uploadLimitExceeded":
                print("🛑 STOP: Your YouTube CHANNEL has hit its limit. Switching keys will not help.")
                return False 

            # CASE 3: Token is bad -> MOVE TO NEXT ACCOUNT
            elif reason == "invalid_grant":
                print(f"⚠️ {account['name']} has an expired token. Moving to next...")
                continue
            
            # CASE 4: Video already uploaded
            elif e.resp.status == 409:
                print("♻️ Video already on channel. Clearing queue.")
                return True
            
            else:
                print(f"⚠️ Unexpected error on {account['name']}, trying next just in case...")
                continue

        except Exception as e:
            print(f"❌ System Error on {account['name']}: {e}")
            continue

    print("\n🚨 ALL ACCOUNTS FAILED. No more keys to try.")
    return False

# ==========================================
# 1. SCANNER & HELPERS
# ==========================================
def update_channel_queues(channels, uploaded_ids, all_queues):
    for channel in channels:
        ydl_opts = {
            'extract_flat': True, 'quiet': True, 'cookiefile': COOKIES_FILE,
            'extractor_args': {'youtube': {'player_client': ['tv']}}
        }
        if channel not in all_queues:
            all_queues[channel] = []
            print(f"\n🚨 NEW: {channel}")
        else:
            print(f"\n⚡ SCAN: {channel}")
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
        except Exception as e: print(f"   ❌ Error: {e}")
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

    target_url, owner, new_index = get_next_video(channels, all_queues, state['last_index'])
    if target_url:
        v_file, t_file, title, desc, orig_id = download_video(target_url)
        if v_file and orig_id:
            if attempt_upload(v_file, t_file, title, desc):
                all_queues[owner].pop(0)
                uploaded_ids.append(orig_id)
                state['last_index'] = new_index
                save_json(QUEUES_FILE, all_queues); save_text_list(UPLOADED_FILE, uploaded_ids); save_json(STATE_FILE, state)
