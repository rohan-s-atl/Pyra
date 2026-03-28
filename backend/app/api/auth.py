from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from app.models.user import User


router = APIRouter(prefix="/api/auth", tags=["Auth"])


# -------------------------
# Schemas
# -------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str


class UserResponse(BaseModel):
    id: str
    username: str
    role: str


# -------------------------
# Default Users (DEV ONLY)
# -------------------------

DEFAULT_USERS = [
    {"username": "commander", "password": "pyra2025", "role": "commander"},
    {"username": "dispatcher", "password": "pyra2025", "role": "dispatcher"},
    {"username": "viewer", "password": "pyra2025", "role": "viewer"},
]


def seed_users(db: Session):
    """
    Seed default users ONLY if database is empty.
    Prevents duplicate creation and accidental overwrites.
    """
    existing_users = db.query(User).first()
    if existing_users:
        return  # ✅ already seeded

    for u in DEFAULT_USERS:
        db.add(
            User(
                id=str(uuid.uuid4()),
                username=u["username"],
                hashed_password=hash_password(u["password"]),
                role=u["role"],
            )
        )
    db.commit()


# -------------------------
# Auth Endpoints
# -------------------------

@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Login and get JWT token",
)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()

    # 🔒 Generic error (prevents username enumeration)
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(
        {
            "sub": user.username,
            "role": user.role,
        }
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        username=user.username,
        role=user.role,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
    )