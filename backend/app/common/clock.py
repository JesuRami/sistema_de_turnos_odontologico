"""Reloj inyectable (C-05): las reglas temporales de turnos dependen de "ahora".

Los routers lo reciben por dependency (`get_now`) y lo pasan al servicio; los
tests lo sobrescriben con un reloj fijo en vez de esperar o depender del día.
"""

from datetime import UTC, datetime


def get_now() -> datetime:
    """Instante actual con zona (UTC)."""
    return datetime.now(UTC)
