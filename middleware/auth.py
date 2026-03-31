"""JWT authentication middleware — 1:1 port of server/middleware/auth.js."""
import time
from typing import Optional

import jwt
from fastapi import Request, Response, HTTPException

from database.db import user_db, app_config_db
from config import IS_PLATFORM, MAIN_SERVER_URL, MAIN_REGISTER_URL, JWT_SECRET_VALUE

# JWT secret: config file > auto-generated per installation
JWT_SECRET = JWT_SECRET_VALUE or app_config_db.get_or_create_jwt_secret()
AUTH_COOKIE_NAME = "auth_token"
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def generate_token(user: dict) -> str:
    now = int(time.time())
    payload = {
        "userId": user["id"],
        "username": user["username"],
        "role": user.get("role", "user"),
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _verify_token(token: str) -> Optional[dict]:
    """Verify JWT and return decoded payload, or None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _is_secure_request(conn) -> bool:
    forwarded_proto = ""
    headers = getattr(conn, "headers", None)
    if headers is not None:
        forwarded_proto = headers.get("x-forwarded-proto", "")
    scheme = getattr(getattr(conn, "url", None), "scheme", "")
    return forwarded_proto.lower() == "https" or scheme.lower() == "https"


def set_auth_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        secure=_is_secure_request(request),
        samesite="lax",
    )


def extract_auth_token(request: Request) -> Optional[str]:
    return request.cookies.get(AUTH_COOKIE_NAME)


def authenticate_websocket(connection) -> Optional[dict]:
    """WebSocket authentication — returns user dict or None."""
    if IS_PLATFORM:
        user = user_db.get_first_user()
        if user:
            return {"userId": user["id"], "username": user["username"], "role": user.get("role", "user")}
        return None

    cookies = getattr(connection, "cookies", None) or {}
    token = cookies.get(AUTH_COOKIE_NAME)

    if not token:
        return None

    decoded = _verify_token(token)
    if not decoded:
        return None

    user = user_db.get_user_by_id(decoded["userId"])
    if not user:
        return None
    return {"userId": user["id"], "username": user["username"], "role": user.get("role", "user")}


async def authenticate_token(
    request: Request,
    response: Response,
):
    """FastAPI dependency that mimics Express authenticateToken middleware."""

    # Node mode: trust Main to forward the already-authenticated browser user.
    if MAIN_SERVER_URL or MAIN_REGISTER_URL:
        forwarded_user_id = request.headers.get("x-authenticated-user-id")
        forwarded_username = request.headers.get("x-authenticated-username")
        forwarded_role = request.headers.get("x-authenticated-role")

        if forwarded_user_id and forwarded_username:
            try:
                user = user_db.ensure_shadow_user(int(forwarded_user_id), forwarded_username)
            except ValueError as exc:
                raise HTTPException(400, "Invalid forwarded user context") from exc

            if forwarded_role in {"creator", "admin", "user", "pending"} and user.get("role") != forwarded_role:
                user["role"] = forwarded_role

            request.state.user = user
            return user

        # Fallback for internal Node-only calls that do not originate from Main.
        request.state.user = {"id": 0, "username": "node"}
        return request.state.user

    # Platform mode: use first DB user
    if IS_PLATFORM:
        user = user_db.get_first_user()
        if not user:
            raise HTTPException(500, "Platform mode: No user found in database")
        request.state.user = user
        return user

    token = extract_auth_token(request)
    if not token:
        raise HTTPException(401, "Access denied. No token provided.")

    decoded = _verify_token(token)
    if not decoded:
        raise HTTPException(403, "Invalid token")

    user = user_db.get_user_by_id(decoded["userId"])
    if not user:
        raise HTTPException(401, "Invalid token. User not found.")

    # Auto-refresh: if past halfway through lifetime
    exp = decoded.get("exp")
    iat = decoded.get("iat")
    if exp and iat:
        now = int(time.time())
        half_life = (exp - iat) / 2
        if now > iat + half_life:
            new_token = generate_token(user)
            set_auth_cookie(response, new_token, request)

    request.state.user = user
    return user


def require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def require_staff(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user.get("role") not in {"creator", "admin"}:
        raise HTTPException(403, "Staff access required")
    return user


def require_creator(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "creator":
        raise HTTPException(403, "Creator access required")
    return user
