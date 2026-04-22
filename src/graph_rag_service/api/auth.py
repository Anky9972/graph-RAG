"""
Authentication and authorization
JWT-based authentication with role-based access control
"""

from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from ..config import settings

# Security
security = HTTPBearer()


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None
    scopes: list = []


class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: bool = False
    scopes: list = []


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password hash"""
    try:
        # bcrypt requires bytes, truncate to 72 bytes as per bcrypt spec
        password_bytes = plain_password.encode('utf-8')[:72]
        return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    """Hash password"""
    password_bytes = password.encode('utf-8')[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token
    
    Args:
        data: Token payload data
        expires_delta: Optional expiration time
        
    Returns:
        JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.algorithm
    )
    
    return encoded_jwt


def decode_token(token: str) -> TokenData:
    """
    Decode and validate JWT token
    
    Args:
        token: JWT token string
        
    Returns:
        TokenData with username and scopes
        
    Raises:
        HTTPException if token is invalid
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        
        token_data = TokenData(
            username=username,
            scopes=payload.get("scopes", [])
        )
        return token_data
    except JWTError:
        raise credentials_exception


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    Get current user from JWT token
    
    Args:
        credentials: Authorization credentials from header
        
    Returns:
        Current user
        
    Raises:
        HTTPException if authentication fails
    """
    token = credentials.credentials
    token_data = decode_token(token)
    
    # In production, fetch user from database
    # For now, return a mock user
    user = User(
        username=token_data.username,
        scopes=token_data.scopes
    )
    
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    return user


def check_scope(required_scope: str):
    """
    Dependency to check if user has required scope
    
    Args:
        required_scope: Required scope/permission
        
    Returns:
        Dependency function
    """
    
    async def scope_checker(current_user: User = Depends(get_current_user)):
        if required_scope not in current_user.scopes and "admin" not in current_user.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions"
            )
        return current_user
    
    return scope_checker
