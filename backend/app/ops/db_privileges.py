"""SQL de privilegios del rol `app_writer` (C-14, D7; diferido de C-05).

Módulo sin dependencias (solo strings): lo usan la migración `c14_hardening_pilot` y los tests,
y se puede aplicar a mano con `psql` en un incidente.

Contrato:
- `app_writer` es un rol de grupo `NOLOGIN`; el usuario de login de la app (`APP_DB_USER`) es
  miembro y lo crea `python -m app.ops.db_roles` con la clave del entorno (nunca en una migración).
- `SELECT, INSERT, UPDATE` en las tablas operativas; **ningún `DELETE` ni `TRUNCATE`** (regla 7:
  la app no borra; los `DELETE` HTTP de bloqueos y prioridad son lógicos).
- Tablas append-only: solo `SELECT, INSERT`. Los triggers de C-03…C-12 siguen como segunda
  barrera, pero ahora un error de código ni siquiera llega a dispararlos.
- `DEFAULT PRIVILEGES`: lo que cree el dueño del schema en migraciones futuras nace con los
  mismos permisos (una tabla append-only nueva debe sumarse a `APPEND_ONLY_TABLES` y revocar
  su `UPDATE` en su propia migración).
"""

from __future__ import annotations

APP_ROLE = "app_writer"

# Tablas con trigger append-only (C-03, C-04, C-05, C-06, C-09, C-10, C-11, C-12).
APPEND_ONLY_TABLES: tuple[str, ...] = (
    "auth_event",
    "agenda_config_event",
    "appointment_event",
    "patient_merge",
    "delivery_event",
    "consent",
    "whatsapp_inbound",
    "reminder_manual_resend",
    "waitlist_event",
)

CREATE_ROLE = f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    CREATE ROLE {APP_ROLE} NOLOGIN;
  END IF;
END
$$
"""

GRANT_CONNECT = f"""
DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO {APP_ROLE}', current_database());
END
$$
"""


def grant_statements() -> list[str]:
    """Sentencias idempotentes que dejan los privilegios del contrato en la base actual."""
    sentencias = [
        CREATE_ROLE,
        GRANT_CONNECT,
        f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}",
        # Punto de partida limpio: lo que hubiera de antes (p. ej. un GRANT ALL manual) se quita.
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}",
        f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}",
        f"REVOKE UPDATE ON {', '.join(APPEND_ONLY_TABLES)} FROM {APP_ROLE}",
        f"REVOKE INSERT, UPDATE ON alembic_version FROM {APP_ROLE}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}",
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {APP_ROLE}"
        ),
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
        ),
    ]
    return sentencias


DROP_ROLE_IF_UNUSED = f"""
DO $$
BEGIN
  DROP ROLE IF EXISTS {APP_ROLE};
EXCEPTION
  WHEN dependent_objects_still_exist THEN
    RAISE NOTICE '{APP_ROLE} sigue con privilegios en otra base: no se elimina';
END
$$
"""


def revoke_statements() -> list[str]:
    """Deshace `grant_statements` en la base actual y elimina el rol si nadie más lo usa."""
    return [
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {APP_ROLE}"
        ),
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}"
        ),
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}",
        f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}",
        f"""
DO $$
BEGIN
  EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {APP_ROLE}', current_database());
END
$$
""",
        DROP_ROLE_IF_UNUSED,
    ]


def role_guard(statement: str) -> str:
    """Envuelve una sentencia para que no falle si el rol no existe (downgrade parcial)."""
    escapada = statement.replace("'", "''")
    return f"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    EXECUTE '{escapada}';
  END IF;
END
$$
"""
