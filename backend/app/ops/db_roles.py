"""Alta/actualización del usuario de login de la app como miembro de `app_writer` (C-14, D7).

Uso (lo corre el servicio `migrate` después de `alembic upgrade head`):

    python -m app.ops.db_roles

Lee del entorno:
- `MIGRATION_DATABASE_URL` (o `DATABASE_URL`): conexión con el dueño del schema, que puede crear
  roles (`CREATEROLE`).
- `APP_DB_USER` (default `turnos_app`) y `APP_DB_PASSWORD` (obligatoria, ≥ 16 caracteres ASCII
  imprimibles).

Idempotente: si el usuario existe le actualiza la clave y la membresía; si no, lo crea con
`LOGIN INHERIT` (hereda los privilegios del grupo), sin `CREATEDB` ni `CREATEROLE`.

La clave **nunca** viaja en claro: se calcula acá el verificador SCRAM-SHA-256 y se manda ese
(así un `log_statement = 'ddl'` del servidor tampoco la registra). Nunca se imprime.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
import sys

from app.ops.db_privileges import APP_ROLE

_USER_RE = re.compile(r"^[a-z_][a-z0-9_]{2,62}$")
_PRINTABLE_ASCII = re.compile(r"^[\x21-\x7e]+$")
_MIN_PASSWORD = 16
_SCRAM_ITERATIONS = 4096


class ProvisioningError(RuntimeError):
    """Configuración inválida: mensaje sin valores sensibles."""


def scram_sha256_verifier(
    password: str, *, salt: bytes | None = None, iterations: int = _SCRAM_ITERATIONS
) -> str:
    """Verificador `SCRAM-SHA-256$<iter>:<salt>$<StoredKey>:<ServerKey>` (RFC 5802/7677).

    Solo ASCII imprimible: así SASLprep es la identidad y el verificador coincide con el que
    calcularía el propio servidor.
    """
    if not _PRINTABLE_ASCII.match(password):
        raise ProvisioningError("APP_DB_PASSWORD debe ser ASCII imprimible sin espacios")
    sal = salt if salt is not None else secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), sal, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def b64(valor: bytes) -> str:
        return base64.b64encode(valor).decode("ascii")

    return f"SCRAM-SHA-256${iterations}:{b64(sal)}${b64(stored_key)}:{b64(server_key)}"


def validate(user: str, password: str) -> None:
    if not _USER_RE.match(user):
        raise ProvisioningError("APP_DB_USER debe ser un identificador simple en minúsculas")
    if user == APP_ROLE:
        raise ProvisioningError(f"APP_DB_USER no puede ser el rol de grupo {APP_ROLE}")
    if len(password) < _MIN_PASSWORD:
        raise ProvisioningError(f"APP_DB_PASSWORD debe tener al menos {_MIN_PASSWORD} caracteres")


def provisioning_statements(user: str, verifier: str, exists: bool) -> list[str]:
    """DDL para crear/actualizar el usuario. `user` ya validado; `verifier` es base64 + `$:`."""
    # El verificador solo tiene [A-Za-z0-9+/=$:-]: no puede cerrar el literal.
    if "'" in verifier:
        raise ProvisioningError("verificador inválido")
    sentencias = []
    if exists:
        sentencias.append(f"ALTER ROLE {user} WITH LOGIN INHERIT PASSWORD '{verifier}'")
    else:
        sentencias.append(
            f"CREATE ROLE {user} WITH LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"PASSWORD '{verifier}'"
        )
    sentencias.append(f"GRANT {APP_ROLE} TO {user}")
    return sentencias


async def provision(dsn: str, user: str, password: str) -> bool:
    """Crea o actualiza el usuario; devuelve `True` si lo creó."""
    import asyncpg

    validate(user, password)
    verifier = scram_sha256_verifier(password)
    conn = await asyncpg.connect(dsn.replace("+asyncpg", "", 1), timeout=10)
    try:
        if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", APP_ROLE) is None:
            raise ProvisioningError(
                f"el rol {APP_ROLE} no existe: correr `alembic upgrade head` primero"
            )
        existe = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", user) is not None
        async with conn.transaction():
            for sentencia in provisioning_statements(user, verifier, existe):
                await conn.execute(sentencia)
        return not existe
    finally:
        await conn.close()


def main() -> int:
    dsn = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    user = os.environ.get("APP_DB_USER", "turnos_app")
    password = os.environ.get("APP_DB_PASSWORD", "")
    if not dsn:
        print("db_roles: falta MIGRATION_DATABASE_URL o DATABASE_URL", file=sys.stderr)
        return 2
    try:
        creado = asyncio.run(provision(dsn, user, password))
    except ProvisioningError as exc:
        print(f"db_roles: {exc}", file=sys.stderr)
        return 2
    print(f"db_roles: usuario {user} {'creado' if creado else 'actualizado'} en {APP_ROLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
