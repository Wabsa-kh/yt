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
COOKIES_FILE = "cookies.txt"

def load_text_list(filepath):
    """Loads a text file into a list of strings."""
    if not os.path.exists(filepath):
        return[]
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_text_list(filepath, data_list):
    """Saves a list of strings to a text file."""
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data_list:
            f.write(f"{item}\n")

# ==========================================
# 1. SMART SCANNER & QUEUE MANAGEMENT
# ==========================================
def scan_channels_for_new_videos(channels, uploaded_ids, current_queue):
    """
    If first run: Scans entire channel.
    If normal run: Scans only top 15 videos to find new daily uploads.
    """
    new_videos =[]
    
    # DETECT FIRST RUN: Are both files completely empty?
    is_first_run = (len(uploaded_ids) == 0 and len(current_queue) == 0)
    
    if is_first_run:
        print("🚨 FIRST RUN DETECTED! Scanning entire channel history... (This may take a minute)")
    else:
        print("⚡ Normal run detected. Scanning the 15 newest videos for recent uploads...")

    for channel in channels:
        print(f"\nScanning channel: {channel}")
        
        ydl_opts = {
            'extract_flat': True, # Only gets URLs and IDs, doesn't download video yet
            'quiet': True,
            'cookiefile': COOKIES_FILE,
            'extractor_args': {'youtube': {'player_client': ['tv']}}
        }
        
        # If it is NOT the first run, we limit the search to the newest 15 videos 
        # to prevent GitHub from getting IP banned by YouTube for spamming.
        if not is_first_run:
            ydl_opts['playlistend'] = 15 
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel, download=False)
                
                if 'entries' in info:
                    # We reverse the entries so the oldest of the "new" videos gets added first,
                    # keeping perfect chronological order!
                    entries = list(info['entries'])
                    entries.reverse() 
                    
                    for entry in entries:
                        vid_id = entry.get('id')
                        vid_url = entry.get('url') or f"https://www.youtube.com/watch?v={vid_id}"
                        
                        # Is it truly a new video we haven't seen before?
                        if vid_id and vid_id not in uploaded_ids and vid_url not in current_queue:
                            print(f"✨ Found new video: {vid_id}")
                            new_videos.append(vid_url)
        except Exception as e:
            print(f"Error scanning {channel}: {e}")
            
    return new_videos

# ==========================================
# 2. DOWNLOADER
# ==========================================
def download_video(url):
    print(f"\n--- DOWNLOADING: {url} ---")
    opts = {
        'cookiefile': COOKIES_FILE,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'extractor_args': {'youtube': {'player_client':['tv']}},
        'outtmpl': 'downloaded_video.%(ext)s',
        'writethumbnail': True,
        'postprocessors':[{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'}],
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
    """Tries to upload using C1, then C2, then C3 if quota is exceeded."""
    
    api_accounts =[
        {'id': os.environ.get('C1_CLIENT_ID'), 'sec': os.environ.get('C1_CLIENT_SECRET'), 'tok': os.environ.get('C1_REFRESH_TOKEN'), 'name': 'C1'},
        {'id': os.environ.get('C2_CLIENT_ID'), 'sec': os.environ.get('C2_CLIENT_SECRET'), 'tok': os.environ.get('C2_REFRESH_TOKEN'), 'name': 'C2'},
        {'id': os.environ.get('C3_CLIENT_ID'), 'sec': os.environ.get('C3_CLIENT_SECRET'), 'tok': os.environ.get('C3_REFRESH_TOKEN'), 'name': 'C3'}
    ]
    valid_accounts =[acc for acc in api_accounts if acc['id'] and acc['sec'] and acc['tok']]
    
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
                    print("⚠️ Thumbnail failed (Account might need phone verification).")
                    
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

    if not channels:
        print("Config file is empty. Add channel URLs to config.txt.")
        exit(0)

    # 1. Find new videos
    new_vids = scan_channels_for_new_videos(channels, uploaded_ids, queue)
    
    if new_vids:
        print(f"\nAdding {len(new_vids)} new videos to the front of the queue.")
        # We put new videos at the FRONT of the queue so the newest uploads are cloned immediately!
        queue = new_vids + queue 
        save_text_list(QUEUE_FILE, queue)

    # 2. Process the Queue
    if not queue:
        print("\nQueue is empty. Nothing to do! See you in 4 hours.")
        exit(0)

    target_video_url = queue[0] # Grab the first video in line
    
    vid_file, thumb_file, title, desc, original_id = download_video(target_video_url)
    
    if vid_file and original_id:
        success = attempt_upload(vid_file, thumb_file, title, desc)
        
        if success:
            # 3. Cleanup! Remove from queue, add to uploaded, and save!
            queue.pop(0)
            uploaded_ids.append(original_id)
            
            save_text_list(QUEUE_FILE, queue)
            save_text_list(UPLOADED_FILE, uploaded_ids)
            print(f"\n🎉 SYSTEM FINISHED! Video {original_id} marked as uploaded.")
        else:
            print("\n❌ Upload failed. Video will remain at the top of the queue for the next run.")
    else:
        print("\n❌ Download failed. Removing from queue so we don't get stuck.")
        queue.pop(0)
        save_text_list(QUEUE_FILE, queue)
