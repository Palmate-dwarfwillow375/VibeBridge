"""Auth routes — 1:1 port of server/routes/auth.js."""
import bcrypt
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from pydantic import BaseModel

from database.db import user_db
from middleware.auth import generate_token, authenticate_token, set_auth_cookie, clear_auth_cookie

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthRequest(BaseModel):
    username: str
    password: str


@router.get("/status")
async def auth_status():
    has_users = user_db.has_users()
    return {"needsSetup": not has_users, "isAuthenticated": False}


@router.post("/register")
async def register(body: AuthRequest, request: Request, response: Response):
    if not body.username or not body.password:
        raise HTTPException(400, "Username and password are required")
    if len(body.username) < 3 or len(body.password) < 6:
        raise HTTPException(400, "Username must be at least 3 characters, password at least 6 characters")

    try:
        password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt(12)).decode()
        user = user_db.create_user(body.username, password_hash)
        token = generate_token(user) if user_db.is_approved_role(user.get("role")) else None
    except HTTPException:
        raise
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise HTTPException(409, "Username already exists")
        raise HTTPException(500, "Internal server error")

    if token:
        user_db.update_last_login(user["id"])
    if token:
        set_auth_cookie(response, token, request)

    return {
        "success": True,
        "user": {"id": user["id"], "username": user["username"], "role": user.get("role", "user")},
        "pendingApproval": user.get("role") == "pending",
        "message": "Registration submitted. An administrator must approve your account before you can sign in." if user.get("role") == "pending" else None,
    }


@router.post("/login")
async def login(body: AuthRequest, request: Request, response: Response):
    if not body.username or not body.password:
        raise HTTPException(400, "Username and password are required")

    user = user_db.get_user_by_username(body.username)
    if not user:
        raise HTTPException(401, "Invalid username or password")

    if user.get("role") == "pending":
        raise HTTPException(403, "Your registration is pending administrator approval")

    if not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Invalid username or password")

    token = generate_token(user)
    user_db.update_last_login(user["id"])
    set_auth_cookie(response, token, request)
    return {
        "success": True,
        "user": {"id": user["id"], "username": user["username"], "role": user.get("role", "user")},
    }


@router.get("/user")
async def get_user(request: Request, response: Response, _=Depends(authenticate_token)):
    return {"user": request.state.user}


@router.post("/logout")
async def logout(request: Request, response: Response, _=Depends(authenticate_token)):
    clear_auth_cookie(response, request)
    return {"success": True, "message": "Logged out successfully"}
