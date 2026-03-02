import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def get_authenticated_service():
    """Builds YouTube credentials directly from GitHub Secrets."""
    client_id = os.environ.get('CLIENT_ID')
    client_secret = os.environ.get('CLIENT_SECRET')
    refresh_token = os.environ.get('REFRESH_TOKEN')

    if not all([client_id, client_secret, refresh_token]):
        print("Error: Missing one or more API secrets in environment variables!")
        return None

    # Construct the credentials object directly
    creds = Credentials(
        token=None, # We leave this None so it forces the refresh token to get a new access token
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )

    return build('youtube', 'v3', credentials=creds)

def upload_video(youtube, video_file, title, description):
    """Uploads the video to YouTube."""
    if not os.path.exists(video_file):
        print(f"Error: Could not find the video file {video_file}")
        return

    print(f"Preparing to upload: {video_file}")
    
    request_body = {
        'snippet': {
            'title': title,
            'description': description,
            'categoryId': '22' # 22 = People & Blogs
        },
        'status': {
            'privacyStatus': 'private' # Must be private for unverified apps
        }
    }
    
    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    )
    
    print("Uploading... (this may take a minute depending on file size)")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
            
    print(f"Upload Complete! Video ID: {response['id']}")

if __name__ == "__main__":
    print("Authenticating with YouTube API...")
    youtube_service = get_authenticated_service()
    
    if youtube_service:
        # We assume 'downloaded_video.mp4' or similar was created by yt-dlp.
        # Check what extension yt-dlp actually saved.
        # If yt-dlp saved it as .webm or .mkv, change this filename accordingly!
        
        # A simple trick to find the downloaded video file automatically:
        downloaded_files =[f for f in os.listdir('.') if f.startswith('downloaded_video')]
        
        if downloaded_files:
            video_file_name = downloaded_files[0]
            print(f"Found video to upload: {video_file_name}")
            
            upload_video(
                youtube_service, 
                video_file=video_file_name, 
                title="Automated Video Upload", 
                description="This video was downloaded and uploaded entirely via GitHub Actions!"
            )
        else:
            print("No downloaded video found to upload.")
