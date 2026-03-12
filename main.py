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

# --- SETTINGS ---
CATEGORY_ID = "24" # Entertainment
LANGUAGE = "en"    # English
MADE_FOR_KIDS = False

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
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None

def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
    return build('youtube', 'v3', credentials=creds)

# ==========================================
# 1. SCANNER
# ==========================================
def update_channel_queues(config_channels, uploaded_ids, all_queues):
    for channel in config_channels:
        ydl_opts = {
            'extract_flat': True, 
            'quiet': True,
            # We try scanning WITHOUT cookies first to avoid the "Reload" trigger
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'tv'],
                }
            }
        }
        if channel not in all_queues:
            all_queues[channel] = []
        else:
            ydl_opts['playlistend'] = 15
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                if 'entries' in info:
                    entries = list(info['entries']) 
                    fresh = [f"https://www.youtube.com/watch?v={e['id']}" for e in entries if e['id'] and e['id'] not in uploaded_ids and f"https://www.youtube.com/watch?v={e['id']}" not in all_queues[channel]]
                    if fresh:
                        all_queues[channel] = fresh + all_queues[channel]
                        print(f"Added {len(fresh)} videos to {channel}")
        except Exception as e: 
            print(f"Error scanning: {e}")
            # Fallback to cookies if anonymous scan fails
            print("Trying scan with cookies...")
            ydl_opts['cookiefile'] = COOKIES_FILE
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel, download=False)
                    # ... (rest of scan logic)
            except: pass
    return all_queues
def attempt_upload(video_file, thumb_file, title, description):
    api_accounts = [
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]
    
    # ADVANCED METADATA BODY
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

    for account in api_accounts:
        if not account['id']: continue
        try:
            youtube = get_auth_service(account['id'], account['sec'], account['tok'])
            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: print(f"{account['name']} Progress: {int(status.progress() * 100)}%")
            
            vid_id = response['id']
            if os.path.exists(thumb_file):
                youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(thumb_file)).execute()
            return True 
        except HttpError as e:
            try: reason = json.loads(e.content.decode())['error']['errors'][0]['reason']
            except: reason = "unknown"
            if reason in ["quotaExceeded", "dailyLimitExceeded", "invalid_grant"]: continue
            elif reason == "uploadLimitExceeded": return False 
            elif e.resp.status == 409: return True
        except Exception: continue
    return False

# ==========================================
# 3. DOWNLOADER (RELOAD FIX)
# ==========================================
# ==========================================
# 3. DOWNLOADER (RELOAD ERROR BYPASS)
# ==========================================
def download_video(url):
    print(f"Downloading: {url}")
    
    # STRATEGY: Try iOS/Android WITHOUT cookies first. 
    # This is the most successful way to bypass "The page needs to be reloaded" in 2026.
    
    attempt_configs = [
        { # Attempt 1: Mobile clients (No Cookies) - Best for bypass
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'extractor_args': {'youtube': {'player_client': ['ios', 'android']}},
            'outtmpl': 'downloaded_video.%(ext)s',
            'writethumbnail': True,
            'postprocessors': [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
            'quiet': False
        },
        { # Attempt 2: TV client (With Cookies) - Fallback for age-restricted
            'cookiefile': COOKIES_FILE,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'extractor_args': {'youtube': {'player_client': ['tv']}},
            'outtmpl': 'downloaded_video.%(ext)s',
            'writethumbnail': True,
            'postprocessors': [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
            'quiet': False
        }
    ]

    for i, config in enumerate(attempt_configs):
        try:
            print(f"   -> Attempt {i+1}...")
            with yt_dlp.YoutubeDL(config) as ydl:
                info = ydl.extract_info(url, download=True)
                return "downloaded_video.mp4", "downloaded_video.jpg", info.get('title'), info.get('description'), info.get('id')
        except Exception as e:
            err_msg = str(e)
            if "reloaded" in err_msg:
                print(f"   ⚠️ Attempt {i+1} triggered reload error. Trying next config...")
                continue
            else:
                print(f"   ❌ Attempt {i+1} failed: {err_msg}")
                continue
                
    return None, None, None, None, None
