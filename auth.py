"""UNG-ZIPPER mutation authorization."""
import os
import hmac
from fastapi import Header, HTTPException

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY")

def require_admin_key(x_admin_key: str = Header(None)):
    if not ADMIN_API_KEY:
        raise HTTPException(500, "Server misconfigured: ADMIN_API_KEY not set")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, ADMIN_API_KEY):
        raise HTTPException(401, "Invalid or missing X-Admin-Key header")
    return True
