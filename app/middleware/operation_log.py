from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging_config import get_logger

logger = get_logger("middleware")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        request.state.trace_id = trace_id
        start = time.time()
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Process-Time"] = f"{time.time() - start:.4f}"
        return response


class OperationLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            path = request.url.path
            if not any(skip in path for skip in ("/health", "/docs", "/openapi", "/ws/")):
                logger.info("Operation", extra={"method": request.method, "path": path})
        return await call_next(request)
