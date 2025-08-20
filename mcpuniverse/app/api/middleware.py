"""
API middlewares.
"""
# pylint: disable=broad-exception-caught,too-few-public-methods,too-many-return-statements
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from mcpuniverse.app.utils.token import verify_token


class AuthMiddleware(BaseHTTPMiddleware):
    """
    The middleware for authentication.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Middleware dispatch function.
        """
        if request.url.path in ["/user/create", "/user/login"]:
            return await call_next(request)
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(status_code=401, content={"detail": "Authorization header missing"})
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Invalid authorization header"})
        try:
            token = auth_header.split(" ")[1]
            payload = verify_token(token)
        except Exception as e:
            return JSONResponse(status_code=401, content={"detail": str(e)})
        if request.url.path.startswith("/admin") and payload.permission != "admin":
            return JSONResponse(status_code=401, content={"detail": "Permission denied"})
        if request.url.path.startswith("/internal") and payload.permission not in ["internal", "admin"]:
            return JSONResponse(status_code=401, content={"detail": "Permission denied"})

        headers = dict(request.scope["headers"])
        headers[b"x-user-id"] = payload.id.encode(encoding="utf-8")
        headers[b"x-user-permission"] = payload.permission.encode(encoding="utf-8")
        request.scope["headers"] = list(headers.items())
        return await call_next(request)
