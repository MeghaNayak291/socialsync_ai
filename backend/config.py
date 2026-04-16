import os
from dotenv import load_dotenv
load_dotenv()

class Settings:
    SECRET_KEY: str = os.getenv("APP_SECRET_KEY", "changeme")
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./autopost.db")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    LINKEDIN_CLIENT_ID: str = os.getenv("LINKEDIN_CLIENT_ID", "")
    LINKEDIN_CLIENT_SECRET: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    LINKEDIN_REDIRECT_URI: str = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/auth/linkedin/callback")
    LINKEDIN_SCOPES: list = ["openid", "profile", "w_member_social"]
    INSTAGRAM_APP_ID: str = os.getenv("INSTAGRAM_APP_ID", "")
    INSTAGRAM_APP_SECRET: str = os.getenv("INSTAGRAM_APP_SECRET", "")
    INSTAGRAM_REDIRECT_URI: str = os.getenv("INSTAGRAM_REDIRECT_URI", "http://localhost:8000/auth/instagram/callback")
    INSTAGRAM_SCOPES: list = ["instagram_basic", "instagram_content_publish", "pages_read_engagement", "pages_show_list"]
    YOUTUBE_CLIENT_ID: str = os.getenv("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET: str = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    YOUTUBE_REDIRECT_URI: str = os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:8000/auth/youtube/callback")
    YOUTUBE_SCOPES: list = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]

settings = Settings()
