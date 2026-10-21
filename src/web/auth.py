"""
Authentication Module.

Handles user authentication and session management.
"""

import hashlib
import json
import math
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, Depends, status
from pydantic import BaseModel
from loguru import logger

from src.core.config import get_config, SESSIONS_DIR


# ==============================================================================
# MODELS
# ==============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: str
    username: Optional[str] = None
    role: Optional[str] = None


class UserInfo(BaseModel):
    username: str
    role: str


class ChangePasswordRequest(BaseModel):
    """Self-service password change request."""
    current_password: str
    new_password: str


# ==============================================================================
# SESSION STORE
# ==============================================================================

SESSIONS_FILE = SESSIONS_DIR / "web_sessions.json"


def _token_key(session_id: str) -> str:
    """Sessions are stored by token hash, so the file never holds usable cookies."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


class SessionStore:
    """Session storage persisted to disk so restarts do not log everyone out."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or SESSIONS_FILE
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._config = get_config()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            now = datetime.now()
            for key, s in raw.items():
                expires_at = datetime.fromisoformat(s["expires_at"])
                if expires_at > now:
                    self._sessions[key] = {
                        "username": s["username"],
                        "role": s["role"],
                        "created_at": datetime.fromisoformat(s["created_at"]),
                        "expires_at": expires_at,
                    }
            logger.info(f"Session store loaded: {len(self._sessions)} active sessions")
        except Exception as e:
            logger.error(f"Failed to load session store, starting empty: {e}")
            self._sessions = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            key: {
                "username": s["username"],
                "role": s["role"],
                "created_at": s["created_at"].isoformat(),
                "expires_at": s["expires_at"].isoformat(),
            }
            for key, s in self._sessions.items()
        }
        tmp = self._path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self._path)

    def create_session(self, username: str, role: str) -> str:
        session_id = secrets.token_urlsafe(32)
        expire_hours = self._config.load_secrets().mcp_server.session_expire_hours
        now = datetime.now()
        with self._lock:
            self._sessions[_token_key(session_id)] = {
                "username": username,
                "role": role,
                "created_at": now,
                "expires_at": now + timedelta(hours=expire_hours),
            }
            self._save()
        logger.info(f"Session created for user: {username}")
        return session_id

    def get_session(self, session_id: str) -> Optional[dict]:
        key = _token_key(session_id)
        session = self._sessions.get(key)
        if session is None:
            return None
        if datetime.now() > session["expires_at"]:
            with self._lock:
                self._sessions.pop(key, None)
                self._save()
            return None
        return session

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(_token_key(session_id), None)
            if session is None:
                return False
            self._save()
        logger.info(f"Session deleted for user: {session['username']}")
        return True

    def delete_user_sessions(self, username: str, keep_session_id: Optional[str] = None) -> int:
        """End every session of a user, optionally keeping the caller's own one."""
        keep = _token_key(keep_session_id) if keep_session_id else None
        with self._lock:
            doomed = [k for k, s in self._sessions.items() if s["username"] == username and k != keep]
            for k in doomed:
                del self._sessions[k]
            if doomed:
                self._save()
        return len(doomed)

    def cleanup_expired(self) -> int:
        now = datetime.now()
        with self._lock:
            expired = [k for k, s in self._sessions.items() if now > s["expires_at"]]
            for k in expired:
                del self._sessions[k]
            if expired:
                self._save()
        return len(expired)


_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


# ==============================================================================
# LOGIN THROTTLING
# ==============================================================================

class LoginThrottle:
    """Locks a username or client IP out after repeated failed logins."""

    def __init__(self, max_attempts: int, lockout: timedelta):
        self.max_attempts = max_attempts
        self.lockout = lockout
        self._lock = threading.Lock()
        self._failures: dict[str, list[datetime]] = {}

    def _recent(self, key: str, now: datetime) -> list[datetime]:
        recent = [t for t in self._failures.get(key, []) if now - t < self.lockout]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, *keys: str) -> int:
        """Seconds until the caller may try again, or 0 if not locked out."""
        now = datetime.now()
        with self._lock:
            wait = 0
            for key in keys:
                recent = self._recent(key, now)
                if len(recent) >= self.max_attempts:
                    wait = max(wait, math.ceil((recent[0] + self.lockout - now).total_seconds()))
            return wait

    def record_failure(self, *keys: str) -> None:
        now = datetime.now()
        with self._lock:
            for key in keys:
                self._failures.setdefault(key, []).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)


_login_throttle: Optional[LoginThrottle] = None


def get_login_throttle() -> LoginThrottle:
    global _login_throttle
    if _login_throttle is None:
        cfg = get_config().load_secrets().mcp_server
        _login_throttle = LoginThrottle(
            max_attempts=cfg.login_max_attempts,
            lockout=timedelta(minutes=cfg.login_lockout_minutes),
        )
    return _login_throttle


def _throttle_keys(username: str, client_ip: Optional[str]) -> list[str]:
    keys = [f"user:{username.strip().lower()}"]
    if client_ip:
        keys.append(f"ip:{client_ip}")
    return keys


# ==============================================================================
# AUTHENTICATION
# ==============================================================================

def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Authenticate user against the user store.

    Returns user dict if successful, None otherwise.
    """
    from src.web.users import get_user_store

    result = get_user_store().verify(username, password)
    if result is None:
        logger.warning(f"Failed authentication for user: {username}")
    return result


# ==============================================================================
# DEPENDENCIES
# ==============================================================================

def _resolve_session(session_id: str) -> Optional[UserInfo]:
    """Map a session cookie to the user, using the role currently in the user store.

    Reading the role on every request means a demotion takes effect at once, and a
    deleted user's sessions stop working instead of living until they expire.
    """
    from src.web.users import get_user_store

    store = get_session_store()
    session = store.get_session(session_id)
    if not session:
        return None
    role = get_user_store().get_role(session["username"])
    if role is None:
        store.delete_session(session_id)
        return None
    return UserInfo(username=session["username"], role=role)


async def get_current_user(request: Request) -> UserInfo:
    """
    Dependency to get current authenticated user.

    Raises HTTPException if not authenticated.
    """
    session_id = request.cookies.get("session_id")

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    user = _resolve_session(session_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )
    return user


async def require_admin(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    """Dependency to require admin role (superadmin also allowed)."""
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


async def require_superadmin(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    if user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin access required"
        )
    return user


# ==============================================================================
# ROUTER
# ==============================================================================

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response, http_request: Request):
    """
    Authenticate user and create session.

    Sets session cookie on successful authentication.
    """
    from src.web.audit import get_audit_logger

    client_ip = http_request.client.host if http_request.client else None
    throttle = get_login_throttle()
    throttle_keys = _throttle_keys(request.username, client_ip)

    wait = throttle.retry_after(*throttle_keys)
    if wait:
        get_audit_logger().log(
            action="login_locked",
            username=request.username,
            ip=client_ip,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed logins. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    user = authenticate_user(request.username, request.password)

    if not user:
        throttle.record_failure(*throttle_keys)
        logger.warning(f"Failed login attempt for user: {request.username}")
        get_audit_logger().log(
            action="login_failed",
            username=request.username,
            ip=client_ip,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    throttle.reset(f"user:{request.username.strip().lower()}")
    get_audit_logger().log(
        action="login",
        username=user["username"],
        role=user["role"],
        ip=client_ip,
        success=True,
    )

    session_store = get_session_store()
    session_id = session_store.create_session(user["username"], user["role"])

    server_cfg = get_config().load_secrets().mcp_server

    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=server_cfg.cookie_secure,
        max_age=server_cfg.session_expire_hours * 3600,
        samesite="lax"
    )

    return LoginResponse(
        success=True,
        message="Login successful",
        username=user["username"],
        role=user["role"]
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """
    Logout user and delete session.
    """
    session_id = request.cookies.get("session_id")

    if session_id:
        session_store = get_session_store()
        session = session_store.get_session(session_id)
        if session:
            from src.web.audit import get_audit_logger
            get_audit_logger().log(
                action="logout",
                username=session["username"],
                role=session["role"],
                ip=request.client.host if request.client else None,
                success=True,
            )
        session_store.delete_session(session_id)

    response.delete_cookie("session_id")

    return {"success": True, "message": "Logged out"}


@router.post("/change-password")
async def change_own_password(
    body: ChangePasswordRequest,
    request: Request,
    user: UserInfo = Depends(get_current_user),
):
    """Change the current user's own password (requires the current one)."""
    from src.web.users import get_user_store
    from src.web.audit import get_audit_logger

    store = get_user_store()
    client_ip = request.client.host if request.client else None

    if store.verify(user.username, body.current_password) is None:
        get_audit_logger().log(
            action="password_change_self",
            username=user.username,
            role=user.role,
            detail="wrong current password",
            ip=client_ip,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current one"
        )

    try:
        store.set_password(user.username, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    get_session_store().delete_user_sessions(user.username, keep_session_id=request.cookies.get("session_id"))
    get_audit_logger().log(
        action="password_change_self",
        username=user.username,
        role=user.role,
        ip=client_ip,
        success=True,
    )
    logger.info(f"User {user.username} changed own password")
    return {"success": True, "message": "Password changed"}


@router.get("/me", response_model=UserInfo)
async def get_me(user: UserInfo = Depends(get_current_user)):
    """Get current user information."""
    return user


@router.get("/check")
async def check_auth(request: Request):
    """Check if user is authenticated."""
    session_id = request.cookies.get("session_id")

    if not session_id:
        return {"authenticated": False}

    user = _resolve_session(session_id)
    if not user:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "username": user.username,
        "role": user.role
    }
