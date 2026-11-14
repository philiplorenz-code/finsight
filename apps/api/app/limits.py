"""Reject oversized bodies while streaming, before multipart spooling."""
from fastapi import HTTPException
from starlette.responses import JSONResponse

from .config import settings


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_upload = scope["path"] in {"/api/imports", "/api/imports/preview"}
        limit = settings.max_upload_bytes + 65536 if is_upload else 65536
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length")
        try:
            too_large = declared is not None and (int(declared) < 0 or int(declared) > limit)
        except ValueError:
            too_large = True
        if too_large:
            return await JSONResponse({"detail": "Request body exceeds limit"}, status_code=413)(scope, receive, send)
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise HTTPException(413, "Request body exceeds limit")
            return message

        await self.app(scope, bounded_receive, send)
