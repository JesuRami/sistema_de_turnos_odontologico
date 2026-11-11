"""Guardia de RBAC (C-14, D6): toda ruta `/api/*` exige un principal autenticado salvo la lista
blanca explícita de bordes públicos. Una ruta nueva sin protección rompe este test.

Sin base ni Redis: recorre el árbol de dependencias de FastAPI.
"""

from __future__ import annotations

from collections.abc import Iterator

from app.core.deps import get_current_principal
from app.main import create_app
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

# Bordes públicos (C-03 auth, C-07 reserva, C-08 gestión por token, C-12 oferta por token).
PUBLIC_PREFIXES = ("/api/booking/", "/api/manage/", "/api/waitlist-offer/")
PUBLIC_EXACT = frozenset(
    {
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/refresh"),
        ("POST", "/api/auth/logout"),
    }
)


def _dependencies(dependant: Dependant) -> Iterator[Dependant]:
    for sub in dependant.dependencies:
        yield sub
        yield from _dependencies(sub)


def _protegida(route: APIRoute) -> bool:
    return any(d.call is get_current_principal for d in _dependencies(route.dependant))


def _rutas_api() -> list[tuple[str, str, APIRoute]]:
    app = create_app()
    rutas = []
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            for metodo in sorted(route.methods or ()):
                rutas.append((metodo, route.path, route))
    return rutas


def _es_publica(metodo: str, path: str) -> bool:
    return (metodo, path) in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


def test_toda_ruta_api_no_publica_exige_principal() -> None:
    sin_proteccion = [
        f"{metodo} {path}"
        for metodo, path, route in _rutas_api()
        if not _es_publica(metodo, path) and not _protegida(route)
    ]
    assert sin_proteccion == []


def test_la_lista_blanca_no_tiene_entradas_muertas() -> None:
    existentes = {(metodo, path) for metodo, path, _ in _rutas_api()}
    assert PUBLIC_EXACT <= existentes


def test_los_reportes_y_exportaciones_nuevos_estan_protegidos() -> None:
    nuevas = {
        "/api/reports/pilot",
        "/api/reports/whatsapp/budget",
        "/api/exports/patients/{patient_id}",
    }
    encontradas = {path for _, path, route in _rutas_api() if path in nuevas and _protegida(route)}
    assert encontradas == nuevas


# ------------------------------------------------------------------ C-15 (D4)

_CLINICAL_MARKERS = ("clinical-record", "clinical-records", "odontogram")


def _roles_declarados(route: APIRoute) -> list[frozenset[str]]:
    """Conjuntos de roles de cada `require_roles(...)` en el árbol de dependencias."""
    return [
        frozenset(str(rol) for rol in d.call.allowed_roles)
        for d in _dependencies(route.dependant)
        if d.call is not None and hasattr(d.call, "allowed_roles")
    ]


def _rutas_clinicas() -> list[tuple[str, str, APIRoute]]:
    return [r for r in _rutas_api() if any(m in r[1] for m in _CLINICAL_MARKERS)]


def test_hay_rutas_clinicas_registradas() -> None:
    assert len(_rutas_clinicas()) >= 20


def test_ningun_endpoint_clinico_queda_sin_guarda_ni_admite_recepcion() -> None:
    """Escenario "Ningún endpoint clínico queda sin guarda"."""
    infractoras = []
    for metodo, path, route in _rutas_clinicas():
        roles = _roles_declarados(route)
        if not _protegida(route) or not roles or any("recepcion" in r for r in roles):
            infractoras.append(f"{metodo} {path}")
    assert infractoras == []


def test_la_guarda_clinica_detecta_una_ruta_que_admite_recepcion() -> None:
    """Prueba del propio test: una ruta con recepción en sus roles se detecta."""
    from app.common.dependencies import require_roles
    from fastapi import APIRouter, Depends

    router = APIRouter()

    @router.get("/api/clinical-records/{rid}/intrusa")
    async def _intrusa(_: object = Depends(require_roles("admin", "recepcion"))) -> None:
        return None

    route = router.routes[0]
    assert isinstance(route, APIRoute)
    assert any("recepcion" in r for r in _roles_declarados(route))
