"""Servicio del dominio notifications (stub C-01; lógica real en C-10)."""


class NotificationsService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"
