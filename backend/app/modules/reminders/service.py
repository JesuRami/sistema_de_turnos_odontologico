"""Servicio del dominio reminders (stub C-01; lógica real en C-09)."""


class RemindersService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"
