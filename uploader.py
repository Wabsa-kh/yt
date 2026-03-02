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

    creds = Credentials(
        token=None, 
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )

    return build('youtube', 'v3', credentials=creds)

def upload_video(youtube, video_file, title, description):
    """Uploads the video to YouTube and returns the Video ID."""
    print(f"Preparing to upload Video: {video_file}")
    
    request_body = {
        'snippet': {
            'title': title,
            'description': description,
            'categoryId': '22' # 22 = People & Blogs
        },
        'status': {
            'privacyStatus': 'public' # Changed to PUBLIC!
        }
    }
    
    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    )
    
    print("Uploading Video... (this may take a minute)")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
            
    video_id = response['id']
    print(f"Upload Complete! Video ID: {video_id}")
    return video_id

def upload_thumbnail(youtube, video_id, thumbnail_file):
    """Uploads a custom thumbnail for the given Video ID."""
    print(f"Preparing to upload Thumbnail: {thumbnail_file}")
    
    try:
        request = youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_file)
        )
        response = request.execute()
        print("Thumbnail uploaded successfully!")
    except Exception as e:
        print(f"Thumbnail upload failed: {e}")
        print("Note: Custom thumbnails require your YouTube channel to be verified with a phone number!")

if __name__ == "__main__":
    print("Authenticating with YouTube API...")
    youtube_service = get_authenticated_service()
    
    if youtube_service:
        target_video = "video.mp4"
        target_thumbnail = "image.jpg"
        
        if os.path.exists(target_video):
            # 1. Upload the Video
            video_id = upload_video(
                youtube_service, 
                video_file=target_video, 
                title="Public Video with Custom Thumbnail!", 
                description="Testing public video and thumbnail upload via GitHub Actions API!"
            )
            
            # 2. Upload the Thumbnail
            if video_id and os.path.exists(target_thumbnail):
                upload_thumbnail(youtube_service, video_id, target_thumbnail)
            elif not os.path.exists(target_thumbnail):
                print(f"Notice: '{target_thumbnail}' not found in the repository. Skipping thumbnail.")
                
            print(f"Done! Check your channel: https://www.youtube.com/watch?v={video_id}")
        else:
            print(f"Error: Could not find '{target_video}'. Did you upload it to the repository?")
