import requests
from urllib.parse import urlencode
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from config import settings
from database import create_auth_state, consume_auth_state, save_token

AUTH_URL    = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL   = "https://www.linkedin.com/oauth/v2/accessToken"
PROFILE_URL = "https://api.linkedin.com/v2/userinfo"

def get_auth_url(db: Session, user_id: int) -> str:
    state = create_auth_state(db, user_id, "linkedin")
    params = {
        "response_type": "code",
        "client_id":     settings.LINKEDIN_CLIENT_ID,
        "redirect_uri":  settings.LINKEDIN_REDIRECT_URI,
        "state":         state,
        "scope":         " ".join(settings.LINKEDIN_SCOPES),
    }
    return f"{AUTH_URL}?{urlencode(params)}"

def handle_callback(db: Session, code: str, state: str) -> dict:
    record = consume_auth_state(db, state)
    if not record:
        return {"ok": False, "error": "Invalid or expired state."}
    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  settings.LINKEDIN_REDIRECT_URI,
        "client_id":     settings.LINKEDIN_CLIENT_ID,
        "client_secret": settings.LINKEDIN_CLIENT_SECRET,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    if resp.status_code != 200:
        return {"ok": False, "error": f"Token exchange failed: {resp.text}"}
    data         = resp.json()
    access_token = data["access_token"]
    expires_at   = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 5183999))
    profile = requests.get(PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10).json()
    save_token(db, record.user_id, "linkedin", access_token=access_token, expires_at=expires_at,
        extra={"sub": profile.get("sub", ""), "name": profile.get("name", ""), "email": profile.get("email", "")})
    return {"ok": True, "name": profile.get("name", "LinkedIn User")}