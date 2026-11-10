"""Entrypoint FastAPI (C-01 foundation; borde endurecido en C-14).

Stack de middlewares (de afuera hacia adentro, C-14 D1): contexto del request (request-id, log de
acceso sin PII, 500 uniforme) → headers seguros → hosts confiables → CORS restrictivo →
rate-limit global (Redis compartido, degradación a memoria). Salud observable (`/health`,
`/ready`) y routers por dominio.
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.common.exceptions import register_exception_handlers
from app.core.database import async_database_url, create_engine, create_sessionmaker
from app.core.logs import configure_logging
from app.core.middleware import (
    GlobalRateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    TrustedHostMiddleware,
)
from app.core.redis import create_redis_client
from app.core.settings import Settings, get_settings
from app.modules.agenda.router import router as agenda_router
from app.modules.appointments.router import router as appointments_router
from app.modules.auth.router import router as auth_router
from app.modules.booking_public.router import router as booking_public_router
from app.modules.clinic.router import router as clinic_router
from app.modules.manage.router import router as manage_router
from app.modules.notifications.router import WEBHOOK_PATH
from app.modules.notifications.router import router as notifications_router
from app.modules.patients.router import router as patients_router
from app.modules.reminders.router import router as reminders_router
from app.modules.reports.router import router as reports_router
from app.modules.users.router import router as users_router
from app.modules.waiting_list.public import router as waitlist_offer_router
from app.modules.waiting_list.router import router as waiting_list_router

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour)\s*$")
_WINDOW = {"second": 1.0, "minute": 60.0, "hour": 3600.0}

# C-14 (D1): headers que el navegador puede mandar a la API. Nada de `*`: con credenciales
# (cookie de refresh) un comodín es justamente lo que CORS intenta evitar.
CORS_ALLOW_HEADERS = ["Authorization", "Content-Type", "Accept", "X-Request-ID"]
CORS_EXPOSE_HEADERS = ["X-Request-ID", "Retry-After", "Content-Disposition"]


def parse_rate_limit(spec: str) -> tuple[int, float]:
    """Parsea `BOOKING_RATE_LIMIT` (`"<n>/<second|minute|hour>"`)."""
    match = _RATE_RE.match(spec)
    if not match:
        raise ValueError(f"BOOKING_RATE_LIMIT inválido: {spec!r}")
    return int(match.group(1)), _WINDOW[match.group(2)]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fábrica de la app (inyectable en tests)."""
    settings = settings or get_settings()
    max_requests, window_s = parse_rate_limit(settings.BOOKING_RATE_LIMIT)

    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    engine = create_engine(str(settings.DATABASE_URL), settings, application_name="turnos-api")
    redis_client = create_redis_client(settings)
    en_prod = settings.ENV == "prod"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Cierra el pool de Redis y el engine al apagar el proceso."""
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(
        title="Sistema de Turnos Odontológico",
        version="0.1.0",
        lifespan=lifespan,
        # C-14: en prod la API no publica su esquema ni la consola interactiva.
        docs_url=None if en_prod else "/docs",
        redoc_url=None if en_prod else "/redoc",
        openapi_url=None if en_prod else "/openapi.json",
    )

    # `add_middleware` apila hacia afuera: el último agregado es el primero en ver el request.
    app.add_middleware(
        GlobalRateLimitMiddleware,
        max_requests=max_requests,
        window_s=window_s,
        exempt_paths=(WEBHOOK_PATH,),
        redis_getter=(None if settings.GLOBAL_RATE_LIMIT_BACKEND == "redis" else _no_redis),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=CORS_ALLOW_HEADERS,
        expose_headers=CORS_EXPOSE_HEADERS,
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts or ["*"])
    app.add_middleware(SecurityHeadersMiddleware, hsts_seconds=settings.hsts_seconds)
    app.add_middleware(RequestContextMiddleware, hsts_seconds=settings.hsts_seconds)
    register_exception_handlers(app)

    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis_client

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness: la app corre (sin dependencias)."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> Response:
        """Readiness: Postgres + Redis alcanzables; 503 si alguna cae."""
        unavailable: list[str] = []
        import asyncpg  # diferido para tests sin DB

        try:
            # asyncpg usa el DSN plano: se quita el sufijo de driver de SQLAlchemy.
            dsn = async_database_url(str(settings.DATABASE_URL)).replace("+asyncpg", "", 1)
            conn = await asyncpg.connect(dsn, timeout=2)
            await conn.close()
        except Exception:
            unavailable.append("postgres")
        try:
            # Cliente compartido de la app: no se crea uno por request.
            await app.state.redis.ping()
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
        appointments_router,
        patients_router,
        booking_public_router,
        manage_router,
        waiting_list_router,
        waitlist_offer_router,
        reminders_router,
        notifications_router,
        users_router,
        reports_router,
    ):
        app.include_router(router)

    return app


def _no_redis(_: object) -> None:
    """`GLOBAL_RATE_LIMIT_BACKEND=memory`: el middleware cuenta por proceso."""
    return None


app = create_app()
