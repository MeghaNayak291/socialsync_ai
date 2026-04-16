import os
from datetime import datetime
from sqlalchemy.orm import Session
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from config import settings
from database import get_token, log_post
from oauth_youtube import refresh_access_token

def _get_credentials(db: Session, user_id: int):
    rec = get_token(db, user_id, "youtube")
    if not rec:
        return None
    if rec.expires_at and rec.expires_at < datetime.utcnow():
        new_token = refresh_access_token(db, user_id)
        if not new_token:
            return None
        rec = get_token(db, user_id, "youtube")
    return google.oauth2.credentials.Credentials(
        token=rec.access_token,
        refresh_token=rec.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.YOUTUBE_CLIENT_ID,
        client_secret=settings.YOUTUBE_CLIENT_SECRET,
        scopes=settings.YOUTUBE_SCOPES,
    )

def post_video(db: Session, user_id: int, video_path: str, title: str = "", description: str = "", privacy: str = "public") -> dict:
    creds = _get_credentials(db, user_id)
    if not creds:
        return {"ok": False, "error": "YouTube not connected."}
    try:
        youtube = build("youtube", "v3", credentials=creds)
        body = {
            "snippet": {
                "title":       title or "New Video",
                "description": description,
                "categoryId":  "22",
            },
            "status": {"privacyStatus": privacy},
        }
        media   = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
        video_id = response.get("id", "")
        log_post(db, user_id, "youtube", "video", "success")
        return {"ok": True, "video_id": video_id, "url": f"https://youtu.be/{video_id}"}
    except Exception as e:
        log_post(db, user_id, "youtube", "video", "failed", str(e))
        return {"ok": False, "error": str(e)}