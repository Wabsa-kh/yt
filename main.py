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

# ==========================================
# 1. PER-CHANNEL SCANNER (UNLIMITED)
# ==========================================
def update_channel_queues(channels, uploaded_ids, all_queues):
    for channel in channels:
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'extractor_args': {'youtube': {'player_client': ['tv']}}
        }

        # Initialize list for this channel if missing
        if channel not in all_queues:
            all_queues[channel] = []
            print(f"\n🚨 NEW CHANNEL FOUND: {channel}")
            print("   -> Scanning ENTIRE channel history (No Limit)...")
            # We removed the 'playlistend' limit here. It gets EVERYTHING.
        else:
            print(f"\n⚡ KNOWN CHANNEL: {channel}")
            print("   -> Checking for new updates (Top 15)...")
            ydl_opts['playlistend'] = 15 # Keep this small just for speed on existing channels

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                if 'entries' in info:
                    # yt-dlp returns entries as [Newest, ..., Oldest]
                    entries = list(info['entries']) 
                    
                    fresh_videos_for_this_run = []
                    
                    for entry in entries:
                        vid_id = entry.get('id')
                        vid_url = entry.get('url') or f"https://www.youtube.com/watch?v={vid_id}"
                        
                        # Check global uploaded list AND specific channel queue
                        if vid_id and vid_id not in uploaded_ids and vid_url not in all_queues[channel]:
                            fresh_videos_for_this_run.append(vid_url)
                    
                    if fresh_videos_for_this_run:
                        # Add the whole chunk [Newest...Oldest] to the FRONT
                        all_queues[channel] = fresh_videos_for_this_run + all_queues[channel]
                        print(f"   -> Added {len(fresh_videos_for_this_run)} videos to queue.")
                    else:
                        print(f"   -> No new videos found.")

        except Exception as e:
            print(f"   ❌ Error scanning {channel}: {e}")

    return all_queues

# ==========================================
# 2. ROUND-ROBIN SELECTOR
# ==========================================
def get_next_video(channels, all_queues, last_index):
    total_channels = len(channels)
    if total_channels == 0: return None, None, last_index

    # Start checking the NEXT channel in line
    start_index = (last_index + 1) % total_channels
    
    for i in range(total_channels):
        current_index = (start_index + i) % total_channels
        channel_url = channels[current_index]
        
        # Check if this channel exists in our JSON and has videos waiting
        if channel_url in all_queues and len(all_queues[channel_url]) > 0:
            video_url = all_queues[channel_url][0] # Grab the first one (Newest)
            print(f"\n🎯 ROUND-ROBIN: Picking from {channel_url}")
            return video_url, channel_url, current_index

    return None, None, last_index

# ==========================================
# 3. DOWNLOADER
# ==========================================
def download_video(url):
    print(f"\n--- DOWNLOADING: {url} ---")
    opts = {
        'cookiefile': COOKIES_FILE,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'extractor_args': {'youtube': {'player_client': ['tv']}},
        'outtmpl': 'downloaded_video.%(ext)s',
        'writethumbnail': True,
        'postprocessors': [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
        'quiet': False
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return "downloaded_video.mp4", "downloaded_video.jpg", info.get('title'), info.get('description'), info.get('id')
    except Exception as e:
        print(f"Download Failed: {e}")
        return None, None, None, None, None

# ==========================================
# 4. MULTI-API UPLOADER
# ==========================================
def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
    return build('youtube', 'v3', credentials=creds)

def attempt_upload(video_file, thumb_file, title, description):
    api_accounts = [
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]
    valid_accounts = [acc for acc in api_accounts if acc['id'] and acc['sec'] and acc['tok']]
    
    request_body = {
        'snippet': {'title': title[:100], 'description': description[:5000], 'categoryId': '22'},
        'status': {'privacyStatus': 'public'}
    }

    for account in valid_accounts:
        print(f"\n[ Trying API Account: {account['name']} ]")
        try:
            youtube = get_auth_service(account['id'], account['sec'], account['tok'])
            media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=request_body, media_body=media)
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: print(f"Uploaded {int(status.progress() * 100)}%")
                    
            new_video_id = response['id']
            print(f"✅ Upload Complete! New ID: {new_video_id}")
            if os.path.exists(thumb_file):
                try: youtube.thumbnails().set(videoId=new_video_id, media_body=MediaFileUpload(thumb_file)).execute()
                except: pass
            return True 

        except HttpError as e:
            if "quotaExceeded" in str(e) or "uploadLimitExceeded" in str(e):
                print(f"⚠️ Account {account['name']} limit reached! Switching...")
                continue
            elif "409" in str(e): return True
            else: break
        except Exception: break
    return False

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    channels = load_text_list(CONFIG_FILE)
    uploaded_ids = load_text_list(UPLOADED_FILE)
    all_queues = load_json(QUEUES_FILE, {})
    state = load_json(STATE_FILE, {"last_index": -1})

    if not channels:
        print("Config file is empty.")
        exit(0)

    # 1. Update Queues (Correct Order)
    all_queues = update_channel_queues(channels, uploaded_ids, all_queues)
    save_json(QUEUES_FILE, all_queues)

    # 2. Pick Next Video (Round Robin)
    target_url, channel_owner, new_index = get_next_video(channels, all_queues, state['last_index'])

    if not target_url:
        print("\n💤 All queues are empty. Nothing to upload.")
        exit(0)

    # 3. Download & Upload
    vid_file, thumb_file, title, desc, original_id = download_video(target_url)
    
    if vid_file and original_id:
        success = attempt_upload(vid_file, thumb_file, title, desc)
        
        if success:
            all_queues[channel_owner].pop(0) # Removes the video we just uploaded (The Newest one)
            uploaded_ids.append(original_id)
            state['last_index'] = new_index

            save_json(QUEUES_FILE, all_queues)
            save_text_list(UPLOADED_FILE, uploaded_ids)
            save_json(STATE_FILE, state)
            
            print(f"\n🎉 SUCCESS! Uploaded video from {channel_owner}.")
        else:
            print("\n❌ Upload failed.")
    else:
        print("\n❌ Download failed.")
        all_queues[channel_owner].pop(0)
        save_json(QUEUES_FILE, all_queues)
