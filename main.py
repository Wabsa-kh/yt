import os, json, subprocess, requests
from datetime import datetime, timezone
from dateutil.parser import isoparse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CONFIG = "config/channels.json"
STATE_DIR = "state"

def load_json(path, default):
    if not os.path.exists(path):
        return default
    return json.load(open(path))

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def yt():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"]
    )
    return build("youtube", "v3", credentials=creds)

def download_video(video_id):
    subprocess.run([
        "yt-dlp",
        "-f", "mp4",
        "-o", "video.mp4",
        f"https://youtube.com/watch?v={video_id}"
    ], check=True)

def download_thumbnail(snippet):
    thumbs = snippet["thumbnails"]
    url = (
        thumbs.get("maxres", {})
        or thumbs.get("high", {})
        or thumbs.get("default", {})
    ).get("url")

    if not url:
        return False

    r = requests.get(url, timeout=20)
    open("thumb.jpg", "wb").write(r.content)
    return True

def upload_video(youtube, snippet, privacy):
    req = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": snippet["title"],
                "description": snippet["description"]
            },
            "status": {"privacyStatus": privacy}
        },
        media_body="video.mp4"
    )
    res = req.execute()
    return res["id"]

def set_thumbnail(youtube, video_id):
    youtube.thumbnails().set(
        videoId=video_id,
        media_body="thumb.jpg"
    ).execute()

def fetch_videos(youtube, channel_id):
    videos = []
    req = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=50,
        order="date",
        type="video"
    )
    while req:
        res = req.execute()
        videos += res["items"]
        req = youtube.search().list_next(req, res)
    return videos

def main():
    os.makedirs(STATE_DIR, exist_ok=True)

    uploaded = load_json("state/uploaded.json", {})
    queues = load_json("state/queues.json", {})
    last_check = load_json("state/last_check.json", {})

    youtube = yt()
    config = load_json(CONFIG, {})

    for ch in config["channels"]:
        src = ch["source_channel_id"]
        uploaded.setdefault(src, [])
        queues.setdefault(src, [])
        last_dt = isoparse(last_check.get(src)) if src in last_check else datetime.min.replace(tzinfo=timezone.utc)

        videos = fetch_videos(youtube, src)

        new = []
        for v in videos:
            vid = v["id"]["videoId"]
            pub = isoparse(v["snippet"]["publishedAt"])

            if vid in uploaded[src]:
                continue

            if pub > last_dt:
                new.append(v)
            elif vid not in queues[src]:
                queues[src].append(vid)

        # NEW VIDEOS
        for v in new[:ch["max_new_per_run"]]:
            vid = v["id"]["videoId"]
            download_video(vid)
            download_thumbnail(v["snippet"])
            up_id = upload_video(youtube, v["snippet"], ch["privacy_status"])
            if os.path.exists("thumb.jpg"):
                set_thumbnail(youtube, up_id)
            uploaded[src].append(vid)

        # OLD VIDEOS
        for _ in range(ch["max_old_per_run"]):
            if not queues[src]:
                break
            vid = queues[src].pop(0)
            download_video(vid)
            v = next(x for x in videos if x["id"]["videoId"] == vid)
            download_thumbnail(v["snippet"])
            up_id = upload_video(youtube, v["snippet"], ch["privacy_status"])
            if os.path.exists("thumb.jpg"):
                set_thumbnail(youtube, up_id)
            uploaded[src].append(vid)

        last_check[src] = datetime.now(timezone.utc).isoformat()

    save_json("state/uploaded.json", uploaded)
    save_json("state/queues.json", queues)
    save_json("state/last_check.json", last_check)

if __name__ == "__main__":
    main()
