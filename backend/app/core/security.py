import secrets
import bcrypt as _bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User


def resolve_secret_key() -> str:
    if settings.secret_key:
        return settings.secret_key
    if settings.is_production:
        raise RuntimeError(
            "SECRET_KEY is required in production. Set it in your .env file."
        )
    return secrets.token_hex(32)


SECRET_KEY = resolve_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = settings.access_token_expire_hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def hash_password(password: str) -> str:
    pwd = password.encode("utf-8")[:72]
    return _bcrypt.hashpw(pwd, _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pwd = plain.encode("utf-8")[:72]
    try:
        return _bcrypt.checkpw(pwd, hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    username = payload.get("sub")

    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_commander(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "commander":
        raise HTTPException(status_code=403, detail="Incident Commander role required")
    return current_user


def require_dispatcher_or_above(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {"commander", "dispatcher"}:
        raise HTTPException(status_code=403, detail="Dispatcher role or above required")
    return current_user


def require_any_role(current_user: User = Depends(get_current_user)) -> User:
    return current_user