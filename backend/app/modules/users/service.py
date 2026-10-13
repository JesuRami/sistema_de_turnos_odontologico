"""Servicio del dominio users (stub C-01; lógica real en C-03)."""


class UsersService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"
