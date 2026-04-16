from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError
from config import settings
 
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days
 
 
def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)
 
 
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)
 
 
def create_session_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
 
 
def decode_session_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
 