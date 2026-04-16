import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import (
    init_db, get_db, get_user_by_email, get_user_by_id,
    create_user, connected_platforms, delete_token,
)
from auth import hash_password, verify_password, create_session_token, decode_session_token
from oauth_linkedin import get_auth_url as li_auth_url, handle_callback as li_callback
from oauth_youtube  import get_auth_url as yt_auth_url, handle_callback as yt_callback

app = FastAPI(title="SocialSync", docs_url=None, redoc_url=None)

MEDIA_DIR = Path(__file__).parent / "media_temp"
MEDIA_DIR.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

@app.on_event("startup")
def startup():
    init_db()

SESSION_COOKIE = "ap_session"

def get_current_user_id(request: Request) -> Optional[int]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return decode_session_token(token)

def require_user(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    if not uid:
        return None
    return get_user_by_id(db, uid)

class SignupBody(BaseModel):
    email: str
    username: str
    password: str

class LoginBody(BaseModel):
    email: str
    password: str

@app.post("/api/signup")
def api_signup(body: SignupBody, db: Session = Depends(get_db)):
    if get_user_by_email(db, body.email):
        raise HTTPException(400, "Email already registered.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if len(body.username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters.")
    user = create_user(db, body.email, body.username, hash_password(body.password))
    token = create_session_token(user.id)
    response = JSONResponse({"ok": True, "username": user.username})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=60*60*24*30, samesite="lax")
    return response

@app.post("/api/login")
def api_login(body: LoginBody, db: Session = Depends(get_db)):
    user = get_user_by_email(db, body.email)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password.")
    token = create_session_token(user.id)
    response = JSONResponse({"ok": True, "username": user.username})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=60*60*24*30, samesite="lax")
    return response

@app.post("/api/logout")
def api_logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie(SESSION_COOKIE)
    return r

@app.get("/api/me")
def api_me(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(401, "Not authenticated.")
    user = get_user_by_id(db, uid)
    if not user:
        raise HTTPException(404, "User not found.")
    platforms = connected_platforms(db, uid)
    tg_token = create_session_token(uid)
    return {
        "id":         user.id,
        "email":      user.email,
        "username":   user.username,
        "telegram_id": user.telegram_id,
        "platforms":  platforms,
        "tg_token":   tg_token,
    }

@app.post("/auth/disconnect/{platform}")
def disconnect_platform(platform: str, request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    if not uid:
        raise HTTPException(401, "Not authenticated.")
    delete_token(db, uid, platform)
    return {"ok": True}

@app.get("/auth/linkedin/connect")
def linkedin_connect(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    return RedirectResponse(li_auth_url(db, uid))

@app.get("/auth/linkedin/callback", response_class=HTMLResponse)
def linkedin_cb(request: Request, code: str = None, state: str = None,
                error: str = None, db: Session = Depends(get_db)):
    if error or not code:
        return _result_page("LinkedIn", False, error or "Missing code.")
    result = li_callback(db, code, state)
    return _result_page("LinkedIn", result["ok"],
                        f"Welcome, {result.get('name')}! LinkedIn connected." if result["ok"] else result.get("error"))

@app.get("/auth/youtube/connect")
def youtube_connect(request: Request, db: Session = Depends(get_db)):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    return RedirectResponse(yt_auth_url(db, uid))

@app.get("/auth/youtube/callback", response_class=HTMLResponse)
def youtube_cb(request: Request, code: str = None, state: str = None,
               error: str = None, db: Session = Depends(get_db)):
    if error or not code:
        return _result_page("YouTube", False, error or "Missing code.")
    result = yt_callback(db, code, state)
    return _result_page("YouTube", result["ok"],
                        f"Welcome, {result.get('name')}! YouTube connected." if result["ok"] else result.get("error"))

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    uid = get_current_user_id(request)
    if uid:
        return RedirectResponse("/dashboard")
    return HTMLResponse(_landing_html())

@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    uid = get_current_user_id(request)
    if uid:
        return RedirectResponse("/dashboard")
    return HTMLResponse(_signup_html())

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    uid = get_current_user_id(request)
    if uid:
        return RedirectResponse("/dashboard")
    return HTMLResponse(_login_html())

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    uid = get_current_user_id(request)
    if not uid:
        return RedirectResponse("/login")
    return HTMLResponse(_dashboard_html())

def _result_page(platform: str, ok: bool, message: str) -> str:
    icon  = "✅" if ok else "❌"
    color = "#00e5a0" if ok else "#ff4d6d"
    title = "Connected!" if ok else "Failed"
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{platform} Auth</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&display=swap');
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:'Syne',sans-serif;background:#0a0a0f;min-height:100vh;display:flex;
        align-items:center;justify-content:center;color:#fff}}
  .card{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
         border-radius:24px;padding:56px 48px;max-width:420px;width:90%;text-align:center}}
  .icon{{font-size:52px;margin-bottom:20px}}
  h1{{font-size:28px;font-weight:800;color:{color};margin-bottom:12px}}
  p{{color:rgba(255,255,255,.6);line-height:1.6;margin-bottom:28px}}
  a{{display:inline-block;background:{color};color:#000;font-weight:700;
     padding:14px 32px;border-radius:12px;text-decoration:none;font-size:15px}}
</style></head><body>
<div class="card">
  <div class="icon">{icon}</div>
  <h1>{platform} {title}</h1>
  <p>{message}</p>
  <a href="/dashboard">← Back to Dashboard</a>
</div></body></html>"""

def _landing_html() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SocialSync — Post Everywhere at Once</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#07070d;--border:rgba(255,255,255,.08);--accent:#00e5a0;--accent2:#7c6aff;--text:#f0f0f5;--muted:rgba(240,240,245,.45);}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}
.blob{position:fixed;border-radius:50%;filter:blur(120px);opacity:.18;pointer-events:none}
.blob-1{width:600px;height:600px;background:var(--accent2);top:-200px;right:-200px}
.blob-2{width:500px;height:500px;background:var(--accent);bottom:-150px;left:-150px}
nav{position:fixed;top:0;left:0;right:0;z-index:100;padding:20px 48px;display:flex;align-items:center;justify-content:space-between;backdrop-filter:blur(20px);border-bottom:1px solid var(--border);background:rgba(7,7,13,.6)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:22px}.logo span{color:var(--accent)}
.nav-links{display:flex;gap:12px}
.btn-ghost{padding:10px 24px;border:1px solid var(--border);border-radius:10px;color:var(--text);text-decoration:none;font-size:14px;font-weight:500;transition:all .2s}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn-primary{padding:10px 24px;background:var(--accent);color:#000;border-radius:10px;text-decoration:none;font-size:14px;font-weight:700}
.hero{position:relative;z-index:1;padding:160px 48px 80px;text-align:center;max-width:900px;margin:0 auto}
.hero-tag{display:inline-flex;align-items:center;gap:8px;padding:8px 20px;background:rgba(0,229,160,.08);border:1px solid rgba(0,229,160,.2);border-radius:100px;font-size:13px;color:var(--accent);font-weight:500;margin-bottom:32px}
.hero-tag::before{content:'';width:8px;height:8px;background:var(--accent);border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
h1{font-family:'Syne',sans-serif;font-size:clamp(42px,7vw,80px);font-weight:800;line-height:1.05;letter-spacing:-2px;margin-bottom:24px}
h1 em{font-style:normal;color:var(--accent)}
.hero-sub{font-size:clamp(16px,2vw,20px);color:var(--muted);max-width:560px;margin:0 auto 48px;line-height:1.6}
.hero-cta{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}
.btn-large{padding:18px 42px;border-radius:14px;font-size:16px;font-weight:700;text-decoration:none;transition:all .2s}
.btn-accent{background:var(--accent);color:#000}
.btn-accent:hover{transform:translateY(-3px);box-shadow:0 12px 40px rgba(0,229,160,.35)}
.btn-outline{border:1px solid var(--border);color:var(--text)}
.section{position:relative;z-index:1;padding:80px 48px;max-width:1000px;margin:0 auto}
.section-label{font-size:12px;letter-spacing:3px;text-transform:uppercase;color:var(--accent);font-weight:600;margin-bottom:16px}
.section-title{font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,42px);font-weight:800;letter-spacing:-1px;margin-bottom:48px}
.flow-step{display:flex;gap:32px;align-items:flex-start;padding:32px 0;border-bottom:1px solid var(--border)}
.flow-step:last-child{border-bottom:none}
.step-num{font-family:'Syne',sans-serif;font-size:48px;font-weight:800;color:rgba(255,255,255,.06);min-width:64px}
.step-content h3{font-family:'Syne',sans-serif;font-size:20px;font-weight:700;margin-bottom:8px}
.step-content p{color:var(--muted);line-height:1.6}
.platforms{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:24px}
.platform-card{background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:16px;padding:28px 24px;text-align:center;transition:all .3s}
.platform-card:hover{border-color:rgba(255,255,255,.15);transform:translateY(-4px)}
.platform-icon{font-size:36px;margin-bottom:12px}
.platform-name{font-family:'Syne',sans-serif;font-weight:700;font-size:16px;margin-bottom:4px}
.platform-desc{font-size:13px;color:var(--muted)}
.cta-section{position:relative;z-index:1;padding:80px 48px;text-align:center}
.cta-box{background:linear-gradient(135deg,rgba(124,106,255,.12),rgba(0,229,160,.08));border:1px solid rgba(255,255,255,.08);border-radius:24px;padding:64px 48px;max-width:640px;margin:0 auto}
.cta-box h2{font-family:'Syne',sans-serif;font-size:clamp(28px,4vw,40px);font-weight:800;letter-spacing:-1px;margin-bottom:16px}
.cta-box p{color:var(--muted);margin-bottom:36px;line-height:1.6}
footer{position:relative;z-index:1;text-align:center;padding:40px;color:var(--muted);font-size:13px;border-top:1px solid var(--border)}
</style></head><body>
<div class="blob blob-1"></div><div class="blob blob-2"></div>
<nav>
  <div class="logo">Social<span>Sync</span></div>
  <div class="nav-links">
    <a href="/login" class="btn-ghost">Log in</a>
    <a href="/signup" class="btn-primary">Get Started</a>
  </div>
</nav>
<div class="hero">
  <div class="hero-tag">LinkedIn · YouTube · More coming soon</div>
  <h1>Post everywhere.<br><em>Instantly.</em></h1>
  <p class="hero-sub">Connect your accounts once, then send anything to your Telegram bot — it posts to all your platforms automatically.</p>
  <div class="hero-cta">
    <a href="/signup" class="btn-large btn-accent">Start for free →</a>
  </div>
</div>
<div class="section">
  <div class="section-label">How It Works</div>
  <div class="section-title">Three steps to autopilot</div>
  <div class="flow-step"><div class="step-num">01</div><div class="step-content"><h3>Sign up on this website</h3><p>Create your free account in 30 seconds.</p></div></div>
  <div class="flow-step"><div class="step-num">02</div><div class="step-content"><h3>Connect your social accounts</h3><p>Link LinkedIn and YouTube with one click. Official OAuth — your passwords never touch our servers.</p></div></div>
  <div class="flow-step"><div class="step-num">03</div><div class="step-content"><h3>Post from Telegram, forever</h3><p>Link your Telegram account from the dashboard. Send a photo, video, or text — it instantly appears on every platform.</p></div></div>
</div>
<div class="section">
  <div class="section-label">Platforms</div>
  <div class="section-title">Supported platforms</div>
  <div class="platforms">
    <div class="platform-card"><div class="platform-icon">💼</div><div class="platform-name">LinkedIn</div><div class="platform-desc">Text, photos & videos</div></div>
    <div class="platform-card"><div class="platform-icon">📺</div><div class="platform-name">YouTube</div><div class="platform-desc">Video uploads</div></div>
  </div>
</div>
<div class="cta-section">
  <div class="cta-box">
    <h2>Ready to save hours every week?</h2>
    <p>Join creators and professionals who post smarter, not harder.</p>
    <a href="/signup" class="btn-large btn-accent">Create free account →</a>
  </div>
</div>
<footer>© 2024 SocialSync · Built for creators everywhere</footer>
</body></html>"""

def _signup_html() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign Up — SocialSync</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#07070d;--border:rgba(255,255,255,.08);--accent:#00e5a0;--text:#f0f0f5;--muted:rgba(240,240,245,.45);}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.blob{position:fixed;border-radius:50%;filter:blur(120px);opacity:.15;pointer-events:none}
.b1{width:500px;height:500px;background:#7c6aff;top:-200px;right:-100px}
.b2{width:400px;height:400px;background:#00e5a0;bottom:-100px;left:-100px}
.card{position:relative;z-index:1;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:24px;padding:48px;width:100%;max-width:440px}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:20px;margin-bottom:32px}.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;letter-spacing:-1px;margin-bottom:6px}
.sub{color:var(--muted);font-size:14px;margin-bottom:36px}
.field{margin-bottom:16px}
label{display:block;font-size:13px;font-weight:500;color:var(--muted);margin-bottom:6px}
input{width:100%;padding:14px 16px;background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:12px;color:var(--text);font-size:15px;font-family:inherit;outline:none;transition:border-color .2s}
input:focus{border-color:var(--accent)}
input::placeholder{color:rgba(255,255,255,.2)}
.btn{width:100%;padding:16px;background:var(--accent);color:#000;border:none;border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;margin-top:8px;transition:all .2s;font-family:inherit}
.btn:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,229,160,.3)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.switch{text-align:center;margin-top:24px;font-size:13px;color:var(--muted)}
.switch a{color:var(--accent);text-decoration:none;font-weight:600}
.error{background:rgba(255,77,109,.1);border:1px solid rgba(255,77,109,.3);border-radius:10px;padding:12px 16px;font-size:13px;color:#ff4d6d;margin-bottom:16px;display:none}
</style></head><body>
<div class="blob b1"></div><div class="blob b2"></div>
<div class="card">
  <div class="logo">Social<span>Sync</span></div>
  <h1>Create account</h1>
  <p class="sub">Start posting everywhere in minutes.</p>
  <div class="error" id="err"></div>
  <div class="field"><label>Email</label><input type="email" id="email" placeholder="you@example.com"></div>
  <div class="field"><label>Username</label><input type="text" id="username" placeholder="yourname"></div>
  <div class="field"><label>Password</label><input type="password" id="password" placeholder="Min. 8 characters"></div>
  <button class="btn" id="btn" onclick="signup()">Create Account →</button>
  <div class="switch">Already have an account? <a href="/login">Log in</a></div>
</div>
<script>
async function signup(){
  const btn=document.getElementById('btn');
  const err=document.getElementById('err');
  err.style.display='none';
  btn.disabled=true;btn.textContent='Creating...';
  const r=await fetch('/api/signup',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email:document.getElementById('email').value,
      username:document.getElementById('username').value,
      password:document.getElementById('password').value})});
  const d=await r.json();
  if(r.ok){window.location='/dashboard'}
  else{err.textContent=d.detail||'Something went wrong.';err.style.display='block';
       btn.disabled=false;btn.textContent='Create Account →'}
}
document.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')signup()}));
</script></body></html>"""

def _login_html() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Log In — SocialSync</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#07070d;--border:rgba(255,255,255,.08);--accent:#00e5a0;--text:#f0f0f5;--muted:rgba(240,240,245,.45);}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.blob{position:fixed;border-radius:50%;filter:blur(120px);opacity:.15;pointer-events:none}
.b1{width:500px;height:500px;background:#7c6aff;top:-200px;right:-100px}
.b2{width:400px;height:400px;background:#00e5a0;bottom:-100px;left:-100px}
.card{position:relative;z-index:1;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:24px;padding:48px;width:100%;max-width:440px}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:20px;margin-bottom:32px}.logo span{color:var(--accent)}
h1{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;letter-spacing:-1px;margin-bottom:6px}
.sub{color:var(--muted);font-size:14px;margin-bottom:36px}
.field{margin-bottom:16px}
label{display:block;font-size:13px;font-weight:500;color:var(--muted);margin-bottom:6px}
input{width:100%;padding:14px 16px;background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:12px;color:var(--text);font-size:15px;font-family:inherit;outline:none;transition:border-color .2s}
input:focus{border-color:var(--accent)}
input::placeholder{color:rgba(255,255,255,.2)}
.btn{width:100%;padding:16px;background:var(--accent);color:#000;border:none;border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;margin-top:8px;transition:all .2s;font-family:inherit}
.btn:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,229,160,.3)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.switch{text-align:center;margin-top:24px;font-size:13px;color:var(--muted)}
.switch a{color:var(--accent);text-decoration:none;font-weight:600}
.error{background:rgba(255,77,109,.1);border:1px solid rgba(255,77,109,.3);border-radius:10px;padding:12px 16px;font-size:13px;color:#ff4d6d;margin-bottom:16px;display:none}
</style></head><body>
<div class="blob b1"></div><div class="blob b2"></div>
<div class="card">
  <div class="logo">Social<span>Sync</span></div>
  <h1>Welcome back</h1>
  <p class="sub">Log in to your account.</p>
  <div class="error" id="err"></div>
  <div class="field"><label>Email</label><input type="email" id="email" placeholder="you@example.com"></div>
  <div class="field"><label>Password</label><input type="password" id="password" placeholder="Your password"></div>
  <button class="btn" id="btn" onclick="login()">Log In →</button>
  <div class="switch">Don't have an account? <a href="/signup">Sign up</a></div>
</div>
<script>
async function login(){
  const btn=document.getElementById('btn');
  const err=document.getElementById('err');
  err.style.display='none';
  btn.disabled=true;btn.textContent='Logging in...';
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email:document.getElementById('email').value,
      password:document.getElementById('password').value})});
  const d=await r.json();
  if(r.ok){window.location='/dashboard'}
  else{err.textContent=d.detail||'Invalid credentials.';err.style.display='block';
       btn.disabled=false;btn.textContent='Log In →'}
}
document.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')login()}));
</script></body></html>"""

def _dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard — SocialSync</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#07070d;--surface:rgba(255,255,255,.04);--border:rgba(255,255,255,.08);--accent:#00e5a0;--accent2:#7c6aff;--text:#f0f0f5;--muted:rgba(240,240,245,.45);}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.blob{position:fixed;border-radius:50%;filter:blur(140px);opacity:.1;pointer-events:none}
.b1{width:600px;height:600px;background:var(--accent2);top:-100px;right:-200px}
.b2{width:400px;height:400px;background:var(--accent);bottom:-100px;left:-100px}
nav{position:sticky;top:0;z-index:100;padding:16px 48px;display:flex;align-items:center;justify-content:space-between;backdrop-filter:blur(20px);border-bottom:1px solid var(--border);background:rgba(7,7,13,.7)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:20px}.logo span{color:var(--accent)}
.nav-right{display:flex;align-items:center;gap:16px}
.username{font-size:13px;color:var(--muted)}
.btn-sm{padding:8px 20px;border:1px solid var(--border);border-radius:8px;color:var(--muted);background:none;cursor:pointer;font-family:inherit;font-size:13px;transition:all .2s}
.btn-sm:hover{border-color:rgba(255,255,255,.2);color:var(--text)}
main{position:relative;z-index:1;max-width:860px;margin:0 auto;padding:48px 24px}
.greeting{margin-bottom:40px}
.greeting h1{font-family:'Syne',sans-serif;font-size:32px;font-weight:800;letter-spacing:-1px;margin-bottom:6px}
.greeting p{color:var(--muted)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:28px;margin-bottom:20px}
.card-header{display:flex;align-items:center;gap:12px;margin-bottom:20px}
.card-icon{font-size:24px}
.card-title{font-family:'Syne',sans-serif;font-weight:700;font-size:16px}
.platform-row{display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid var(--border)}
.platform-row:last-child{border-bottom:none}
.platform-info{display:flex;align-items:center;gap:12px}
.p-icon{font-size:20px}
.p-name{font-weight:500;font-size:14px}
.status-badge{font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px}
.badge-on{background:rgba(0,229,160,.12);color:var(--accent);border:1px solid rgba(0,229,160,.25)}
.badge-off{background:rgba(255,255,255,.05);color:var(--muted);border:1px solid var(--border)}
.action-btn{padding:8px 16px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;transition:all .2s;border:none;text-decoration:none;display:inline-block}
.connect-btn{background:rgba(0,229,160,.12);color:var(--accent);border:1px solid rgba(0,229,160,.25)}
.connect-btn:hover{background:rgba(0,229,160,.2)}
.disconnect-btn{background:rgba(255,77,109,.08);color:#ff4d6d;border:1px solid rgba(255,77,109,.2)}
.disconnect-btn:hover{background:rgba(255,77,109,.15)}
.tg-steps{display:flex;flex-direction:column;gap:12px}
.tg-step{display:flex;gap:12px;align-items:flex-start}
.step-circle{min-width:26px;height:26px;border-radius:50%;background:rgba(0,229,160,.12);border:1px solid rgba(0,229,160,.25);color:var(--accent);font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center}
.step-text{font-size:14px;color:var(--muted);padding-top:3px}
.step-text strong{color:var(--text)}
.token-box{display:flex;gap:8px;margin-top:12px}
.token-input{flex:1;padding:10px 14px;background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:10px;color:var(--text);font-size:12px;word-break:break-all}
.copy-btn{padding:10px 16px;background:rgba(0,229,160,.1);color:var(--accent);border:1px solid rgba(0,229,160,.25);border-radius:10px;font-family:inherit;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap}
.tg-linked{display:flex;align-items:center;gap:8px;padding:12px 16px;background:rgba(0,229,160,.06);border:1px solid rgba(0,229,160,.15);border-radius:12px;font-size:14px;color:var(--accent)}
.tg-btn{display:inline-block;background:var(--accent);color:#000;font-weight:700;padding:14px 28px;border-radius:12px;text-decoration:none;font-size:15px;margin:16px 0;}
.tg-btn:hover{opacity:.9}
</style></head><body>
<div class="blob b1"></div><div class="blob b2"></div>
<nav>
  <div class="logo">Social<span>Sync</span></div>
  <div class="nav-right">
    <span class="username" id="userlabel">Loading...</span>
    <button class="btn-sm" onclick="logout()">Log out</button>
  </div>
</nav>
<main>
  <div class="greeting">
    <h1 id="greeting">Dashboard</h1>
    <p>Connect your platforms, then post from Telegram.</p>
  </div>
  <div class="card">
    <div class="card-header"><div class="card-icon">🔗</div><div class="card-title">Connected Platforms</div></div>
    <div id="platform-list">Loading...</div>
  </div>
  <div class="card">
    <div class="card-header"><div class="card-icon">✈️</div><div class="card-title">Link Telegram Bot</div></div>
    <div id="tg-section">Loading...</div>
  </div>
</main>
<script>
let userData = null;
const PLATFORMS = [
  {id:'linkedin', name:'LinkedIn', icon:'💼', connectUrl:'/auth/linkedin/connect'},
  {id:'youtube',  name:'YouTube',  icon:'📺', connectUrl:'/auth/youtube/connect'},
];
async function load(){
  const r = await fetch('/api/me');
  if(!r.ok){ window.location='/login'; return; }
  userData = await r.json();
  document.getElementById('userlabel').textContent = '@' + userData.username;
  document.getElementById('greeting').textContent = 'Hey, ' + userData.username + ' 👋';
  renderPlatforms();
  renderTelegram();
}
function renderPlatforms(){
  const connected = userData.platforms || [];
  const html = PLATFORMS.map(p => {
    const on = connected.includes(p.id);
    return `<div class="platform-row">
      <div class="platform-info"><span class="p-icon">${p.icon}</span><span class="p-name">${p.name}</span></div>
      <div style="display:flex;align-items:center;gap:10px">
        <span class="status-badge ${on?'badge-on':'badge-off'}">${on?'Connected':'Not connected'}</span>
        ${on
          ? `<button class="action-btn disconnect-btn" onclick="disconnect('${p.id}')">Disconnect</button>`
          : `<a href="${p.connectUrl}" class="action-btn connect-btn">Connect →</a>`}
      </div>
    </div>`;
  }).join('');
  document.getElementById('platform-list').innerHTML = html;
}
function renderTelegram(){
  const tgLinked = userData.telegram_id;
  const tgSection = document.getElementById('tg-section');
  if(tgLinked){
    tgSection.innerHTML = `
      <div class="tg-linked">✅ Telegram linked! You're all set.</div>
      <div style="margin-top:16px">
        <a href="https://t.me/pooja_project_ai_bot" target="_blank" class="tg-btn">
          📱 Open @Socialsync_AI Bot →
        </a>
      </div>`;
    return;
  }
  const token = userData.tg_token || '';
  tgSection.innerHTML = `
    <div class="tg-steps">
      <div class="tg-step">
        <div class="step-circle">1</div>
        <div class="step-text">Open the Telegram bot 👇</div>
      </div>
    </div>
    <a href="https://t.me/Socialsync_AIbot" target="_blank" class="tg-btn">
      📱 Open @Socialsync_AI Bot →
    </a>
    <div class="tg-steps">
      <div class="tg-step">
        <div class="step-circle">2</div>
        <div class="step-text">Copy this token and paste it in the bot:</div>
      </div>
    </div>
    <div class="token-box">
      <div class="token-input" id="tg-token">/link ${token}</div>
      <button class="copy-btn" onclick="copyToken()">Copy</button>
    </div>
    <p style="margin-top:12px;font-size:12px;color:var(--muted)">Do this once — then just chat with the bot to post anywhere!</p>`;
}
async function disconnect(platform){
  if(!confirm('Disconnect ' + platform + '?')) return;
  await fetch('/auth/disconnect/' + platform, {method:'POST'});
  await load();
}
async function logout(){
  await fetch('/api/logout', {method:'POST'});
  window.location = '/';
}
function copyToken(){
  const t = document.getElementById('tg-token').textContent;
  navigator.clipboard.writeText(t).then(()=>{
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(()=>btn.textContent='Copy', 2000);
  });
}
load();
</script></body></html>"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)