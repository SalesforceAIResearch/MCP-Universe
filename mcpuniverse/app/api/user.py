"""
API endpoints for users.
"""
import datetime
import os

import bcrypt
import psycopg
import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncConnection
from mcpuniverse.app.db.database import get_connection
from mcpuniverse.app.db.sqlc.user import AsyncQuerier, models
from mcpuniverse.app.utils.token import UserTokenPayload, generate_token
from mcpuniverse.app.utils.limiter import RateLimiter

router = APIRouter()


class CreateUserRequest(BaseModel):
    """Request schema for creating a new user."""
    username: str = Field(description="username", min_length=1)
    email: EmailStr = Field(description="email address")
    password: str = Field(description="password", min_length=1)


class CreateUserResponse(BaseModel):
    """Response schema for creating a new user."""
    id: int = Field(default=0, description="user ID")
    username: str = Field(default="", description="username")
    email: str = Field(default="", description="email address")


class LoginUserRequest(BaseModel):
    """Request schema for user login."""
    email: EmailStr = Field(description="email address")
    password: str = Field(description="password", min_length=1)


class LoginUserResponse(BaseModel):
    """Response schema for user login."""
    username: str = Field(default="", description="username")
    email: str = Field(description="email address")
    access_token: str = Field(description="user access token")
    access_token_expired_at: datetime.datetime = Field(description="user access token expiration time")


@router.post(
    "/user/create",
    response_model=CreateUserResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_USER"]))]
)
async def create_user(
        request: CreateUserRequest,
        conn: AsyncConnection = Depends(get_connection)
):
    """
    Create a new user.
    """
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(request.password.encode(encoding="utf-8"), salt)
    querier = AsyncQuerier(conn)
    try:
        user = await querier.create_user(
            username=request.username,
            email=request.email,
            hashed_password=hashed_password.decode("utf-8"),
            permission=models.UserPerm.DEFAULT,
        )
        return CreateUserResponse(id=user.id, username=user.username, email=user.email)
    except sqlalchemy.exc.IntegrityError as e:
        if isinstance(e.orig, psycopg.errors.UniqueViolation):
            raise HTTPException(status_code=409, detail="User name or email exists") from e


@router.post(
    "/user/login",
    response_model=LoginUserResponse,
    dependencies=[Depends(RateLimiter(rate=os.environ["FORMATTED_RATE_USER"]))]
)
async def login_user(
        request: LoginUserRequest,
        conn: AsyncConnection = Depends(get_connection)
):
    """
    User login.
    """
    querier = AsyncQuerier(conn)
    user = await querier.get_user_by_email(email=request.email)
    if user is None:
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not bcrypt.checkpw(request.password.encode("utf-8"), user.hashed_password.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Wrong email or password")

    issued_at = datetime.datetime.now(datetime.timezone.utc)
    expired_at = issued_at + datetime.timedelta(hours=int(os.getenv("ACCESS_TOKEN_DURATION_HRS", "24")))
    payload = UserTokenPayload(
        id=str(user.id),
        email=user.email,
        permission=user.permission,
        issued_at=issued_at,
        expired_at=expired_at
    )
    return LoginUserResponse(
        username=user.username,
        email=user.email,
        access_token=generate_token(payload),
        access_token_expired_at=payload.expired_at
    )
