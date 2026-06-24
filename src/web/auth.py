"""
Authentication Module.

Handles user authentication and session management.
"""

import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response, Depends, status
from fastapi.security import HTTPBasic
from pydantic import BaseModel
from loguru import logger

from src.core.config import get_config


# ==============================================================================
# MODELS
# ==============================================================================

class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response model."""
    success: bool
    message: str
    username: Optional[str] = None
    role: Optional[str] = None


class UserInfo(BaseModel):
    """User information model."""
    username: str
    role: str


# ==============================================================================
# SESSION STORE
# ==============================================================================

class SessionStore:
    """In-memory session storage."""
    
    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._config = get_config()
    
    def create_session(self, username: str, role: str) -> str:
        """Create new session and return session ID."""
        session_id = secrets.token_urlsafe(32)
        
        secrets_config = self._config.load_secrets()
        expire_hours = secrets_config.mcp_server.session_expire_hours
        
        self._sessions[session_id] = {
            "username": username,
            "role": role,
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(hours=expire_hours)
        }
        
        logger.info(f"Session created for user: {username}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[dict]:
        """Get session by ID if valid."""
        if session_id not in self._sessions:
            return None
        
        session = self._sessions[session_id]
        
        if datetime.now() > session["expires_at"]:
            del self._sessions[session_id]
            return None
        
        return session
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session."""
        if session_id in self._sessions:
            username = self._sessions[session_id]["username"]
            del self._sessions[session_id]
            logger.info(f"Session deleted for user: {username}")
            return True
        return False
    
    def cleanup_expired(self) -> int:
        """Remove expired sessions."""
        now = datetime.now()
        expired = [
            sid for sid, session in self._sessions.items()
            if now > session["expires_at"]
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)


_session_store = SessionStore()


def get_session_store() -> SessionStore:
    """Get session store instance."""
    return _session_store


# ==============================================================================
# PASSWORD UTILITIES
# ==============================================================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    try:
        if hashed.startswith('$2b$') or hashed.startswith('$2a$'):
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        else:
            return password == hashed
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


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
    
    session_store = get_session_store()
    session = session_store.get_session(session_id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )
    
    return UserInfo(
        username=session["username"],
        role=session["role"]
    )


async def require_admin(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    """Dependency to require admin role (superadmin also allowed)."""
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


async def require_superadmin(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    """Dependency to require superadmin role."""
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
    user = authenticate_user(request.username, request.password)
    
    if not user:
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
    
    get_audit_logger().log(
        action="login",
        username=user["username"],
        role=user["role"],
        ip=client_ip,
        success=True,
    )
    
    session_store = get_session_store()
    session_id = session_store.create_session(user["username"], user["role"])
    
    config = get_config()
    secrets = config.load_secrets()
    max_age = secrets.mcp_server.session_expire_hours * 3600
    
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        max_age=max_age,
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
    
    session_store = get_session_store()
    session = session_store.get_session(session_id)
    
    if not session:
        return {"authenticated": False}
    
    return {
        "authenticated": True,
        "username": session["username"],
        "role": session["role"]
    }
