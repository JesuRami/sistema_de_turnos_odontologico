"""Servicio del dominio waiting_list (stub C-01; lógica real en C-12)."""


class WaitingListService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"
