"""Metadatos del request compartidos por auth y reserva pública (C-07, D11).

La IP del cliente es la que el servidor ya resolvió (uvicorn con `--proxy-headers` y
`FORWARDED_ALLOW_IPS`, con nginx sobrescribiendo `X-Forwarded-For`). La app NO parsea
`X-Forwarded-For` por su cuenta: en desarrollo sería falsificable por el cliente.
"""

from fastapi import Request


def client_ip(request: Request) -> str:
    """IP de origen del request, o `"unknown"` si el transporte no la informa."""
    return request.client.host if request.client else "unknown"
