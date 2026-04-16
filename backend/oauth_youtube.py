import requests
from urllib.parse import urlencode
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from config import settings
from database import create_auth_state, consume_auth_state, save_token

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"

def get_auth_url(db: Session, user_id: int) -> str:
    state = create_auth_state(db, user_id, "youtube")
    params = {
        "client_id":     settings.YOUTUBE_CLIENT_ID,
        "redirect_uri":  settings.YOUTUBE_REDIRECT_URI,
        "response_type": "code",
        "scope":         " ".join(settings.YOUTUBE_SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

def handle_callback(db: Session, code: str, state: str) -> dict:
    record = consume_auth_state(db, state)
    if not record:
        return {"ok": False, "error": "Invalid or expired state."}
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code":          code,
        "client_id":     settings.YOUTUBE_CLIENT_ID,
        "client_secret": settings.YOUTUBE_CLIENT_SECRET,
        "redirect_uri":  settings.YOUTUBE_REDIRECT_URI,
        "grant_type":    "authorization_code",
    }, timeout=15)
    if resp.status_code != 200:
        return {"ok": False, "error": f"Token exchange failed: {resp.text}"}
    data          = resp.json()
    access_token  = data["access_token"]
    refresh_token = data.get("refresh_token", "")
    expires_at    = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
    profile = requests.get(GOOGLE_USER_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10).json()
    save_token(db, record.user_id, "youtube", access_token=access_token, refresh_token=refresh_token,
        expires_at=expires_at, extra={"name": profile.get("name", ""), "email": profile.get("email", "")})
    return {"ok": True, "name": profile.get("name", "YouTube User")}

def refresh_access_token(db: Session, user_id: int):
    from database import get_token
    token_rec = get_token(db, user_id, "youtube")
    if not token_rec or not token_rec.refresh_token:
        return None
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "client_id":     settings.YOUTUBE_CLIENT_ID,
        "client_secret": settings.YOUTUBE_CLIENT_SECRET,
        "refresh_token": token_rec.refresh_token,
        "grant_type":    "refresh_token",
    }, timeout=15)
    if resp.status_code != 200:
        return None
    data = resp.json()
    expires_at = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
    save_token(db, user_id, "youtube", access_token=data["access_token"],
        refresh_token=token_rec.refresh_token, expires_at=expires_at, extra=token_rec.extra)
    return data["access_token"]