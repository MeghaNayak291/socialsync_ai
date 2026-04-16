import json
import secrets
from datetime import datetime
from typing import Optional
 
from sqlalchemy import (
    create_engine, Column, String, Integer, Text,
    DateTime, Boolean, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
 
from config import settings
 
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
 
 
# ── MODELS ────────────────────────────────────────────────────────────────────
 
class User(Base):
    __tablename__ = "users"
 
    id           = Column(Integer, primary_key=True, index=True)
    email        = Column(String(255), unique=True, index=True, nullable=False)
    username     = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    telegram_id  = Column(String(50), unique=True, nullable=True, index=True)
    telegram_username = Column(String(100), nullable=True)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
 
    tokens   = relationship("PlatformToken", back_populates="user", cascade="all, delete")
    posts    = relationship("PostLog", back_populates="user", cascade="all, delete")
 
 
class PlatformToken(Base):
    __tablename__ = "platform_tokens"
    __table_args__ = (UniqueConstraint("user_id", "platform"),)
 
    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform      = Column(String(30), nullable=False)   # linkedin | instagram | youtube
    access_token  = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at    = Column(DateTime, nullable=True)
    extra_json    = Column(Text, nullable=True)           # platform-specific JSON blob
    connected_at  = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
 
    user = relationship("User", back_populates="tokens")
 
    @property
    def extra(self) -> dict:
        return json.loads(self.extra_json) if self.extra_json else {}
 
    @extra.setter
    def extra(self, value: dict):
        self.extra_json = json.dumps(value) if value else None
 
 
class AuthState(Base):
    """Temporary record linking an OAuth `state` param to a user_id + platform."""
    __tablename__ = "auth_states"
 
    state      = Column(String(100), primary_key=True)
    user_id    = Column(Integer, nullable=False)
    platform   = Column(String(30), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class PostLog(Base):
    __tablename__ = "post_logs"
 
    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform     = Column(String(30), nullable=False)
    content_type = Column(String(20), nullable=True)   # text | photo | video
    status       = Column(String(10), nullable=False)  # success | failed
    error        = Column(Text, nullable=True)
    posted_at    = Column(DateTime, default=datetime.utcnow)
 
    user = relationship("User", back_populates="posts")
 
 
# ── DB INIT ───────────────────────────────────────────────────────────────────
 
def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ Database ready.")
 
 
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
 
 
# ── USER HELPERS ──────────────────────────────────────────────────────────────
 
def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()
 
 
def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()
 
 
def get_user_by_telegram_id(db: Session, telegram_id: str) -> Optional[User]:
    return db.query(User).filter(User.telegram_id == str(telegram_id)).first()
 
 
def create_user(db: Session, email: str, username: str, password_hash: str) -> User:
    user = User(email=email, username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
 
 
def link_telegram(db: Session, user_id: int, telegram_id: str, telegram_username: str = None):
    user = get_user_by_id(db, user_id)
    if user:
        user.telegram_id = str(telegram_id)
        user.telegram_username = telegram_username
        db.commit()
 
 
# ── TOKEN HELPERS ─────────────────────────────────────────────────────────────
 
def save_token(db: Session, user_id: int, platform: str,
               access_token: str, refresh_token: str = None,
               expires_at: datetime = None, extra: dict = None):
    token = db.query(PlatformToken).filter_by(user_id=user_id, platform=platform).first()
    if token:
        token.access_token  = access_token
        token.refresh_token = refresh_token or token.refresh_token
        token.expires_at    = expires_at
        token.extra         = extra or {}
        token.updated_at    = datetime.utcnow()
    else:
        token = PlatformToken(
            user_id=user_id, platform=platform,
            access_token=access_token, refresh_token=refresh_token,
            expires_at=expires_at,
        )
        token.extra = extra or {}
        db.add(token)
    db.commit()
 
 
def get_token(db: Session, user_id: int, platform: str) -> Optional[PlatformToken]:
    return db.query(PlatformToken).filter_by(user_id=user_id, platform=platform).first()
 
 
def delete_token(db: Session, user_id: int, platform: str):
    db.query(PlatformToken).filter_by(user_id=user_id, platform=platform).delete()
    db.commit()
 
 
def connected_platforms(db: Session, user_id: int) -> list:
    rows = db.query(PlatformToken.platform).filter_by(user_id=user_id).all()
    return [r.platform for r in rows]
 
 
# ── AUTH STATE HELPERS ────────────────────────────────────────────────────────
 
def create_auth_state(db: Session, user_id: int, platform: str) -> str:
    state = secrets.token_urlsafe(32)
    # Remove old states for same user+platform
    db.query(AuthState).filter_by(user_id=user_id, platform=platform).delete()
    db.add(AuthState(state=state, user_id=user_id, platform=platform))
    db.commit()
    return state
 
 
def consume_auth_state(db: Session, state: str) -> Optional[AuthState]:
    record = db.query(AuthState).filter_by(state=state).first()
    if record:
        db.delete(record)
        db.commit()
    return record
 
 
# ── POST LOG ──────────────────────────────────────────────────────────────────
 
def log_post(db: Session, user_id: int, platform: str,
             content_type: str, status: str, error: str = None):
    db.add(PostLog(
        user_id=user_id, platform=platform,
        content_type=content_type, status=status, error=error,
    ))
    db.commit()
 