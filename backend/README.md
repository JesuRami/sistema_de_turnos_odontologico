# Backend — Sistema de Turnos Odontológico

FastAPI + SQLAlchemy 2.x async + Alembic sobre PostgreSQL 15. Los comandos se
corren desde la raíz del repo salvo que se indique otra cosa.

## Base de datos y migraciones

```bash
# DATABASE_URL acepta postgresql:// o postgresql+asyncpg:// (se fuerza asyncpg)
alembic upgrade head      # crea el modelo core (revisión c02_core_models)
alembic downgrade c01_base
```

- `pg_trgm` se crea con `CREATE EXTENSION IF NOT EXISTS`. Es una extensión
  *trusted* desde PostgreSQL 13: alcanza con ser owner de la base (no hace falta
  superusuario). El downgrade no la elimina.
- Todas las tablas operativas llevan `clinic_id NOT NULL`; las referencias entre
  tablas son claves foráneas compuestas `(clinic_id, id)`.

## Seed del tenant inicial

Crea una clínica, un admin con cambio de contraseña obligatorio, el sillón
"Sillón 1" y un profesional de ejemplo inactivo. Es idempotente por slug y no
imprime secretos. Se ejecuta desde `backend/`:

```bash
cd backend
SEED_CLINIC_SLUG=clinica-demo \
SEED_CLINIC_NAME="Clínica Demo Ficticia" \
SEED_ADMIN_EMAIL=admin@example.com \
SEED_ADMIN_PASSWORD='<clave provisoria>' \
python -m app.seed
```

Las cuatro variables `SEED_*` son obligatorias (ver `.env.example`); si falta
alguna el seed aborta nombrándola y no escribe nada. Usar solo datos sintéticos
(dominio `example.com`).

## Tests

Los tests corren contra **PostgreSQL real** (nunca mocks de base de datos).

```bash
# DB de tests: TEST_DATABASE_URL > DATABASE_URL > default local
export TEST_DATABASE_URL=postgresql+asyncpg://turnos:ci-secret@localhost:5432/turnos_test
pytest -q
ruff check backend && black --check backend && mypy backend
```

El rol necesita `CREATEDB` para el test de ciclo de migraciones y el del CLI del
seed (usan una base temporal propia); sin ese permiso se saltan con motivo.
