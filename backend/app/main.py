"""Entrypoint FastAPI (C-01 foundation).

CORS restrictivo + rate-limit global + salud observable (`/health`, `/ready`)
+ routers por dominio (stubs hasta su change).
"""

import re
import time
from collections import defaultdict

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.common.exceptions import register_exception_handlers
from app.core.settings import Settings, get_settings
from app.modules.agenda.router import router as agenda_router
from app.modules.auth.router import router as auth_router
from app.modules.booking_public.router import router as booking_public_router
from app.modules.clinic.router import router as clinic_router
from app.modules.notifications.router import router as notifications_router
from app.modules.reminders.router import router as reminders_router
from app.modules.reports.router import router as reports_router
from app.modules.users.router import router as users_router
from app.modules.waiting_list.router import router as waiting_list_router

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour)\s*$")
_WINDOW = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


def parse_rate_limit(spec: str) -> tuple[int, float]:
    """Parsea `BOOKING_RATE_LIMIT` (`"<n>/<second|minute|hour>"`)."""
    match = _RATE_RE.match(spec)
    if not match:
        raise ValueError(f"BOOKING_RATE_LIMIT inválido: {spec!r}")
    return int(match.group(1)), _WINDOW[match.group(2)]


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit global en memoria (ventana fija por IP).

    Suficiente para C-01; en C-07 el booking usa límites estrictos en Redis.
    """

    def __init__(self, app: FastAPI, max_requests: int, window_s: float) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_s = window_s
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in ("/health", "/ready"):
            return await call_next(request)
        now = time.monotonic()
        key = request.client.host if request.client else "unknown"
        window_start = now - self.window_s
        hits = [t for t in self._hits[key] if t > window_start]
        if len(hits) >= self.max_requests:
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        hits.append(now)
        self._hits[key] = hits
        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fábrica de la app (inyectable en tests)."""
    settings = settings or get_settings()
    max_requests, window_s = parse_rate_limit(settings.BOOKING_RATE_LIMIT)

    app = FastAPI(title="Sistema de Turnos Odontológico", version="0.1.0")

    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )
    app.add_middleware(GlobalRateLimitMiddleware, max_requests=max_requests, window_s=window_s)
    register_exception_handlers(app)

    app.state.settings = settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness: la app corre (sin dependencias)."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> Response:
        """Readiness: Postgres + Redis alcanzables; 503 si alguna cae."""
        unavailable: list[str] = []
        import asyncpg  # diferido para tests sin DB
        import redis.asyncio as aioredis

        try:
            conn = await asyncpg.connect(str(settings.DATABASE_URL), timeout=2)
            await conn.close()
        except Exception:
            unavailable.append("postgres")
        try:
            client = aioredis.from_url(str(settings.REDIS_URL))  # type: ignore[no-untyped-call]
            await client.ping()
            await client.aclose()
        except Exception:
            unavailable.append("redis")
        if unavailable:
            return JSONResponse(
                status_code=503,
                content={"detail": f"unavailable: {', '.join(unavailable)}"},
            )
        return JSONResponse(status_code=200, content={"status": "ready"})

    for router in (
        auth_router,
        clinic_router,
        agenda_router,
        booking_public_router,
        waiting_list_router,
        reminders_router,
        notifications_router,
        users_router,
        reports_router,
    ):
        app.include_router(router)

    return app


app = create_app()
