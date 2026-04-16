import requests
from sqlalchemy.orm import Session
from database import get_token, log_post

UGC    = "https://api.linkedin.com/v2/ugcPosts"
ASSETS = "https://api.linkedin.com/v2/assets?action=registerUpload"

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

def _person_urn(token_rec) -> str:
    return f"urn:li:person:{token_rec.extra.get('sub', '')}"

def post_text(db: Session, user_id: int, text: str) -> dict:
    rec = get_token(db, user_id, "linkedin")
    if not rec:
        return {"ok": False, "error": "LinkedIn not connected."}
    payload = {
        "author": _person_urn(rec),
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = requests.post(UGC, json=payload, headers=_headers(rec.access_token), timeout=20)
    ok = resp.status_code in (200, 201)
    log_post(db, user_id, "linkedin", "text", "success" if ok else "failed", None if ok else resp.text)
    return {"ok": ok, "error": resp.text if not ok else None}

def _register_asset(token: str, person_urn: str, recipe: str) -> tuple:
    payload = {
        "registerUploadRequest": {
            "recipes": [recipe],
            "owner": person_urn,
            "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}],
        }
    }
    resp = requests.post(ASSETS, json=payload, headers=_headers(token), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn  = data["value"]["asset"]
    return upload_url, asset_urn

def post_image(db: Session, user_id: int, image_path: str, caption: str = "") -> dict:
    rec = get_token(db, user_id, "linkedin")
    if not rec:
        return {"ok": False, "error": "LinkedIn not connected."}
    try:
        upload_url, asset_urn = _register_asset(rec.access_token, _person_urn(rec), "urn:li:digitalmediaRecipe:feedshare-image")
        with open(image_path, "rb") as f:
            requests.put(upload_url, data=f, headers={
                "Authorization": f"Bearer {rec.access_token}",
                "Content-Type": "application/octet-stream"
            }, timeout=60).raise_for_status()
        payload = {
            "author": _person_urn(rec),
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": caption},
                    "shareMediaCategory": "IMAGE",
                    "media": [{"status": "READY", "media": asset_urn, "description": {"text": caption}, "title": {"text": ""}}],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        resp = requests.post(UGC, json=payload, headers=_headers(rec.access_token), timeout=20)
        ok = resp.status_code in (200, 201)
        log_post(db, user_id, "linkedin", "photo", "success" if ok else "failed", None if ok else resp.text)
        return {"ok": ok, "error": resp.text if not ok else None}
    except Exception as e:
        log_post(db, user_id, "linkedin", "photo", "failed", str(e))
        return {"ok": False, "error": str(e)}

def post_video(db: Session, user_id: int, video_path: str, caption: str = "") -> dict:
    rec = get_token(db, user_id, "linkedin")
    if not rec:
        return {"ok": False, "error": "LinkedIn not connected."}
    try:
        upload_url, asset_urn = _register_asset(rec.access_token, _person_urn(rec), "urn:li:digitalmediaRecipe:feedshare-video")
        with open(video_path, "rb") as f:
            requests.put(upload_url, data=f, headers={
                "Authorization": f"Bearer {rec.access_token}",
                "Content-Type": "application/octet-stream"
            }, timeout=120).raise_for_status()
        payload = {
            "author": _person_urn(rec),
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": caption},
                    "shareMediaCategory": "VIDEO",
                    "media": [{"status": "READY", "media": asset_urn, "description": {"text": caption}, "title": {"text": ""}}],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        resp = requests.post(UGC, json=payload, headers=_headers(rec.access_token), timeout=20)
        ok = resp.status_code in (200, 201)
        log_post(db, user_id, "linkedin", "video", "success" if ok else "failed", None if ok else resp.text)
        return {"ok": ok, "error": resp.text if not ok else None}
    except Exception as e:
        log_post(db, user_id, "linkedin", "video", "failed", str(e))
        return {"ok": False, "error": str(e)}