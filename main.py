import os
import yt_dlp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# --- FILE PATHS ---
CONFIG_FILE = "config.txt"
QUEUE_FILE = "queue.txt"
UPLOADED_FILE = "uploaded.txt"
SCANNED_CHANNELS_FILE = "scanned_channels.txt"
COOKIES_FILE = "cookies.txt"

def load_text_list(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_text_list(filepath, data_list):
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data_list:
            f.write(f"{item}\n")

# ==========================================
# 1. SMART SCANNER (LATEST TO OLDEST)
# ==========================================
def scan_channels_for_new_videos(channels, uploaded_ids, current_queue, scanned_channels):
    new_videos = []
    updated_scanned_channels = list(scanned_channels)

    for channel in channels:
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'extractor_args': {'youtube': {'player_client': ['tv']}}
        }
        
        # CHECK THE REGISTRY
        if channel not in scanned_channels:
            print(f"\n🚨 NEW CHANNEL DETECTED: {channel}")
            print("Scanning channel history (Latest to Oldest)...")
            updated_scanned_channels.append(channel)
        else:
            print(f"\n⚡ Known channel: {channel}. Scanning the 15 newest videos...")
            ydl_opts['playlistend'] = 15 
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                
                if 'entries' in info:
                    entries = list(info['entries'])
                    
                    # --- CRITICAL CHANGE HERE ---
                    # We REMOVED entries.reverse(). 
                    # YouTube sends data as [Newest, ..., Oldest].
                    # By keeping it as is, we process the Newest video first!
                    
                    for entry in entries:
                        vid_id = entry.get('id')
                        vid_url = entry.get('url') or f"https://www.youtube.com/watch?v={vid_id}"
                        
                        # Add if not uploaded and not already in queue
                        if vid_id and vid_id not in uploaded_ids and vid_url not in current_queue and vid_url not in new_videos:
                            # We append to the list. Since 'entries' is Newest->Oldest,
                            # new_videos[0] will be the absolute newest video.
                            new_videos.append(vid_url)
                            
        except Exception as e:
            print(f"Error scanning {channel}: {e}")
            
    return new_videos, updated_scanned_channels

# ==========================================
# 2. DOWNLOADER
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
            original_id = info.get('id')
            title = info.get('title', 'Cloned Video')
            description = info.get('description', '')
            
            return "downloaded_video.mp4", "downloaded_video.jpg", title, description, original_id
    except Exception as e:
        print(f"Download Failed: {e}")
        return None, None, None, None, None

# ==========================================
# 3. MULTI-API UPLOADER
# ==========================================
def get_auth_service(client_id, client_secret, refresh_token):
    creds = Credentials(
        token=None, refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret
    )
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
                if status:
                    print(f"Uploaded {int(status.progress() * 100)}%")
                    
            new_video_id = response['id']
            print(f"✅ Upload Complete! New ID: {new_video_id}")
            
            if os.path.exists(thumb_file):
                try:
                    youtube.thumbnails().set(videoId=new_video_id, media_body=MediaFileUpload(thumb_file)).execute()
                    print("✅ Thumbnail Uploaded!")
                except Exception:
                    print("⚠️ Thumbnail failed.")
                    
            return True 

        except HttpError as e:
            if "quotaExceeded" in str(e):
                print(f"⚠️ Account {account['name']} is out of quota! Switching to next...")
                continue
            elif "uploadLimitExceeded" in str(e):
                print(f"⚠️ Account {account['name']} hit daily video limit! Switching to next...")
                continue
            elif "409" in str(e):
                print("⚠️ Video is a duplicate! Treating as success to clear from queue.")
                return True
            else:
                print(f"❌ Unrecoverable API Error on {account['name']}: {e}")
                break
        except Exception as e:
            print(f"❌ Local Error: {e}")
            break

    print("🚨 All API accounts failed or ran out of quota.")
    return False

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    channels = load_text_list(CONFIG_FILE)
    uploaded_ids = load_text_list(UPLOADED_FILE)
    queue = load_text_list(QUEUE_FILE)
    scanned_channels = load_text_list(SCANNED_CHANNELS_FILE)

    if not channels:
        print("Config file is empty.")
        exit(0)

    # 1. Find new videos
    new_vids, updated_scanned_channels = scan_channels_for_new_videos(channels, uploaded_ids, queue, scanned_channels)
    
    save_text_list(SCANNED_CHANNELS_FILE, updated_scanned_channels)

    if new_vids:
        print(f"\nAdding {len(new_vids)} new videos to the front of the queue.")
        # IMPORTANT: 'new_vids' contains [Newest, 2nd Newest, ...].
        # We put them at the start of the queue.
        # So queue[0] becomes the absolute newest video.
        queue = new_vids + queue 
        save_text_list(QUEUE_FILE, queue)

    # 2. Process the Queue
    if not queue:
        print("\nQueue is empty.")
        exit(0)

    target_video_url = queue[0] 
    
    vid_file, thumb_file, title, desc, original_id = download_video(target_video_url)
    
    if vid_file and original_id:
        success = attempt_upload(vid_file, thumb_file, title, desc)
        
        if success:
            queue.pop(0)
            uploaded_ids.append(original_id)
            save_text_list(QUEUE_FILE, queue)
            save_text_list(UPLOADED_FILE, uploaded_ids)
            print(f"\n🎉 SYSTEM FINISHED! Video {original_id} marked as uploaded.")
        else:
            print("\n❌ Upload failed. Video remains in queue.")
    else:
        print("\n❌ Download failed. Removed from queue.")
        queue.pop(0)
        save_text_list(QUEUE_FILE, queue)
