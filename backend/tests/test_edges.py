"""Bordes API: validación estricta Pydantic v2 + envolvente uniforme de errores."""

import httpx
import pytest
from app.main import create_app


@pytest.fixture()
def app() -> object:
    """App de test (sin DB: los 422 de borde se resuelven en validación)."""
    return create_app()


async def test_campo_extra_rechazado_con_422(app: object) -> None:
    """WHEN campo no declarado en el login THEN 422 {"detail":...} sin traza."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "staff.ficticio@example.com",
                "password": "clave-ficticia-123",
                "campo_fantasma": 1,
            },
        )
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert "Traceback" not in str(body)


async def test_login_sin_password_es_422(app: object) -> None:
    """WHEN falta un campo obligatorio del login THEN 422 de validación."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post(
            "/api/auth/login", json={"email": "staff.ficticio@example.com"}
        )
    assert response.status_code == 422


async def test_stubs_de_auth_eliminados(app: object) -> None:
    """WHEN se llama el viejo stub THEN ya no existe (404)."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post("/auth/echo", json={"ping": "ok"})
    assert response.status_code == 404


async def test_rate_limit_global_activo(app: object) -> None:
    """El rate-limit global responde 429 con envolvente {"detail":...} al excederse."""
    from app.core.settings import get_settings

    settings = get_settings()
    settings.BOOKING_RATE_LIMIT = "2/minute"
    limited = create_app(settings)
    transport = httpx.ASGITransport(app=limited)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        await client.get("/openapi.json")
        await client.get("/openapi.json")
        response = await client.get("/openapi.json")
    assert response.status_code == 429
    assert "detail" in response.json()


# ------------------------------------------------------------------ regla 2 (C-10, D2)

# Única excepción documentada a la regla 2 (AGENTS.md/CLAUDE.md): el payload de Meta, que se parsea
# solo después de verificar la firma del webhook.
_EXCEPCION_REGLA_2 = frozenset({"app.modules.notifications.payload"})


def _modelos_de_la_app() -> list[type]:
    import importlib
    import pkgutil

    import app
    from pydantic import BaseModel
    from pydantic_settings import BaseSettings

    for modulo in pkgutil.walk_packages(app.__path__, "app."):
        if modulo.name in ("app.main",):
            continue
        importlib.import_module(modulo.name)

    def _todas(clase: type) -> list[type]:
        hijas = clase.__subclasses__()
        return hijas + [n for h in hijas for n in _todas(h)]

    return [
        modelo
        for modelo in _todas(BaseModel)
        if modelo.__module__.startswith("app.")
        and not issubclass(modelo, BaseSettings)
        and "[" not in modelo.__name__  # genéricos parametrizados
    ]


def _relajado(modelo: type) -> bool:
    """Declara `extra` y no es `forbid` (los modelos de respuesta sin `extra` no cuentan)."""
    extra = modelo.model_config.get("extra")  # type: ignore[attr-defined]
    return extra is not None and extra != "forbid"


def _infractores(excepciones: frozenset[str]) -> list[str]:
    return sorted(
        f"{m.__module__}.{m.__name__}"
        for m in _modelos_de_la_app()
        if _relajado(m) and m.__module__ not in excepciones
    )


def test_ningun_schema_relaja_extra_salvo_el_payload_de_meta() -> None:
    assert _infractores(_EXCEPCION_REGLA_2) == []


def test_la_excepcion_existe_y_es_la_unica_relajada() -> None:
    relajados = {m.__module__ for m in _modelos_de_la_app() if _relajado(m)}

    assert relajados == set(_EXCEPCION_REGLA_2)


def test_el_chequeo_detecta_un_modelo_relajado_fuera_de_la_excepcion() -> None:
    """Prueba del propio test: un modelo temporal con `ignore` en otro módulo se detecta."""
    import sys
    import types

    from pydantic import BaseModel, ConfigDict

    modulo = types.ModuleType("app.modules.temporal_regla_2")
    sys.modules[modulo.__name__] = modulo
    try:
        relajado = type(
            "Relajado",
            (BaseModel,),
            {"model_config": ConfigDict(extra="ignore"), "__module__": modulo.__name__},
        )
        assert relajado is not None
        assert "app.modules.temporal_regla_2.Relajado" in _infractores(_EXCEPCION_REGLA_2)
    finally:
        del sys.modules[modulo.__name__]
