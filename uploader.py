import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def get_authenticated_service():
    """Builds YouTube credentials directly from GitHub Secrets."""
    client_id = os.environ.get('YT_CLIENT_ID')
    client_secret = os.environ.get('YT_CLIENT_SECRET')
    refresh_token = os.environ.get('YT_REFRESH_TOKEN')

    if not all([client_id, client_secret, refresh_token]):
        print("Error: Missing one or more YT_ secrets in environment variables!")
        return None

    # Construct the credentials object directly
    creds = Credentials(
        token=None, 
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
            'privacyStatus': 'private' # Keeps it private during testing
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
        # Look specifically for the file you uploaded to the repo
        target_video = "video.mp4"
        
        if os.path.exists(target_video):
            print(f"Found video to upload: {target_video}")
            upload_video(
                youtube_service, 
                video_file=target_video, 
                title="GitHub Action API Test", 
                description="This video was uploaded directly from my GitHub repository using the YouTube API!"
            )
        else:
            print(f"Error: Could not find '{target_video}'. Did you upload it to the repository?")
