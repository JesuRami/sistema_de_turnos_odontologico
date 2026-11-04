"""`client_ip` (C-07, D11): usa la IP que el servidor ya resolvió, sin parsear cabeceras propias."""

from app.common.request_meta import client_ip
from starlette.requests import Request


def _request(client: tuple[str, int] | None, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers, "client": client}
    )


def test_usa_el_host_del_cliente() -> None:
    assert client_ip(_request(("203.0.113.7", 5000), [])) == "203.0.113.7"


def test_ignora_x_forwarded_for_enviado_por_el_cliente() -> None:
    request = _request(("203.0.113.7", 5000), [(b"x-forwarded-for", b"198.51.100.9")])

    assert client_ip(request) == "203.0.113.7"


def test_sin_cliente_devuelve_unknown() -> None:
    assert client_ip(_request(None, [])) == "unknown"
