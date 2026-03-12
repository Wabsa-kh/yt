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
CATEGORY_ID = "24" # Entertainment Category
LANGUAGE = "en"    # English for Video and Thumbnail
MADE_FOR_KIDS = False # Not made for kids

def load_text_list(filepath):
    if not os.path.exists(filepath): return[]
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
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
    return build('youtube', 'v3', credentials=creds)

# ==========================================
# 1. SMART SCANNER (Bypass Reload Error)
# ==========================================
def update_channel_queues(config_channels, uploaded_ids, all_queues):
    for channel in config_channels:
        # STRATEGY 1: Attempt scanning WITHOUT cookies first to avoid Reload triggers
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'tv']}}
        }
        
        if channel not in all_queues:
            all_queues[channel] =[]
            print(f"\n🚨 NEW CHANNEL: {channel} -> Scanning ENTIRE history.")
            # No playlistend limit, gets everything
        else:
            print(f"\n⚡ SCANNING: {channel} -> Checking newest videos.")
            ydl_opts['playlistend'] = 15
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                if 'entries' in info:
                    entries = list(info['entries']) 
                    fresh = [f"https://www.youtube.com/watch?v={e['id']}" for e in entries if e['id'] and e['id'] not in uploaded_ids and f"https://www.youtube.com/watch?v={e['id']}" not in all_queues[channel]]
                    if fresh:
                        all_queues[channel] = fresh + all_queues[channel]
                        print(f"   -> Added {len(fresh)} new videos to queue.")
                    else:
                        print("   -> No new videos found.")
        except Exception as e:
            print(f"   ❌ Anonymous scan failed: {e}. Trying with cookies...")
            
            # STRATEGY 2: Fallback to cookies if anonymous fails
            ydl_opts['cookiefile'] = COOKIES_FILE
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel, download=False)
                    if 'entries' in info:
                        entries = list(info['entries']) 
                        fresh =[f"https://www.youtube.com/watch?v={e['id']}" for e in entries if e['id'] and e['id'] not in uploaded_ids and f"https://www.youtube.com/watch?v={e['id']}" not in all_queues[channel]]
                        if fresh:
                            all_queues[channel] = fresh + all_queues[channel]
                            print(f"   -> Added {len(fresh)} new videos to queue.")
            except Exception as e2:
                print(f"   ❌ Cookie scan also failed: {e2}")
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
# 3. DOWNLOADER (DOUBLE-STRATEGY FIX)
# ==========================================
def download_video(url):
    print(f"\n--- DOWNLOADING: {url} ---")
    
    attempt_configs =[
        { # Attempt 1: Anonymous Mobile Clients (Bypasses Reload Error)
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'extractor_args': {'youtube': {'player_client': ['ios', 'android']}},
            'outtmpl': 'downloaded_video.%(ext)s',
            'writethumbnail': True,
            'postprocessors':[{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
            'quiet': False
        },
        { # Attempt 2: TV Client with Cookies (Fallback for Age-Restricted/Private)
            'cookiefile': COOKIES_FILE,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'extractor_args': {'youtube': {'player_client': ['tv']}},
            'outtmpl': 'downloaded_video.%(ext)s',
            'writethumbnail': True,
            'postprocessors':[{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
            'quiet': False
        }
    ]

    for i, config in enumerate(attempt_configs):
        print(f"   -> Starting Download Strategy {i+1}...")
        try:
            with yt_dlp.YoutubeDL(config) as ydl:
                info = ydl.extract_info(url, download=True)
                return "downloaded_video.mp4", "downloaded_video.jpg", info.get('title', 'Video'), info.get('description', ''), info.get('id')
        except Exception as e:
            err_msg = str(e)
            print(f"   ⚠️ Strategy {i+1} failed: {err_msg}")
            if "reloaded" in err_msg or "Sign in" in err_msg or "unavailable" in err_msg:
                continue # Try next strategy
            else:
                pass
    
    return None, None, None, None, None

# ==========================================
# 4. UPLOADER (WITH ADVANCED METADATA)
# ==========================================
def attempt_upload(video_file, thumb_file, title, description):
    api_accounts =[
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]
    
    force_acc = os.environ.get('FORCE_ACCOUNT')
    if force_acc:
        accounts_to_try = [acc for acc in api_accounts if acc['name'] == force_acc]
    else:
        accounts_to_try =[acc for acc in api_accounts if acc['id'] and acc['sec'] and acc['tok']]

    # ADVANCED METADATA APPLIED HERE
    body = {
        'snippet': {
            'title': title[:100],
            'description': description[:5000],
            'categoryId': CATEGORY_ID,
            'defaultLanguage': LANGUAGE,
            'defaultAudioLanguage': LANGUAGE
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': MADE_FOR_KIDS,
            'license': 'youtube'
        }
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

            if reason in ["quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "invalid_grant"]:
                print(f"⚠️ Switching to next account...")
                continue
            elif reason == "uploadLimitExceeded":
                print("🛑 STOP: Your YouTube CHANNEL has hit its limit. Wait 24 hours.")
                return False 
            elif e.resp.status == 409:
                print("♻️ Video already on channel. Clearing queue.")
                return True
            else:
                continue
        except Exception as e:
            print(f"❌ System Error on {account['name']}: {e}")
            continue

    print("\n🚨 ALL ACCOUNTS FAILED.")
    return False

# ==========================================
# 5. MAIN EXECUTION
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

    # 2. Infinite Selection Loop
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
            state['last_index'] = new_index
            continue 
        
        print(f"\n🎯 SELECTED: {target_url} from {channel_owner}")
        
        # 3. Download & Upload
        v_file, t_file, title, desc, orig_id = download_video(target_url)
        
        if v_file and orig_id:
            if attempt_upload(v_file, t_file, title, desc):
                all_queues[channel_owner].pop(0)
                uploaded_ids.append(orig_id)
                state['last_index'] = new_index
                
                save_json(QUEUES_FILE, all_queues)
                save_text_list(UPLOADED_FILE, uploaded_ids)
                save_json(STATE_FILE, state)
                print(f"🎉 SYSTEM FINISHED.")
            else:
                print("❌ Upload failed.")
        else:
            print("❌ Download failed. Removing from queue to prevent infinite loop.")
            all_queues[channel_owner].pop(0)
            save_json(QUEUES_FILE, all_queues)
            
        break # Exit the loop after trying 1 video
