"""Servicio del dominio reports (stub C-01; lógica real en C-13)."""


class ReportsService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"
