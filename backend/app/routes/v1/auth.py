import secrets
from datetime import datetime, timedelta, timezone

from typing import Annotated, Optional
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

import jwt
from pwdlib import PasswordHash
from jwt.exceptions import InvalidTokenError
from sqlalchemy.exc import IntegrityError

from app.core.settings import settings
from app.core.database import get_session, User
from app.schemas import MessageOutput, UserRegister, UserResponse, UserStatsResponse
from app.models_db import Dataset, Vocabulary, RefreshToken
from sqlmodel import Session, select, func

import requests

BIONER_URL = "http://localhost:5600"


# ================================================
# Token classes
# ================================================


class TokenData(BaseModel):
    """Internal model for decoded JWT token data."""

    username: str


class Token(BaseModel):
    """OAuth2 token response model."""

    access_token: str
    refresh_token: str
    token_type: str


class RefreshRequest(BaseModel):
    """Request model for token refresh."""

    refresh_token: str


# ================================================
# Helper functions
# ================================================

password_hash = PasswordHash.recommended()


def get_password_hash(password: str) -> str:
    """Hash a plain text password using the recommended hashing algorithm.

    Args:
        password: Plain text password to hash

    Returns:
        Hashed password
    """
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a hashed password.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to verify against

    Returns:
        True if password is verified, False otherwise
    """
    return password_hash.verify(plain_password, hashed_password)


# ================================================
# Security functions
# ================================================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_user(db, username: str):
    """
    Retrieve a user from the database by username.

    Args:
        db: Database session
        username: Username to look up

    Returns:
        User object if found, None otherwise
    """
    statement = select(User).where(User.username == username)
    user = db.exec(statement).one_or_none()
    return user


def authenticate_user(db: Session, username: str, password: str):
    """
    Authenticate a user by username and password.

    Args:
        db: Database session
        username: Username to authenticate
        password: Plain text password to verify

    Returns:
        User object if authentication successful, False otherwise
    """
    user = get_user(db, username)

    if user is None:
        return False

    if not verify_password(password, user.hashed_password):
        return False

    return user


def create_access_token(data: dict, expires_delta: timedelta = None):
    """
    Create a JWT access token.

    Args:
        data: Dictionary of claims to encode in the token
        expires_delta: Optional expiration time delta (defaults to 15 minutes)

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(db: Session, user: User) -> str:
    """
    Create a refresh token and store it in the database.

    Args:
        db: Database session
        user: User to create refresh token for

    Returns:
        Refresh token string
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    refresh_token = RefreshToken(
        token=token,
        user_id=user.id,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(refresh_token)
    db.commit()

    return token


def validate_refresh_token(db: Session, token: str) -> Optional[RefreshToken]:
    """
    Validate a refresh token and return it if valid.

    Args:
        db: Database session
        token: Refresh token string

    Returns:
        RefreshToken object if valid, None otherwise
    """
    statement = select(RefreshToken).where(
        RefreshToken.token == token,
        RefreshToken.revoked == False,
        RefreshToken.expires_at > datetime.now(timezone.utc),
    )
    return db.exec(statement).one_or_none()


def revoke_refresh_token(db: Session, token: str) -> bool:
    """
    Revoke a refresh token.

    Args:
        db: Database session
        token: Refresh token string

    Returns:
        True if token was revoked, False if not found
    """
    statement = select(RefreshToken).where(RefreshToken.token == token)
    refresh_token = db.exec(statement).one_or_none()

    if refresh_token:
        refresh_token.revoked = True
        db.add(refresh_token)
        db.commit()
        return True

    return False


def revoke_all_user_refresh_tokens(db: Session, user_id: int) -> int:
    """
    Revoke all refresh tokens for a user.

    Args:
        db: Database session
        user_id: User ID to revoke tokens for

    Returns:
        Number of tokens revoked
    """
    statement = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False,
    )
    tokens = db.exec(statement).all()

    for token in tokens:
        token.revoked = True
        db.add(token)

    db.commit()
    return len(tokens)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_session)],
):
    """
    Dependency to get the current authenticated user from JWT token.

    Args:
        token: JWT token from Authorization header
        db: Database session

    Returns:
        Authenticated User object

    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except InvalidTokenError:
        raise credentials_exception
    user = get_user(db, token_data.username)
    if user is None:
        raise credentials_exception
    return user


# ================================================
# Route definitions
# ================================================

router = APIRouter()


@router.post(
    "/register",
    response_model=MessageOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Creates a new user account with username and password. Password must meet complexity requirements (minimum 8 characters, at least one uppercase letter, one lowercase letter, and one digit)",
    response_description="Confirmation message that the user was registered successfully",
)
async def register(user_data: UserRegister, db: Session = Depends(get_session)):
    # Check if username already exists
    existing_user = get_user(db, user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Hash password and create user
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username,
        hashed_password=hashed_password,
        disabled=False,
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    return MessageOutput(message="User registered successfully")


@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Login and get access token",
    description="Authenticates a user with username and password via OAuth2 password flow. Returns JWT access and refresh tokens for subsequent API requests and updates the user's last login timestamp",
    response_description="JWT access token, refresh token, and token type (bearer)",
)
async def login2(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_session),
):
    user = authenticate_user(
        db, username=form_data.username, password=form_data.password
    )
    if not user:
        # Generic error message to prevent username enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is disabled
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    

    # Update last login timestamp
    user.last_login = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    # Create refresh token
    refresh_token = create_refresh_token(db, user)

    try:
        requests.post(
        f"{BIONER_URL}/models/load-user",
        json={"user_id": user.id},
        timeout=1.0
        )
    except Exception as e:
        # do NOT block login if inference service is down
        logger.warning(f"Failed to notify bioner: {e}")


    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


# backend/app/routes/auth.py

import requests
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, status, Depends
from sqlmodel import Session

from app.models_db import UserModelPreference
from app.core.database import get_session


BIONER_URL = "http://localhost:5600"


async def login(
    form_data,
    db: Session = Depends(get_session),
):
    user = authenticate_user(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(401, "Incorrect username or password")

    if user.disabled:
        raise HTTPException(403, "Account disabled")

    # -------------------------
    # 1. READ USER PREFERENCE
    # -------------------------
    pref = (
        db.query(UserModelPreference)
        .filter(UserModelPreference.user_id == user.id)
        .first()
    )

    model_path = (
        pref.model.model_path
        if pref and pref.model
        else "urchade/gliner_small"
    )

    # -------------------------
    # 2. NOTIFY BIONER
    # -------------------------
    try:
        requests.post(
            f"{BIONER_URL}/models/load-user",
            json={"model_path": model_path},
            timeout=1.0,
        )
    except Exception as e:
        print(f"Bioner not reachable: {e}")

    # -------------------------
    # 3. UPDATE LOGIN TIME
    # -------------------------
    user.last_login = datetime.now(timezone.utc)
    db.add(user)
    db.commit()

    # -------------------------
    # 4. RETURN TOKEN
    # -------------------------
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=30),
    )

    refresh_token = create_refresh_token(db, user)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }

@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user information",
    description="Retrieves the profile of the currently authenticated user based on their JWT token. Returns user information excluding sensitive data such as the hashed password",
    response_description="User profile with id, username, disabled status, and timestamps",
)
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_user)],
):
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        disabled=current_user.disabled,
        created_at=current_user.created_at,
        last_login=current_user.last_login,
    )


@router.get(
    "/me/statistics",
    response_model=UserStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user statistics",
    description="Retrieves statistics for the currently authenticated user, including counts of datasets and vocabularies they have uploaded",
    response_description="User statistics with dataset and vocabulary counts",
)
async def read_user_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_session),
):
    # Count datasets owned by user
    dataset_count = db.exec(
        select(func.count(Dataset.id)).where(Dataset.user_id == current_user.id)
    ).one()

    # Count vocabularies owned by user
    vocabulary_count = db.exec(
        select(func.count(Vocabulary.id)).where(Vocabulary.user_id == current_user.id)
    ).one()

    return UserStatsResponse(
        dataset_count=dataset_count,
        vocabulary_count=vocabulary_count,
    )


@router.post(
    "/refresh",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Exchanges a valid refresh token for a new access token and refresh token pair. The old refresh token is revoked.",
    response_description="New JWT access token, refresh token, and token type (bearer)",
)
async def refresh_token(
    request: RefreshRequest,
    db: Session = Depends(get_session),
):
    # Validate the refresh token
    refresh_token_obj = validate_refresh_token(db, request.refresh_token)

    if not refresh_token_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get the user
    user = db.exec(
        select(User).where(User.id == refresh_token_obj.user_id)
    ).one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    # Revoke the old refresh token (token rotation)
    revoke_refresh_token(db, request.refresh_token)

    # Create new access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    # Create new refresh token
    new_refresh_token = create_refresh_token(db, user)

    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


@router.post(
    "/logout",
    response_model=MessageOutput,
    status_code=status.HTTP_200_OK,
    summary="Logout and revoke refresh token",
    description="Revokes the provided refresh token, effectively logging out the user from that session.",
    response_description="Confirmation message",
)
async def logout(
    request: RefreshRequest,
    db: Session = Depends(get_session),
):
    revoked = revoke_refresh_token(db, request.refresh_token)

    if not revoked:
        # Still return success even if token not found (already logged out)
        return MessageOutput(message="Logged out successfully")

    return MessageOutput(message="Logged out successfully")
