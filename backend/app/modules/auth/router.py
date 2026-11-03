"""Router de autenticación del personal (C-03).

Routers finos: rate-limit, cookies y traducción HTTP; la lógica vive en
`AuthService`. Prefijo público `/api/auth` (design §16).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.core.deps import get_current_principal, get_db
from app.core.rate_limit import (
    hit,
    login_ip_key,
    login_pair_key,
    parse_window_spec,
    password_key,
    refresh_ip_key,
)
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.modules.auth.cookies import (
    clear_refresh_cookie,
    cleared_cookie_header,
    refresh_cookie_name,
    set_refresh_cookie,
)
from app.modules.auth.schemas import (
    AccessTokenResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserProfile,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PrincipalDep = Annotated[Principal, Depends(get_current_principal)]


async def _consume(redis: Redis, key: str, spec: str) -> None:
    """Consume un cupo de la ventana fija; 429 con `Retry-After` si se excede."""
    limit, window_s = parse_window_spec(spec)
    try:
        resultado = await hit(redis, key, limit, window_s)
    except RedisError:
        raise DomainError(503, "auth_unavailable") from None
    if not resultado.allowed:
        raise DomainError(429, "rate_limited", headers={"Retry-After": str(resultado.retry_after)})


def _check_origin(request: Request, settings: Settings) -> None:
    """CSRF: si el navegador manda `Origin`, debe estar en la allowlist."""
    origin = request.headers.get("Origin")
    if not origin:
        return
    permitidos = {o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()}
    if origin not in permitidos:
        raise DomainError(403, "origin_not_allowed")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> LoginResponse:
    """Autentica al personal y emite access + cookie de refresh."""
    ip = _client_ip(request)
    await _consume(redis, login_pair_key(ip, payload.email), settings.AUTH_LOGIN_RATE_LIMIT)
    await _consume(redis, login_ip_key(ip), settings.AUTH_LOGIN_IP_RATE_LIMIT)

    service = AuthService(session, redis, settings)
    resultado = await service.login(payload.email, payload.password.get_secret_value())
    set_refresh_cookie(response, settings, resultado.refresh_token)
    return LoginResponse(
        access_token=resultado.access_token,
        expires_in=resultado.expires_in,
        user=resultado.profile,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> AccessTokenResponse:
    """Rota el refresh de la cookie y devuelve un access nuevo."""
    _check_origin(request, settings)
    await _consume(redis, refresh_ip_key(_client_ip(request)), settings.AUTH_REFRESH_RATE_LIMIT)

    token = request.cookies.get(refresh_cookie_name(settings))
    if not token:
        raise DomainError(
            401, "invalid_refresh", headers={"Set-Cookie": cleared_cookie_header(settings)}
        )

    service = AuthService(session, redis, settings)
    try:
        resultado = await service.refresh(token)
    except DomainError as exc:
        if exc.status_code == 401 and exc.headers is None:
            exc.headers = {"Set-Cookie": cleared_cookie_header(settings)}
        raise
    set_refresh_cookie(response, settings, resultado.refresh_token)
    return AccessTokenResponse(
        access_token=resultado.access_token,
        expires_in=resultado.expires_in,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> Response:
    """Cierra la sesión del access o, si venció, de la cookie; idempotente."""
    _check_origin(request, settings)
    await _consume(redis, refresh_ip_key(_client_ip(request)), settings.AUTH_REFRESH_RATE_LIMIT)

    service = AuthService(session, redis, settings)
    await service.logout(
        request.headers.get("Authorization"),
        request.cookies.get(refresh_cookie_name(settings)),
    )
    respuesta = Response(status_code=204)
    clear_refresh_cookie(respuesta, settings)
    return respuesta


@router.get("/me", response_model=UserProfile)
async def me(
    principal: PrincipalDep,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> UserProfile:
    """Perfil propio; nunca incluye hash ni tokens."""
    return await AuthService(session, redis, settings).profile(principal)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    principal: PrincipalDep,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> dict[str, str]:
    """Cambia la contraseña propia y cierra las demás sesiones del usuario."""
    await _consume(redis, password_key(principal.user_id), settings.AUTH_PASSWORD_RATE_LIMIT)
    await AuthService(session, redis, settings).change_password(
        principal,
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
    )
    return {"status": "ok"}
