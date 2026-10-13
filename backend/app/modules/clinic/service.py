"""Servicio del dominio clinic (stub C-01; lógica real en C-02)."""


class ClinicService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"
