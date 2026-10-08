# Arquitectura Propuesta

## Patrones aplicados

| Patrón | Dónde se usa | Por qué |
|--------|--------------|---------|
| Monolito modular (FastAPI routers/services/schemas) | Backend: `agenda`, `booking-public`, `reminders`, `users`, `reports`, `notifications` | < 50 concurrentes por tenant no justifican red distribuida; routers + servicios con fronteras permiten extraer el worker (reminders primero) cuando el volumen lo pida |
| Invariante en DB (exclusion constraint) | Tabla `appointment` (`tstzrange` + GiST) | Elimina condiciones de carrera entre recepción y booking concurrente; el backend valida para UX, la DB decide |
| Outbox transaccional / jobs en Redis + persistencia en DB | `reminder_job` + worker async con `FOR UPDATE SKIP LOCKED` + cola Redis (reminder scheduler, WhatsApp queue/outbox, waiting-list jobs) | Los recordatorios sobreviven caídas; reintentos e idempotencia gratis |
| Token capability (no sesión) | Gestión del paciente (`manage_token`) | Evita cuentas/contraseñas para el paciente; capacidad mínima por turno con TTL |
| Auditoría inmutable (append-only) | `appointment_event`, rol DB sin UPDATE/DELETE | Base de reportes y disputas; exigencia regulatoria futura (Ley 27.706) heredada gratis |
| Webhook con verificación de firma | `POST /webhooks/whatsapp` | Meta firma cada evento; sin firma válida no se procesa nada |
| Configuración por clínica (multi-tenant lógico) | `clinic_id` en todas las tablas operativas + parámetros (`cancellation_window_hours`, `reminder_steps`) | Un deploy por clínica hoy, mismo código para multi-tenant mañana |

## Estructura de directorios

```
sistema-turnos-odonto/
├── backend/
│   ├── app/
│   │   ├── main.py                  # bootstrap FastAPI, CORS, rate-limit, routers
│   │   ├── core/                    # config (pydantic-settings), security (JWT), deps
│   │   ├── common/                  # dependencies (auth, roles, tenant), exceptions, pagination
│   │   ├── modules/
│   │   │   ├── auth/                # router + service + schemas: login personal, refresh rotativo, hash argon2
│   │   │   ├── clinic/              # router + service + schemas: clinic, professionals, chairs, schedules, blocks
│   │   │   ├── agenda/              # router + service + schemas: appointments, estados, sobreturnos, auditoría
│   │   │   ├── booking_public/      # router + service + schemas: disponibilidad, reserva, manage-token (rate-limit duro)
│   │   │   ├── waiting_list/        # router + service + schemas: entries, offers, evaluación FIFO
│   │   │   ├── reminders/           # scheduler, sender whatsapp/email, reintentos (lógica compartida api+worker)
│   │   │   ├── notifications/       # templates, delivery events, opt-in/out
│   │   │   ├── users/               # personal, roles
│   │   │   └── reports/             # ocupación, ausentismo, cancelaciones (solo lectura)
│   │   ├── models/                  # modelos SQLAlchemy 2.x async (DateTime(timezone=True), JSONB, Enum)
│   │   └── worker/                  # entrypoint worker async Redis (reminder scheduler, whatsapp outbox, waitlist jobs)
│   ├── alembic/ + alembic.ini       # migraciones versionadas (una por cambio; DDL para EXCLUDE)
│   ├── tests/                       # pytest unit + API (httpx/TestClient, invariantes con concurrencia)
│   ├── pyproject.toml / requirements.txt  # deps (fastapi, sqlalchemy[asyncio], asyncpg, alembic, redis, pydantic-settings)
│   └── Dockerfile                   # imagen api + worker
├── frontend/
│   └── src/
│       ├── features/
│       │   ├── agenda/              # grilla día/semana, filtros, drag & drop
│       │   ├── booking/             # flujo público en 4 pasos (mobile-first)
│       │   ├── manage/              # gestión por token
│       │   ├── waiting-list/        # panel de cola y ofertas
│       │   ├── reminders/           # timeline de entregas por turno
│       │   ├── admin/               # profesionales, sillones, horarios, bloqueos, políticas
│       │   └── reports/             # 4 reportes + exportación
│       ├── shared/                  # api client, auth context, UI kit, fechas/zona
│       └── pages/ + routes/         # públicas (/b/:slug, /g/:token) vs. autenticadas
├── docker-compose.yml               # servicios: api, db (Postgres 15), redis (Redis 7), worker, frontend
└── knowledge-base/                  # este directorio (contrato del sistema)
```

### Docker Compose (servicios)

| Servicio | Imagen / build | Rol | Depende de |
|----------|---------------|-----|------------|
| `db` | Postgres 15 | Base transaccional (constraints de agenda, `tstzrange`/GiST) | — |
| `redis` | Redis 7 | Cola/outbox async: reminder scheduler, WhatsApp queue, waiting-list jobs | — |
| `api` | Backend FastAPI (uvicorn) | REST API (`routers/`+`services/`+`schemas/`, SQLAlchemy `AsyncSession`) | `db`, `redis` |
| `worker` | Misma imagen, entrypoint worker | Consume Redis + reclama `reminder_job` con `SKIP LOCKED`, envía WhatsApp/email | `db`, `redis` |
| `frontend` | Build Vite + servidor estático | SPA React+TS (recepción/admin/odontólogo + booking público) | `api` |

## Seguridad

- **Autenticación**: personal con email+password (argon2id) → JWT access corto (15 min) + refresh rotativo con reuse-detection (FastAPI dependencies + `python-jose`/`pyjwt`). Paciente sin credenciales: token opaco de 256 bits (hash SHA-256 en DB, TTL 72 h post-turno).
- **Autorización**: dependencies de roles FastAPI (`require_roles('admin','recepcion')`, equivalente a guards) + regla "odontólogo solo sus turnos" aplicada en query SQLAlchemy (no en frontend). Endpoints públicos aislados en router `booking_public` con rate-limit propio (slowapi o middleware Redis).
- **Validación de input**: schemas Pydantic v2 en todos los bordes; normalización E.164 de teléfonos (phonenumbers); fechas siempre ISO con zona de la clínica; enumerados cerrados para estados/motivos.
- **Secrets management**: solo variables de entorno (nunca en repo); `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `WHATSAPP_TOKEN`, `META_WEBHOOK_SECRET` marcadas sensibles; rotación de token Meta sin redeploy (reload o secret manager del proveedor cloud).
- **Endurecimiento**: headers seguros (TrustedHost + middleware de security headers), CORS restrictivo (orígenes de la clínica), rate-limit global + estricto en booking/webhooks, validación de firma Meta en webhook, logs sin datos personales (teléfonos enmascarados), backups cifrados de Postgres con PITR.
- **Auditoría**: rol DB `app_writer` sin permiso de UPDATE/DELETE sobre `appointment_event`; ni siquiera un admin de app puede reescribir historia (solo superusuario DB, fuera del runtime).

## Variables de entorno

| Variable | Descripción | Ejemplo | Sensible |
|----------|-------------|---------|----------|
| `DATABASE_URL` | Conexión Postgres del tenant (asyncpg) | `postgresql+asyncpg://user:***@db:5432/clinica_x` | Y |
| `REDIS_URL` | Conexión Redis (cola/outbox + rate-limit) | `redis://redis:6379/0` | Y |
| `JWT_SECRET` | Firma de access/refresh tokens | (aleatorio 256 bits) | Y |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | TTLs de JWT | `15` / `7` | N |
| `WHATSAPP_TOKEN` | Token Cloud API WhatsApp | `EAA...` | Y |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número remitente | `123456789` | N |
| `META_WEBHOOK_SECRET` | Secreto de verificación de webhook | (aleatorio) | Y |
| `META_TEMPLATE_T72H` / `_T24H` / `_T3H` | Nombres de plantillas aprobadas | `recordatorio_72h_v1` | N |
| `EMAIL_PROVIDER` / `EMAIL_API_KEY` | Proveedor y clave de email respaldo | `resend / re_...` | Y (clave) |
| `CLINIC_TZ_DEFAULT` | Zona por defecto de clínicas nuevas | `America/Argentina/Buenos_Aires` | N |
| `BOOKING_RATE_LIMIT` | Reservas/hora/IP en booking público | `10` | N |
| `MANAGE_TOKEN_TTL_H` | TTL del token de gestión post-turno | `72` | N |
| `REMINDER_WORKER_CONCURRENCY` | Workers paralelos del scheduler | `4` | N |
| `FRONTEND_PUBLIC_URL` | Base para links de token/WhatsApp | `https://turnos.clinica.com` | N |
| `CORS_ORIGINS` | Orígenes permitidos del frontend | `https://turnos.clinica.com` | N |
| `ENV` | Entorno (`dev`/`prod`) para Compose | `dev` | N |

> Jobs sobre Redis desde el día 1: reminder scheduler, WhatsApp queue/outbox y waiting-list jobs corren en el servicio `worker` (async) con persistencia en `reminder_job` + `FOR UPDATE SKIP LOCKED`. Ver `09_decisiones_y_supuestos.md` (DD-01/DD-06).
