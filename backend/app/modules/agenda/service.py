"""Servicio del dominio agenda (stub C-01; lógica real en C-04/C-05)."""


class AgendaService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"
