"""Reject oversized multipart requests before Starlette creates spooled files."""

from starlette.responses import JSONResponse

from cloudpilot.modules.collection.connectors.csv_import import MAX_UPLOAD


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/imports/csv":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > MAX_UPLOAD + 65536:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "file_too_large",
                            "message": "CSV upload exceeds 2 MiB",
                            "request_id": scope.get("state", {}).get("request_id", "upload-limit"),
                        }
                    },
                )
                return await response(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body"):
                break
        iterator = iter(chunks)

        async def replay():
            return next(iterator, {"type": "http.request", "body": b"", "more_body": False})

        return await self.app(scope, replay, send)
