# Descripción General

## Stack tecnológico

| Capa | Tecnología | Versión mínima | Notas |
|------|-----------|----------------|-------|
| Backend | Python + FastAPI | Python 3.12+ / FastAPI 0.110+ | API REST, routers por dominio, validación con Pydantic v2 |
| Frontend | React + TypeScript + Vite | React 18 / Vite 5 | SPA browser-first; TypeScript estricto |
| UI | Tailwind CSS + componentes propios | Tailwind 3 | Agenda (calendario) con librería dedicada o custom sobre grid |
| Base de datos | PostgreSQL | 15 | Exclusion constraints para solapamientos; `tstzrange` |
| ORM / Migraciones | SQLAlchemy 2.x async + Alembic | SQLAlchemy 2.x | `AsyncSession`, `DateTime(timezone=True)`, constraints vía DDL; migraciones versionadas con Alembic |
| Jobs programados / Cola | Redis + worker async | Redis 7 | Reminder scheduler, WhatsApp queue/outbox y waiting-list jobs (idempotentes y reintentables) |
| Auth | JWT (access corto + refresh rotativo) | — | Solo personal de clínica; paciente opera por token de un solo uso |
| Email transaccional | Proveedor SMTP/API (a definir) | — | Canal de respaldo de recordatorios |
| WhatsApp | WhatsApp Business API (Cloud API de Meta) | Graph API v19+ | Único canal WhatsApp soportado; plantillas aprobadas |
| Despliegue | Docker / Docker Compose: `api` + `db` + `redis` + `worker` + `frontend` | — | Single cloud deploy por tenant (fase 1); `frontend` estático servido tras build Vite |
| Tests | pytest (unit) + httpx/TestClient (API) + Playwright (E2E crítico) | — | Cobertura obligatoria en invariantes de agenda |

**Suposición:** se asume despliegue single-tenant (una base por clínica) en fase 1. Multi-tenant real queda para fase posterior; el esquema de datos debe dejar `clinic_id` como clave de partición futura aunque físicamente haya una DB por clínica.

## Arquitectura general

```
                ┌──────────────┐      HTTPS       ┌──────────────┐
                │  React SPA   │ ◄──────────────► │  FastAPI API │
                │ (recepción,  │    REST + JWT    │  (routers:   │
                │  admin,      │                  │  agenda,     │
                │  odontólogo) │                  │  booking,    │
                └──────────────┘                  │  reminders,  │
                        ▲                         │  users)     │
                        │ link público            └──────┬───────┘
                ┌──────────────┐                        │
                │ Paciente     │                        ▼
                │ (sin login:  │                 ┌──────────────┐
                │  token URL)  │                 │  PostgreSQL  │
                └──────────────┘                 │  (constraints│
                                                 │   de agenda) │
                                                 └──────┬───────┘
                                                        │ jobs
                                                 ┌──────▼───────┐
                                                 │ Reminder     │
                                                 │ worker ──► Meta Cloud API
                                                 │        ──► Email
                                                 └──────────────┘
```

Decisiones de alto nivel:

1. **La consistencia de agenda vive en la base de datos, no en el backend.** Los solapamientos se previenen con `EXCLUDE USING gist` sobre rangos temporales por (profesional, sillón). El backend valida para dar mensajes amables; la DB es la última palabra. Esto elimina condiciones de carrera entre recepción y reserva online concurrente.
2. **El paciente no tiene cuenta en v1.0.** Opera con token firmado de un solo uso por turno (link mágico con expiración). Se elimina una superficie completa de auth/recupero de contraseñas a cambio de links con TTL y rate-limit (trade-off documentado en DD-04).
3. **Recordatorios como jobs persistentes, no cron en memoria.** Cada turno confirmado genera filas de job (T-72h, T-24h, T-3h configurable). Si el worker cae, los jobs sobreviven. Idempotencia por `(appointment_id, reminder_step)`.
4. **Monolito modular, no microservicios.** Con < 50 usuarios concurrentes por tenant, distribuir es costo sin beneficio. Paquetes FastAPI con fronteras claras (`routers/` + `services/` + `schemas/` por dominio: agenda, booking público, reminders, users) extraíbles el día que el volumen lo pida. El worker async (Redis queue/outbox: reminder scheduler, WhatsApp queue, waiting-list jobs) corre como servicio separado en Docker Compose pero comparte los mismos modelos SQLAlchemy.

## Integraciones externas

| Servicio | Propósito | Tipo |
|----------|-----------|------|
| Meta WhatsApp Cloud API | Envío de recordatorios, confirmaciones, ofrecimiento de huecos; recepción de respuestas SÍ/NO/reprogramar | REST + webhooks entrantes |
| Email transaccional (a definir: Resend/SES/SMTP) | Respaldo cuando no hay WhatsApp válido u opt-out | API/SMTP |
| (Futura, NO v1.0) Mercado Pago | Señas y cobros online | — registrado como stub, sin implementar |
| (Futura, NO v1.0) ARCA | Factura electrónica | — registrado como stub, sin implementar |

## API REST

Agrupada por recurso (detalle de contratos en fase de diseño detallado):

- `POST /auth/login`, `POST /auth/refresh` — personal de clínica.
- `GET/POST/PUT /professionals`, `/chairs`, `/schedules`, `/blocks` — configuración de agenda (admin).
- `GET /agenda?professional_id&chair_id&from&to` — vista día/semana; `POST /appointments` (recepción, con sobreturno explícito), `PATCH /appointments/:id` (estados, reprogramación).
- `GET /booking/:slug/availability` (público, rate-limited), `POST /booking/:slug/appointments` (público), `GET/PATCH /manage/:token` (gestión por token: confirmar/cancelar/reprogramar).
- `GET/POST /waiting-list`, `POST /waiting-list/:id/offer` — lista de espera.
- `POST /webhooks/whatsapp` — eventos entrantes de Meta (confirmaciones, opt-out).
- `GET /reports/occupancy`, `/reports/no-shows`, `/reports/cancellations` — reportes mínimos.
