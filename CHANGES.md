# CHANGES — Secuencia de Implementación

> Índice canónico de todos los changes del proyecto **sistema_de_turnos_odontologico**.
> Cada change es atómico: un agente puede implementarlo en una sesión (~4-6 horas).
> **Leer este archivo antes de ejecutar cualquier `/opsx:propose`.**

---

## Cómo usar este documento

1. Identificar el change a implementar (verificar que sus dependencias están en `openspec/changes/archive/`).
2. Leer los docs de la knowledge-base indicados en "Leer antes".
3. Ejecutar `/opsx:propose <nombre-del-change>`.
4. Al terminar el change, archivarlo con `/opsx:archive <nombre-del-change>`.
5. Marcar el checkbox `[x]` en este archivo.

---

## Árbol de dependencias

```
C-01 foundation-setup
  └── C-02 core-models
        └── C-03 auth-rbac
              └── C-04 agenda-config
                    └── C-05 appointments-core          ← invariante anti-solapamiento, desbloquea el MVP
                          │
                          ├── C-06 agenda-spa-recepcion        [Frontend]
                          ├── C-07 booking-publico             ──┐
                          │     └── C-08 gestion-por-token       │
                          │                                       ├── C-10 whatsapp-webhook  ← necesita C-08 + C-09
                          ├── C-09 motor-recordatorios   ────────┘     │
                          │     └── C-11 timeline-recordatorios        │
                          │                                           ├── C-12 lista-de-espera  ← necesita C-05 + C-08 + C-10
                          ├── C-13 reportes-admin-export              │
                                (C-03 + C-05)                         │
                                                                      └── C-14 hardening-piloto  ← necesita C-06 + C-11 + C-12 + C-13
                                                                            └── C-15 historia-clinica-odontograma   (FASE POSTERIOR)
                                                                                  └── C-16 cobros-mercadopago       (FASE POSTERIOR)
                                                                                        └── C-17 factura-arca      (FASE POSTERIOR)
                                                                                              └── C-18 obras-sociales-liquidacion (FASE POSTERIOR)
                                                                                                    └── C-19 multisede-escala      (FASE POSTERIOR)
```

### Paralelismo por fase

> Cada "gate" es un punto de sincronización. Los changes dentro de un grupo pueden ejecutarse en paralelo.

```
GATE 0: ninguna
  → C-01 foundation-setup (solo)

GATE 1: C-01 ✓
  → C-02 core-models (solo)

GATE 2: C-02 ✓
  → C-03 auth-rbac (solo)

GATE 3: C-03 ✓
  → C-04 agenda-config (solo)

GATE 4: C-04 ✓
  → C-05 appointments-core (solo)

GATE 5: C-05 ✓                          ← PRIMER FORK (4 paralelos)
  → C-06 agenda-spa-recepcion           [Agente C]
  → C-07 booking-publico                [Agente A]
  → C-09 motor-recordatorios            [Agente B]
  → C-13 reportes-admin-export          [Agente C — si C-06 ✓]

GATE 6: C-07 ✓ + C-09 ✓
  → C-08 gestion-por-token              [Agente A]
  → C-10 whatsapp-webhook               [Agente B — si C-08 ✓]

GATE 7: C-08 ✓ + C-10 ✓
  → C-12 lista-de-espera                [Agente A]
  → C-11 timeline-recordatorios         [Agente C]

GATE 8: C-06 + C-11 + C-12 + C-13 ✓
  → C-14 hardening-piloto (solo — requiere MVP funcional completo)

GATE 9: C-14 ✓                            ← FASES POSTERIORES (secuenciales, un agente)
  → C-15 → C-16 → C-17 → C-18 → C-19
```

### Camino crítico (9 changes — mínimo irreducible al piloto)

```
C-01 → C-02 → C-03 → C-04 → C-05 → C-07 → C-08 → C-10 → C-14
```

> C-09 (motor de recordatorios) corre en paralelo con C-07/C-08 y debe estar ✓ antes de C-10.
> C-06, C-11, C-12 y C-13 completan el MVP operativo pero no bloquean la cadena mínima a producción.
> C-15 a C-19 son fases posteriores (circuito clínico/fiscal) fuera del camino crítico del piloto agenda-first.

### Plan óptimo con 3 agentes

```
Paso │ Agente A (Backend Core)      │ Agente B (Backend Aux)         │ Agente C (Frontend)
─────┼──────────────────────────────┼────────────────────────────────┼─────────────────────────────
  1  │ C-01 foundation-setup        │               —                │               —
  2  │ C-02 core-models             │               —                │               —
  3  │ C-03 auth-rbac               │               —                │               —
  4  │ C-04 agenda-config           │               —                │               —
  5  │ C-05 appointments-core       │               —                │               —
  6  │ C-07 booking-publico         │ C-09 motor-recordatorios       │ C-06 agenda-spa-recepcion
  7  │ C-08 gestion-por-token       │ C-10 whatsapp-webhook (*)      │ C-13 reportes-admin-export
  8  │ C-12 lista-de-espera         │               —                │ C-11 timeline-recordatorios
  9  │ C-14 hardening-piloto        │               — (soporte)      │               — (soporte)
 10+ │ C-15 → C-16 → C-17 → C-18 → C-19 (secuencial, fases posteriores) │ — │ —
```

> (*) C-10 empieza cuando C-08 está ✓ (el webhook ejecuta las mismas transiciones que el link con token).

---

## FASE 0 — Cimientos

### [C-01] `foundation-setup`
- **Estado**: `[x]` archivado (2026-10-13 → `openspec/changes/archive/2026-10-13-c-01-foundation-setup/`)
- **Scope**: Scaffolding completo del monorepo + infraestructura base (DD-01, DD-06, DD-07)
  - Estructura `backend/` (Python + FastAPI async, `app/main.py` con CORS + rate-limit global, `app/routers|services|schemas` por dominio), `frontend/` (React 18 + TS + Vite, Tailwind 3), `backend/tests/` (pytest)
  - Paquetes FastAPI vacíos (`routers/`+`services/`+`schemas/`): `auth`, `clinic`, `agenda`, `booking_public`, `waiting_list`, `reminders`, `notifications`, `users`, `reports`; modelos SQLAlchemy 2.x async en `app/models/` + entrypoint `app/worker/`
  - Postgres 15 + Redis 7 + migraciones Alembic versionadas (una por change, DDL para EXCLUDE); worker async Redis (reminder scheduler, WhatsApp queue/outbox, waiting-list jobs — ver DD-06)
  - `.env.example` con `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `JWT_ACCESS_MINUTES`, `WHATSAPP_TOKEN`, `META_*`, `EMAIL_*`, `CLINIC_TZ_DEFAULT`, `BOOKING_RATE_LIMIT`, `MANAGE_TOKEN_TTL_H`, `FRONTEND_PUBLIC_URL`, `CORS_ORIGINS`
  - `Dockerfile` backend (api + worker) + `compose.yaml` con servicios `api`, `db`, `redis`, `worker`, `frontend` + Postgres gestionado por tenant (DD-07: 1 DB por clínica)
  - CI (jobs paralelos backend/frontend) + pytest + httpx/TestClient + Playwright instalados; deps Python vía `venv`+`pip` o `uv` (`pyproject.toml`/`requirements.txt`: fastapi, sqlalchemy[asyncio], asyncpg, alembic, redis, pydantic-settings)
- **Dependencias**: ninguna
- **Governance**: BAJO
- **Leer antes**:
  - `knowledge-base/01_vision_y_objetivos.md` (alcance v1.0 agenda-first)
  - `knowledge-base/02_descripcion_general.md` §Stack tecnológico
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-01, §DD-06, §DD-07

---

### [C-02] `core-models`
- **Estado**: `[x]` archivado (2026-11-02 → `openspec/changes/archive/2026-11-02-c-02-core-models/`)
- **Scope**: Entidades base + migraciones iniciales + seed mínimo (sin turnos todavía)
  - Modelos: `Clinic` (slug único, timezone, `cancellation_window_hours=24`, `reminder_steps` jsonb), `Professional`, `Chair`, `ScheduleRule`, `Patient` (liviano: nombre + teléfono E.164/email, `whatsapp_opt_in`, DNI opcional no único — SU-03), `User` (enum `admin/recepcion/odontologo`, argon2id, `professional_id` nullable)
  - `clinic_id` obligatorio en todas las tablas operativas (partición lógica futura, DD-07)
  - Migración `c02_core_models` (revises `c01_base`): tablas core + índices (`slug`, `(clinic_id, active)`, `(clinic_id, phone_e164)`, trigram en `full_name`)
  - Seed por clínica: 1 clinic + 1 admin + 1 chair "Sillón 1" + 1 professional ejemplo inactivo (sin `notification_template` ni motivos de bloqueo: ver C-04 y C-09)
  - Tests: constraints de unicidad, match de paciente por teléfono normalizado
- **Dependencias**: C-01
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §clinic, §professional, §chair, §schedule_rule, §patient, §user / role, §Seed data inicial
  - `knowledge-base/08_arquitectura_propuesta.md` §Configuración por clínica
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-07, §SU-03, §SU-04

---

### [C-03] `auth-rbac`
- **Estado**: `[x]` archivado (2026-11-03 → `openspec/changes/archive/2026-11-02-c-03-auth-rbac/`; gate 9.2 verde contra Postgres 15 + Redis 7)
- **Notas de cierre**: la migración real es `c03_auth_rbac` (no "migración 002"); la familia de refresh tokens vive en Redis (`REDIS_AUTH_DB`), no en tablas. C-04/C-05 consumen `require_roles` + `scope_by_professional` sin filtros propios.
- **Scope**: Autenticación del personal + RBAC de 4 roles (DD-03, DD-04)
  - `POST /auth/login` (email+password, argon2id, rate-limit 5/60s por IP+email), `POST /auth/refresh` (rotativo con reuse-detection, cookie HttpOnly secure/samesite=lax), `POST /auth/logout`, `GET /auth/me`
  - JWT access 15 min (`sub`, `clinic_id`, `roles`, `email`, `jti`, `type`, `iat`, `exp`)
  - Dependency FastAPI `require_roles('admin','recepcion')` + regla "odontólogo solo sus turnos" aplicada en query SQLAlchemy (no en frontend)
  - Alta/baja de usuarios con rol; odontólogo atado a su `professional_id` (US-051 CA-1)
  - Migración 002: tablas/saltos auth (refresh token family/blacklist)
  - Tests: login correcto, token expirado, refresh rotation + reuse, dependency de rol, odontólogo aislado (pytest + httpx/TestClient)
- **Dependencias**: C-02
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/03_actores_y_roles.md` §RBAC — Matriz de permisos
  - `knowledge-base/05_reglas_de_negocio.md` §Excepciones globales (RN-GL-01)
  - `knowledge-base/08_arquitectura_propuesta.md` §Seguridad
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-03

---

## FASE 1 — Agenda core (el núcleo de consistencia)

### [C-04] `agenda-config`
- **Estado**: `[x]` archivado (2026-11-03; rehecho tras un archive vacío del 2026-11-02, ver proposal)
- **Notas de cierre**: migración `c04_agenda_config` (no "003"). Anti-solape vía `EXCLUDE` con excepción acotada a la regla 11 (Postgres no admite `NOT VALID`/`CONCURRENTLY` en EXCLUDE). Políticas en horas (`max_overbookings_per_day`, `waitlist_offer_ttl_hours`). Auditoría en `agenda_config_event` (append-only). **Diferido con contrato**: RN-BL-02 → C-05 agrega el chequeo de turnos afectados a `BlocksService.create/update`; rechazo `409` al reservar sobre profesional/sillón inactivo → C-05 (recepción) y C-07 (online); US-004 CA-2 → C-09 copia el paso de recordatorio al programar el job y nunca relee la política.
- **Scope**: Configuración de agenda por la clínica — backend (US-001 a US-004)
  - Modelos/CRUD: `GET/POST/PUT /professionals`, `/chairs`, `/schedules`, `/blocks` (admin CRUD; recepción R; odontólogo R propios)
  - `ScheduleRule` por (professional, chair, weekday) con vigencia desde/hasta; rechazo de reglas solapadas (RN-AG-05)
  - `Block` con al menos un objetivo (RN-BL-01); creación que pisa turnos vigentes exige resolución explícita en la misma transacción (RN-BL-02); pasados inmutables (RN-BL-03); feriados como bloqueo manual multi-recurso (RN-BL-04)
  - Políticas de clínica editables: ventana de cancelación (default 24 h), pasos de recordatorio (72/24/3 h), tope sobreturnos (default 2), expiración de ofertas (default 4 h); cambios solo afectan turnos futuros (US-004 CA-2)
  - Desactivar profesional/sillón impide nuevas reservas, conserva historial (US-001 CA-1)
  - Migración 003: `block` con catálogo de motivos de bloqueo, columnas de política en `clinic`; anti-solape RN-AG-05 sobre `schedule_rule` (tabla creada en C-02)
  - Tests: solapamiento de reglas, bloqueo con turnos afectados, cambio de políticas no toca jobs programados
- **Dependencias**: C-03
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §schedule_rule, §block
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-05, §RN-BL-01 a §RN-BL-04
  - `knowledge-base/06_funcionalidades.md` §Épica 1 (US-001 a US-004)

---

### [C-05] `appointments-core`
- **Estado**: `[x]` archivado (2026-11-03)
- **Notas de cierre**: migración `c05_appointments_core` (no "004"). Rango ocupado explícito `occupied_until = ends_at + buffer` (snapshot) en vez de columna generada (`timestamptz + interval` no es inmutable). Los EXCLUDE usan la vigencia positiva `status IN ('pending','confirmed','present') AND NOT is_overbooking` (la KB decía `NOT IN ('cancelled','no_show')`: `absent` también libera, US-013 CA-2). Sobreturnos fuera del EXCLUDE, controlados bajo lock por recurso. Cancelación/asistencia por `POST /api/appointments/{id}/transitions` (no `PATCH status`). FK compuesta a `patient` exigió `uq_patient_id_clinic_id` (`CONCURRENTLY` + `USING INDEX`). RN-BL-02 aplicado a alta/edición de bloqueos y también al cierre de clínica. API mínima de pacientes (`GET/POST /api/patients`). **Diferido con contrato**: jobs de recordatorio (programar al crear/reprogramar, cancelar al cancelar, en la misma transacción del servicio de turnos) → C-09; evaluar lista de espera al cancelar → C-12; el booking público usa `AppointmentsService.book(origin=online)` y por lo tanto el mismo lock `FOR UPDATE` profesional→sillón, y `suggest_slots` para disponibilidad → C-07; rol DB `app_writer` (sin UPDATE/DELETE sobre eventos, separado del owner de migraciones) → C-14.
- **Scope**: Núcleo de turnos con invariante dura en DB + auditoría inmutable (US-011, US-012, US-013, RN-AG, RN-SB, RN-ST) — el change más crítico del sistema
  - `appointment` (`tstzrange` + `EXCLUDE USING gist` por professional y por chair, `WHERE status NOT IN ('cancelled','no_show')`); `ends_at > starts_at`; buffer del profesional integra el rango excluido (RN-AG-04)
  - Máquina de estados RN-ST-01 (`pending → confirmed → present`; `→ cancelled`; `confirmed → absent/no_show` post-horario solo personal); recepción nace `confirmed`, online nace `pending` (RN-ST-02)
  - `POST /appointments` (recepción, con `is_overbooking` explícito + motivo obligatorio + rol autorizado; online jamás genera sobreturno — RN-SB-01/02), tope configurable default 2 (RN-SB-03); `PATCH /appointments/:id` (reprogramación atómica con revalidación RN-AG-06; cancelar exige motivo, cancela jobs y evalúa lista de espera — RN-CX-03)
  - Marcar presente/ausente/no-show solo día del turno o después, solo personal (RN-ST-03); `no_show` vs cancelación tardía distinguidos (RN-ST-04); turnos nunca se borran físicamente (RN-GL-04)
  - `appointment_event` append-only (rol DB sin UPDATE/DELETE) escrito en la misma transacción que cada mutación (RN-GL-01); zona horaria única por clínica (RN-GL-03)
  - Migración 004: `appointment`, `appointment_event`, exclusion constraints, rol `app_writer`
  - Tests obligatorios: concurrencia recepción vs booking (carrera por el mismo hueco), sobreturno sin motivo rechazado, reprogramación que colisiona deja el turno intacto, auditoría inmutable
- **Dependencias**: C-04
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §appointment, §appointment_event
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-01 a §RN-AG-06, §RN-SB, §RN-ST, §RN-CX, §RN-GL-01
  - `knowledge-base/06_funcionalidades.md` §Épica 2 (US-011, US-012, US-013)
  - `knowledge-base/08_arquitectura_propuesta.md` §Invariante en DB, §Auditoría inmutable

---

### [C-06] `agenda-spa-recepcion`
- **Estado**: `[x]` archivado (2026-11-03)
- **Notas de cierre**: SPA del personal con sesión en memoria y refresh single-flight entre pestañas (`navigator.locks` + `BroadcastChannel`), agenda día/semana en la zona de la clínica con grilla propia, operación de turnos (alternativos ante `409`, sobreturno con motivo, reprogramar, cancelar, asistencia), pantallas de profesionales, sillones, plantilla, bloqueos (resolución de turnos afectados en la misma operación, también en cierres) y políticas. Backend mínimo: `GET /api/clinic` (zona horaria para todos los roles), `GET /api/patients/{id}` y `POST /api/patients/{id}/merge` con migración `c06_patient_merge` (puntero + `patient_merge` append-only) y `FOR SHARE` en el alta de turnos. Governance subida a ALTO por la fusión. Tests: Vitest + Testing Library + MSW y Playwright contra el stack real (semana de 500 turnos visible en 319 ms). **Diferido**: ABM de usuarios del personal (sin change asignado: hoy por API/seed); drag & drop en la agenda; reasignar o cancelar jobs de recordatorio y lista de espera del duplicado en la transacción de la fusión → C-09/C-12; Playwright en CI → C-14.
- **Scope**: SPA de recepción y administración — agenda diaria + ABM de recursos (US-010, US-001 a US-004 frontend, Flujo 4)
  - Vista día (default) y semana con filtros profesional/sillón/estado; color por profesional, distintivo por estado/sobreturno/bloqueo (US-010 CA-1/2); objetivo < 2 s con 500 turnos/semana (US-010 CA-3)
  - Crear turno con búsqueda trigram + alta rápida (nombre + contacto); colisión → alternativos o sobreturno explícito (Flujo 4 paso 2); reprogramar/cancelar con motivo; presente/ausente del día; pendientes sin confirmar destacados (T-24 h)
  - Pantallas admin: profesionales, sillones, horarios semanales, bloqueos (con lista de turnos afectados a resolver), políticas de la clínica
  - Fusión asistida de pacientes duplicados (auditada), nunca borrado
  - Rutas autenticadas con JWT + guard de rol; odontólogo ve solo sus turnos (vista restringida)
- **Dependencias**: C-04, C-05
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 1, §Épica 2 (US-010)
  - `knowledge-base/07_flujos_principales.md` §Flujo 4
  - `knowledge-base/03_actores_y_roles.md` §RBAC (odontólogo restringido)
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios (features/agenda, features/admin)

---

## FASE 2 — Reserva online y gestión del paciente (sin cuenta)

### [C-07] `booking-publico`
- **Estado**: `[x]` completado
- **Scope**: Reserva online 24/7 por link público — backend + flujo mobile-first (US-020, Flujo 1)
  - `GET /api/booking/:slug/availability?professional_id&from&to` — huecos = `schedule_rule − block − turnos vigentes − buffers`; solo fecha/hora/profesional, sin datos de otros pacientes (RN-ON-01); anti-enumeración + rate-limit 10 reservas/hora/IP (RN-ON-03; CAPTCHA según pregunta abierta Alta en `10`)
  - `POST /api/booking/:slug/appointments` — exige nombre + contacto + opt-in WhatsApp si hay teléfono (RN-ON-02); normalización E.164 + match por teléfono existente (RN-ON-05); inserta turno `pending` + `manage_token` (opaco 256 bits, hash SHA-256 en DB) en transacción con revalidación de exclusión; carrera → 409 + alternativos cercanos
  - Duración desde `slot_duration_min`, nunca libre del paciente (RN-AG-03); anti-ruido: sin regla vigente el profesional no es reservable (RN-AG-05)
  - Al crear: programa `reminder_job` (72/24/3 h futuros) + confirmación inmediata con link de gestión; aparece en agenda de recepción en tiempo real
  - Frontend `/b/:slug` en ≤ 4 pasos (profesional → día → hora → datos), mobile-first (US-020 CA-1)
  - Tests: 409 en carrera, 422 sin contacto, 429 rate-limit, teléfono inválido → email como canal con aviso
- **Dependencias**: C-05
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/05_reglas_de_negocio.md` §RN-ON-01 a §RN-ON-05, §RN-AG-03
  - `knowledge-base/06_funcionalidades.md` §Épica 3 (US-020)
  - `knowledge-base/07_flujos_principales.md` §Flujo 1
  - `knowledge-base/10_preguntas_abiertas.md` §CAPTCHA/anti-bot, §rotación de manage_token
- **Notas de cierre**: migración `c07_booking_public` (`appointment.manage_token_hash bytea`, CHECKs `NOT VALID → VALIDATE`, único parcial `CONCURRENTLY`; solo el SHA-256 persiste). Endpoints anónimos `GET /api/booking/{slug}`, `…/availability` y `POST …/appointments` (el servidor elige el sillón; escritura solo por `AppointmentsService.book(origin=online)`, actor `patient_token`). Sin CAPTCHA en v1 (decisión 2026-11-04): cupos Redis por IP/slug/lecturas, falla cerrada `503 booking_unavailable` y `BotGuard` conectable. `409` público con alternativos de todos los sillones y sin `conflicts`/`chair_id`. Extraídos `consume()` (rate-limit) y `client_ip()` compartidos con auth. Seed demo opt-in `SEED_BOOKING_DEMO=true`. SPA `/b/:slug` en ≤ 4 pasos con `QueryClient` propio (el `AuthProvider` hace `queryClient.clear()` al resultar anónimo el visitante y colgaba el catálogo), agenda de recepción con `refetchInterval` de 30 s. E2E mobile 360 px, agenda en ≤ 30 s y carrera por el mismo hueco. **Diferido con contrato**: `reminder_job` y mensaje de alta → C-09/C-10 (enganchan en `AppointmentsService.book`); uso, TTL (72 h post-turno) y rotación del token → C-08; historial de consentimiento (tabla `consent`) → C-09/C-10; texto legal de privacidad definitivo (hoy `PRIVACY_POLICY_VERSION` placeholder) → asesor legal; alta del toggle de `clinic.booking_enabled` desde la UI de admin → sin change asignado (hoy solo seed/DB); SSE/WebSocket en lugar de polling → cuando haya otra necesidad de push.

---

### [C-08] `gestion-por-token`
- **Estado**: `[x]` archivado (2026-11-05 → `openspec/changes/archive/2026-11-05-c-08-gestion-por-token/`; specs sincronizados: `booking/manage-token` y `web/manage-token` nuevos, `agenda/appointments` y `agenda/config` ampliados)
- **Notas de cierre**: migración `c08_manage_token` (solo `clinic.contact_phone`; `appointment` no cambia). Decisiones abiertas 1–5 aprobadas por el usuario con su default (2026-11-05): **no rotar** el token al reprogramar, TTL `ends_at + 72 h` (solo lectura desde `starts_at`), catálogo de 5 motivos con nota ≤ 200 solo para `otro`, rate-limit por IP y por hash separado lectura/escritura, reprogramar devuelve la vista sin URL nueva. Hallazgos corregidos durante el apply: deadlock recepción↔paciente al reprogramar el mismo turno (orden de locks unificado profesional → sillones → turno) y `MissingGreenlet` latente en `AppointmentsService._write` ante una violación real del `EXCLUDE` (C-05). **Contratos diferidos**: recordatorios reales → C-09 reemplaza `get_reminder_invalidator` (hoy no-op, invocado en la misma transacción); webhook WhatsApp "SI/NO" → C-10 reutiliza `ManageService`/`apply_transition` con `Actor(type=patient_token)`; reporte por motivo fino del paciente (`payload.patient_reason`) → change futuro sin backfill (C-13 sigue contando la causa `paciente`); rotación del token → decisión abierta #1, pendiente de confirmación Tech Lead + PO; reprogramar con otro profesional → sin change asignado (falta el flag de política). **Requisito de despliegue**: redactar `/g/` y `/api/manage/` en el access log de uvicorn/nginx (backend/README.md §Gestión por token).
- **Scope**: Confirmar / cancelar / reprogramar con token capability — backend + página pública (US-021, Flujo 2, DD-04)
  - `GET /g/:token`, `PATCH /api/manage/:token` — resuelve `manage_token_hash → appointment`; TTL 72 h post-turno, expirado → pantalla de contacto (RN-ON-04)
  - Confirmar en un toque (`pending → confirmed`, cancela jobs redundantes + auditoría); cancelar valida ventana (default 24 h; fuera → derivación a clínica, RN-CX-01); reprogramar ofrece solo huecos válidos, transacción atómica (RN-AG-06, RN-CX-02); doble click idempotente (no-op auditado)
  - Cancelar turno pasado → 422 (RN-CX-05); motivo paciente opcional (lista cerrada + "otro"), alimenta reporte (RN-CX-04)
  - Token de un solo turno, sin sesión; rate-limit estricto; rotación en reprogramación según decisión abierta (ver `10`)
- **Dependencias**: C-07
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/05_reglas_de_negocio.md` §RN-CX, §RN-ON-04, §RN-ST-01
  - `knowledge-base/06_funcionalidades.md` §US-021
  - `knowledge-base/07_flujos_principales.md` §Flujo 2
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-04

---

## FASE 3 — Recordatorios WhatsApp (el diferencial del MVP)

### [C-09] `motor-recordatorios`
- **Estado**: `[x]` archivado (2026-11-05 → `openspec/changes/archive/2026-11-05-c-09-motor-recordatorios/`; specs sincronizados: `reminders/job-scheduling`, `reminders/dispatch-worker` y `reminders/channel-consent` nuevos, `booking/manage-token` modificado, `core/patients` y `core/seed` ampliados)
- **Scope**: Reminder engine persistente sobre Postgres — scheduler + sender (US-030 backend, Flujo 3, DD-06)
  - `reminder_job` (`scheduled_for` en zona de la clínica, idempotencia única `(appointment_id, step, channel)`), `notification_template` (72/24/3 h + alta de turno), `delivery_event`
  - Worker tick 60 s con `FOR UPDATE SKIP LOCKED LIMIT 100`; pre-envío: turno vigente (si no → `cancelled`, RN-CX-03), opt-in del canal (RN-WA-01), plantilla activa, ventana 24 h de Meta
  - Reprogramar recalcula pendientes; cancelar marca `cancelled`; anti-ruido: solo pasos futuros si el turno se crea cerca del inicio; tope: jamás enviar de un turno ya iniciado (→ `skipped`)
  - Email como respaldo/escalado tras 3 fallos con backoff (5 min → 30 min → 2 h → `failed`); `provider_message_id` guardado; costo atribuible por clínica y paso (RN-WA-05)
  - Migración 005: `reminder_job`, `delivery_event`, `notification_template`, `consent`; seed de las 3 plantillas placeholder (extiende `app.seed`)
  - Tests: caída del worker (jobs sobreviven), doble-tick no duplica, opt-out a mitad de secuencia → `skipped`
- **Dependencias**: C-05
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §reminder_job + delivery_event + notification_template, §consent
  - `knowledge-base/05_reglas_de_negocio.md` §RN-WA-01, §RN-WA-02, §RN-WA-04, §RN-WA-05, §RN-CX-03
  - `knowledge-base/07_flujos_principales.md` §Flujo 3
  - `knowledge-base/11_whatsapp_y_recordatorios.md` §3. Motor de recordatorios

---

### [C-10] `whatsapp-webhook`
- **Estado**: `[x]` archivado (2026-11-06 → `openspec/changes/archive/2026-11-06-c-10-whatsapp-webhook/`; specs sincronizados: `reminders/whatsapp-channel`, `reminders/whatsapp-webhook` y `reminders/delivery-report` nuevos, `reminders/dispatch-worker` modificado, `reminders/channel-consent` y `web/reports-admin` ampliados)
- **Notas de cierre**: migración `c10_whatsapp_channel` (`clinic.whatsapp_phone_number_id` con CHECK `NOT VALID → VALIDATE`, únicos parciales `CONCURRENTLY` sobre ese campo y `reminder_job.provider_message_id`, tablas `whatsapp_inbound` append-only y `whatsapp_outbound_reply`, sin texto ni teléfono). Decisiones del usuario (2026-11-06): **excepción documentada a la regla 2** (el payload de Meta usa `extra='ignore'` solo después de verificar la firma; transcripta en `AGENTS.md`/`CLAUDE.md` y vigilada por `tests/test_edges.py`); **número propio o compartido soportados ambos** (la decisión comercial sigue abierta en `10`); "NO" nunca cancela (link o teléfono según ventana); STOP sin contexto en número compartido da de baja todas las fichas con ese teléfono; el webhook procesa en la request y las respuestas salen por un outbox del worker dentro de las 24 h. Proveedor `meta` sobre `httpx` (sin dependencia nueva), errores de Meta clasificados reintentable/definitivo. Confirmación compartida con C-08 en `manage/actions.confirm_by_patient`. `PUT /api/patients/{id}/consent/{canal}` para recepción. Reporte `GET /api/reports/whatsapp` sobre `delivery_event` (el costo viaja en `payload.cost_micros` del evento `sent`) y pestaña WhatsApp en `/admin/reportes`. Hallazgo del e2e: el evento `sent` tomaba la hora de la base y no la del tick; alineado con `sent_at`. Gate: 1411 tests backend, 181 frontend, ruff/black/mypy limpios. **Pendiente antes del piloto**: validar un payload real con el número de prueba de Meta, aprobar las 4 plantillas (`backend/README.md` §Canal WhatsApp) y la decisión comercial del número. **Diferido**: timeline, reenvío manual y alerta de `failed` → C-11; UI de consentimiento en la ficha → C-11; plantilla "turno reprogramado", `{{direccion}}`/«Cómo llegar», re-alta por WhatsApp, alerta de umbral de costo y tabla de precios por país → sin change asignado; carga de `whatsapp_phone_number_id` desde la UI → sin change asignado (hoy SQL/seed).
- **Scope**: Canal WhatsApp oficial bidireccional — envío Cloud API + webhook de respuestas (US-031, DD-05)
  - Alta de turno + plantillas `es_AR` categoría `utility` (`turno_creado_v1`, `recordatorio_72h_v1`, `recordatorio_24h_v1`, `recordatorio_3h_v1`) con botones Confirmar/Cambiar, SÍ/NO; fecha/hora formato argentino explícito
  - `POST /webhooks/whatsapp` con verificación `X-Hub-Signature-256` (401 + log sin firma); deduplicación por `provider_event_id`; estados `delivered/read/failed` actualizan el job
  - "SÍ" confirma (misma transición que el link, idempotente); "NO"/reprogramar → link de gestión o clínica según ventana; "STOP"/BAJA bloquea el canal de inmediato con confirmación (RN-WA-01/03)
  - Opt-in en reserva o cargado por recepción; cada cambio de consentimiento auditado con fuente
  - Proceso operativo de alta de plantillas por clínica + decisión número propio vs compartido (pregunta abierta Alta en `10`) antes del piloto
  - Reporte mensual WhatsApp por clínica (diferido de C-13): enviados/entregados/leídos por paso + costo atribuido (RN-WA-05, archivo `11` §4), sobre `reminder_job`/`delivery_event`, solo admin, con CSV
- **Dependencias**: C-08, C-09
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/05_reglas_de_negocio.md` §RN-WA-01 a §RN-WA-05, §RN-ST-02
  - `knowledge-base/06_funcionalidades.md` §US-030, §US-031
  - `knowledge-base/11_whatsapp_y_recordatorios.md` §1. Diseño del canal, §2. Plantillas, §5. Riesgos del canal
  - `knowledge-base/10_preguntas_abiertas.md` §alta de plantillas / número WhatsApp

---

### [C-11] `timeline-recordatorios`
- **Estado**: `[x]` archivado (2026-11-07 → `openspec/changes/archive/2026-11-07-c-11-timeline-recordatorios/`; specs sincronizados: `reminders/delivery-timeline`, `reminders/manual-actions` y `reminders/followup-board` nuevos, `reminders/job-scheduling` ampliado, `reminders/delivery-report` modificado y ampliado (requisito «Fallidos del último intento»), `web/agenda-board` ampliado)
- **Notas de preparación**: change preparado bajo SDD (proposal, design, 6 delta-specs, tasks TDD). Auditado con la skill `auditoria-escenarios-turnos` (informe en `docs/skills-mcp/evidencias/02-auditoria-informe.md`) y contrastado con Context7 para Meta Cloud API y PostgreSQL/SQLAlchemy. Las 3 fallas bloqueantes de especificación se corrigieron en los artefactos (frontera de generación en timeline, orden de guardas en reenvío concurrente, alineación de reprogramación con la spec principal).
- **Notas de cierre**: migración `c11_reminder_timeline` (`reminder_job.manual_resend_at` nullable, tabla `reminder_manual_resend` append-only con FKs compuestas a turno, job y usuario y CHECK de nota ≤ 200, índice parcial `ix_reminder_job_failed` `CONCURRENTLY`). Decisiones del usuario (2026-11-07): **aprobados los seis defaults** de las Open Decisions (cooldown 60 s y tope 3/día local por recordatorio, anotados en `10`; "sin confirmar" = `pending` con `sent` del paso de 24 h o del último de confirmación; precedencia `read > delivered > failed` en el intento vigente; estados tardíos del mensaje anterior ignorados; reporte con enviados y costo por evento; odontólogo de solo lectura) y **mockups salteados** (la UI reutiliza el design system). Endpoints: `GET /api/appointments/{id}/reminders` (timeline sin PII ni ids del proveedor, `can_resend` calculado por el servidor), `POST /api/appointments/{id}/reminders/{step}/{channel}/resend` (`202`, la request no envía: el worker lo despacha; guardas en orden fijo, `FOR UPDATE` del turno y del job, nota sin teléfono/email/DNI) y `GET /api/reminders/follow-up` (`no_response`/`delivery_failed`, cursor y totales). `reconcile` no cancela un reenvío en cola salvo reprogramación, cancelación o paso quitado; el `sent` de un reenvío lleva `manual: true`. Confirmación manual con la transición existente (sin endpoint nuevo). SPA: timeline con «Reenviar» en el detalle del turno y panel «Sin confirmar / Con fallo de envío» con filtro «Solo para llamar» en la agenda (solo admin/recepción). Hallazgo: Meta informa con segundos enteros, así que un `delivered` puede quedar milisegundos "antes" del `sent`; timeline y reporte comparan contra el `sent` truncado al segundo (requisito agregado a la delta-spec). `--strict` pedía dividir cinco requisitos largos (cuatro de la validación del change y «Cifras por paso y canal» al sincronizar): se dividieron sin cambiar lo que exigen. Gate: 1495 tests backend (+84), 199 frontend (+18), ruff/black/mypy y typecheck limpios, `openspec validate --strict` válido; build del frontend no ejecutado (no pedido). Desvíos documentados en `tasks.md` §Notas de implementación. **Diferido**: UI de consentimiento en la ficha (venía de C-10) → sin change asignado; reenvío masivo y plantilla "turno reprogramado" → sin change asignado.
- **Scope**: Operación de recordatorios desde recepción — timeline + acciones manuales (US-032)
  - Timeline de entregas por turno (`scheduled/sent/delivered/read/failed/skipped/cancelled`) con estados del proveedor
  - Reenvío manual y confirmación manual con auditoría (RN-GL-01); fallos reiterados escalan a email o alerta visible
  - Filtro "pendientes sin confirmar" (no respondieron T-24 h) para la llamada de recepción del día
- **Dependencias**: C-09, C-10
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §US-032
  - `knowledge-base/07_flujos_principales.md` §Flujo 4 (paso 3)
  - `knowledge-base/11_whatsapp_y_recordatorios.md` §4. Costos y transparencia

---

## FASE 4 — Lista de espera, reportes y salida a piloto

### [C-12] `lista-de-espera`
- **Estado**: `[x]` archivado (2026-11-10 → `openspec/changes/archive/2026-11-10-c-12-lista-de-espera/`; specs sincronizados: `waitlist/entries`, `waitlist/offers`, `waitlist/offer-delivery`, `waitlist/offer-link`, `waitlist/conversion-report`, `web/waiting-list` y `web/waitlist-offer` nuevos, `core/data-export` y `core/seed` modificados, `web/reports-admin` modificado y ampliado, `agenda/appointments`, `reminders/delivery-report`, `reminders/whatsapp-webhook` y `web/public-booking` ampliados; E2E `frontend/e2e/waitlist.spec.ts` verde contra la pila de Compose)
- **Notas de cierre**: migración `c12_waiting_list` (tablas `waiting_list_entry`, `waitlist_offer` y `waitlist_event` append-only por trigger y sin PII; unicidad `waiting/offered` por paciente y profesional con `NULLS NOT DISTINCT`; FKs compuestas por clínica; `ReminderJob.appointment_id` pasa a opcional y suma `waitlist_offer_id`; enums con `ADD VALUE` en `autocommit_block`; FKs y CHECKs sobre tablas existentes `NOT VALID → VALIDATE`, único `(waitlist_offer_id, channel)` `CONCURRENTLY`; el downgrade deja los valores de enum). Decisiones del usuario (2026-11-08): **aprobadas las Open Decisions 1–7** tal como estaban (expiración `min(ahora + TTL 4 h, inicio − 60 min)` y sin oferta automática con menos de 15 min de ventana; plantilla con «Tenés hasta las {{vence}}»; estado `cancelled` de la oferta; tras perder la carrera la entrada vuelve a `waiting` prioritaria con motivo `slot_lost` y hasta 3 alternativos; `409 patient_busy` sin tocar la oferta; `409 already_waiting` público; odontólogo de solo lectura sin contacto), más preferencia = período de fechas + franja y días opcionales, priorización con motivo auditado (excepción a FIFO, pregunta Media de `10` resuelta), respuesta por link y por botones de WhatsApp y **solo la cancelación dispara la evaluación**. Comportamiento: la cancelación (recepción o token) evalúa el hueco en `apply_transition()` dentro de la misma transacción (`evaluate_slot`, FIFO con prioridad primero, candidata con `FOR UPDATE SKIP LOCKED` para no esperar a otras transacciones); la oferta se envía como `reminder_job` del paso `waitlist_offer` por WhatsApp (plantilla con botones Tomarlo/Paso) o email, con escalada a email tras tres fallos; aceptar toma `FOR UPDATE` de la oferta y de la entrada, crea un turno `confirmed` de origen `waitlist` validando RN-AG-01 y cancela las ofertas paralelas del mismo hueco; la carrera la gana la primera aceptación y la perdedora queda prioritaria con alternativos (el cambio se confirma antes de responder el `409`); el tick `waitlist_tick` (cada minuto) vence ofertas y rota a la siguiente entrada, y a los tres vencimientos seguidos la entrada pasa a `expired`. Endpoints: `GET/POST/PATCH /api/waiting-list`, `withdraw`, `prioritize`, `DELETE …/priority`, `…/slots`, `…/offers`, `GET /api/waiting-list/offers` con `accept|decline|cancel`, `…/events` y `GET /api/reports/waitlist` (solo admin, con CSV); públicos `POST /api/booking/{slug}/waiting-list` y `/api/waitlist-offer/{token}` (+ `accept`/`decline`) con link firmado de contexto propio (`w1.`), rate-limit y cabeceras `no-store`/`no-referrer`; el webhook de WhatsApp rutea la respuesta por el contexto de la oferta. Exportación completa ampliada a seis archivos y reporte de WhatsApp con la fila «Oferta de lista de espera». SPA: `/lista-de-espera` (cola, alta, oferta manual, panel de ofertas), `/o/:token` (oferta pública, 360 px), paso de anotación en la reserva cuando no hay horarios y pestaña «Lista de espera» en `/admin/reportes`. Hallazgos: la migración `c09_reminder_engine` sembraba plantillas leyendo el catálogo vivo, que ahora incluye `waitlist_offer`, un paso que su CHECK todavía no admite (una base anterior a C-09 con clínicas no habría migrado): C-09 siembra solo sus pasos y `c12_waiting_list` hace el backfill de las dos plantillas de oferta; el `worker` no recarga código, así que con la pila levantada antes de C-12 hay que reiniciarlo antes de crear ofertas; el E2E necesita `BOOKING_RATE_LIMIT` elevado en el contenedor `api` y `E2E_BASE_URL=http://127.0.0.1:5174`. Gate (2026-11-09): 1760 tests backend (+265 sobre 1495), 234 frontend (+35 sobre 199), ruff/black/mypy y typecheck limpios, `openspec validate --strict` válido; E2E Playwright (2026-11-10) `waitlist.spec.ts` 1/1 verde contra la pila de Compose, suite completa 10 passed / 2 skipped (stubs smoke); build del frontend no ejecutado (no pedido). Desvíos documentados en `tasks.md` §Notas de implementación (orden TDD invertido en varios grupos, compensado con chequeo de mutación del gancho de cancelación; extracción de `_contact`/`_match_or_create` reemplazada por reutilización en `BookingPublicService.join_waitlist`; plantilla inactiva falla y escala a email en vez de `skipped`). **Pendiente antes del piloto**: aprobar en Meta la plantilla de oferta (sigue como placeholder, parte de la pregunta Alta de titularidad de plantillas en `10`). **Diferido**: oferta automática del hueco de reprogramaciones, `absent` o `no_show`, mensaje de confirmación de la anotación y link para que el paciente gestione su entrada, y difusión de un hueco a varias entradas → sin change asignado.
- **Scope**: Lista de espera extremo a extremo — paciente + recepción + motor automático (US-022, US-040, Flujo 5)
  - `waiting_list_entry` (una `waiting/offered` por paciente+profesional, RN-LE-01) + `waitlist_offer` con `expires_at` default 4 h (RN-LE-03); anotación con preferencia de profesional y rango
  - Cancelación (cualquier origen) dispara evaluación FIFO con tolerancia de preferencia (RN-LE-02) en la misma transacción lógica (RN-CX-03); oferta por WhatsApp/email con expiración visible; aceptar crea turno origen `waitlist` validando RN-AG-01 (no es sobreturno encubierto, RN-LE-05); rechazar conserva posición (RN-LE-04); 3 vencimientos → `expired`
  - Panel de cola ordenado por antigüedad con filtros; ofrecimiento manual/automático; ofertas pendientes/vencidas; priorización con motivo auditado (excepción a FIFO — pregunta abierta Media en `10`)
  - Carrera doble-aceptación: la primera gana, la segunda vuelve a cola prioritaria con alternativas
  - Migración 006: `waiting_list_entry`, `waitlist_offer`
  - Tests: FIFO con filtro, expiración y rotación, aceptar fuera de expiración rechazado
  - Reporte de conversión lista de espera → turno (diferido de C-13), solo admin, con CSV, sobre eventos (US-050)
- **Dependencias**: C-05, C-08, C-10
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §waiting_list_entry + waitlist_offer
  - `knowledge-base/05_reglas_de_negocio.md` §RN-LE-01 a §RN-LE-05, §RN-CX-03
  - `knowledge-base/06_funcionalidades.md` §US-022, §US-040
  - `knowledge-base/07_flujos_principales.md` §Flujo 5

---

### [C-13] `reportes-admin-export`
- **Estado**: `[x]` archivado (2026-11-05 → `openspec/changes/archive/2026-11-05-c-13-reportes-admin-export/`)
- **Scope**: Reportes mínimos + administración con control y sin lock-in (US-050, US-051)
  - 3 reportes con rango de fechas + CSV: ocupación por profesional/sillón, ausentismo (`no_show` vs cancelación tardía, RN-ST-04), cancelaciones por motivo (RN-CX-04); calculados sobre `appointment_event`, nunca sobre estados mutados (US-050 CA-3)
  - Auditoría de turnos de la clínica (actor, antes/después, timestamp), inmutable, visible solo admin (RBAC); el historial por turno de C-05 se mantiene
  - Exportación completa (turnos, pacientes operativos, eventos) en CSV/JSON con un clic (US-051 CA-3), auditada en `auth_event` (`data_exported`)
  - Instantánea del horario y recursos en cada `appointment_event` nuevo (migración `c13_event_slot`)
  - **Diferido** (necesita tablas que aún no existen): reporte mensual WhatsApp por clínica → pasa a C-10 (necesita `reminder_job`/`delivery_event` de C-09); conversión lista de espera → turno → pasa a C-12 (necesita `waiting_list_entry` y origen `waitlist`)
- **Dependencias**: C-03, C-05
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 6 (US-050, US-051)
  - `knowledge-base/04_modelo_de_datos.md` §appointment_event
  - `knowledge-base/03_actores_y_roles.md` §RBAC (auditoría/exportación solo admin)

---

### [C-14] `hardening-piloto`
- **Estado**: `[x]` archivado (2026-11-10 → openspec/changes/archive/2026-11-10-c-14-hardening-piloto/)
- **Scope**: Endurecimiento para piloto en 1-2 clínicas amigas (criterio: NO cadenas multi-sede — IN-02)
  - Headers seguros + CORS restrictivo + rate-limit global y estricto en booking/webhooks (Redis); validación Pydantic v2 en todos los bordes; E.164 con phonenumbers; logs sin PII (teléfonos enmascarados)
  - Backups cifrados Postgres con PITR; `MANAGE_TOKEN_TTL_H`, `BOOKING_RATE_LIMIT` calibrados; alerta de costo WhatsApp mensual por umbral (sin corte automático en v1.0)
  - Mitigación de cortes SU-06: agenda del día imprimible/cacheada + cola de reintentos en frontend (offline real es fase posterior)
  - Consentimiento/retención/portabilidad mínimos desde v1 para no re-arquitecturar en fase clínica (pregunta Alta Ley 27.706/26.529 en `10` — validar con asesor legal + PO)
  - Checklist de piloto: 6 plantillas Meta + 2 variantes listas (email cubre si alguna se rechaza), métricas de éxito cableadas (0 solapamientos, ausentismo −20 %, confirmación ≥ 60 % pre T-24 h, huecos recuperados ≥ 10 %, online ≥ 30 %)
  - Tests E2E Playwright del circuito crítico: reserva → recordatorio → confirmación → presente
  - Playwright del circuito de recepción en CI (diferido de C-06; hoy corre en el gate local con el stack levantado)
  - Rol DB `app_writer` para la app (diferido de C-05): `MIGRATION_DATABASE_URL` separado del usuario de la app; `GRANT SELECT, INSERT` sin `UPDATE/DELETE` sobre `appointment_event`, `agenda_config_event` y `auth_event`
- **Notas de cierre**: Migración c14_hardening_pilot (down_revision="c12_waiting_list"): rol de la app app_writer con SELECT, INSERT, UPDATE en tablas operativas, SELECT, INSERT en las append-only (appointment_event, agenda_config_event, auth_event) y sin DELETE en ninguna (regla 7), con DEFAULT PRIVILEGES para tablas futuras; MIGRATION_DATABASE_URL separado del usuario de la app (APP_DB_USER=turnos_app, creado por python -m app.ops.db_roles desde el servicio migrate; en prod compose.prod.yaml exige APP_DB_PASSWORD); clinic.whatsapp_monthly_alert_micros. Borde HTTP: headers seguros, ALLOWED_HOSTS, CORS cerrado, X-Request-ID, logs JSON con redacción de teléfono, email, DNI, JWT y tokens (el log de acceso usa la plantilla de la ruta), 500 uniforme sin traza, SQLSTATE de concurrencia → 409 concurrent_update y 57014 → 503 db_timeout, 422 del personal sin input, timeouts por conexión en API y worker, rate-limit global en Redis con degradación a memoria (auth y reserva siguen fail-closed), cupo de firmas inválidas en el webhook de Meta y Bearer estricto con WWW-Authenticate. Reportes: GET /api/reports/pilot (+CSV, las 5 métricas de 01 y auditoría de solapamientos), GET /api/reports/whatsapp/budget (política whatsapp_monthly_alert_usd, sin corte automático) y GET /api/exports/patients/{id} (solo admin, auditado). SPA: reintentos con backoff, banner de red, ErrorBoundary, Skeleton, validadores compartidos, cola de reintentos en memoria para confirmación y asistencia, agenda imprimible /agenda/imprimir, pestaña «Piloto», banner de presupuesto y umbral en Políticas. CI: nuevo ci-e2e.yml con el stack real y critical-circuit.spec.ts (reserva → recordatorio → confirmación → presente), Vitest en ci-frontend.yml y se elimina el stub playwright-smoke. Docs: docs/piloto/ (checklist, backups PITR, privacidad y retención) y ops/backup/. Hallazgos: to_json_value no serializaba datetime.time, por lo que la exportación completa JSON fallaba con entradas de lista de espera con franja (C-12/C-13); corregido con test de regresión. El gate de formato falló porque el código se había formateado con black 26 y el proyecto fija black>=24.0,<25.0: reformateados con black 24 los tres archivos que difieren (tests/core/test_sessions.py, tests/models/test_appointment_race_db.py, tests/modules/test_appointments_week_perf.py), y no hay que correr ruff format porque CI formatea con black. Con el gate de formato en verde, mypy sacó a la luz dos errores en tests (test_reports_pilot.py: pend tipado como dict[str, Any]; test_patient_export_api.py: assert paciente.phone_e164 is not None). Gate (2026-11-10): 1894 tests backend, ruff/black 24/mypy limpios y CI verde en el commit 4919a9b. Pendiente antes del piloto: aprobación de las 8 Open Decisions de proposal.md por el usuario/Tech Lead; consulta con asesor legal por retención y portabilidad (Ley 25.326/26.529); aprobar las plantillas en Meta y la decisión comercial del número. Diferido: offline real (service worker, IndexedDB) → fase posterior (SU-06); purga o anonimización por retención → asesor legal; corte automático de envíos por presupuesto; WAF/CDN, secret manager y APM externo → opcionales.
- **Dependencias**: C-06, C-11, C-12, C-13
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/08_arquitectura_propuesta.md` §Seguridad, §Variables de entorno
  - `knowledge-base/01_vision_y_objetivos.md` §Métricas de éxito
  - `knowledge-base/10_preguntas_abiertas.md` §IN-01, §IN-02, §Ley 27.706/26.529
  - `knowledge-base/09_decisiones_y_supuestos.md` §SU-06, §SU-07

---

## FASE 5 — Circuito clínico-financiero (POSTERIOR al piloto, backlog registrado)

> Los changes C-15 a C-19 están fuera del MVP agenda-first (ver `01` §Fuera de alcance y `10` §Registro para fases posteriores).
> Se secuencian aquí para que el roadmap llegue al "circuito argentino cerrado" del Discovery sin contaminar el piloto.
> Orden propuesto (a confirmar por Dueño + PO — pregunta Baja en `10`): clínica → cobros → ARCA → obras sociales → escala.

### [C-15] `historia-clinica-odontograma`
- **Estado**: `[ ]` pendiente
- **Scope**: Ficha clínica + anamnesis + odontograma FDI por cara + adjuntos + evoluciones + planes/presupuestos por fases en PDF (engancha en `patient_id`/`appointment_id` estables de v1.0, sin migración rompiente — DD-02)
  - Odontograma permanente/temporal por cara; periodontograma y ortodoncia/cefalometría como extensión posterior; consentimientos con firma Ley 25.506; ReNaPDiS/HL7 FHIR donde aplique
  - Recepción no accede a datos clínicos (regla transversal heredada de `03`)
- **Dependencias**: C-14
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §Registro para fases posteriores (clínica)
  - `knowledge-base/03_actores_y_roles.md` §Reglas transversales (recepción sin clínica)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-02
  - `docs/discovery/discovery.md` §D3 MVP sugerido (ficha clínica), §C4.5

---

### [C-16] `cobros-mercadopago`
- **Estado**: `[ ]` pendiente
- **Scope**: Caja diaria (ingresos/gastos/deudas/arqueo) + señas al reservar + Mercado Pago QR/link con conciliación automática en caja + cuenta corriente y cuotas
- **Dependencias**: C-15
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §Registro para fases posteriores (cobros)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-01 (stack Python/FastAPI; SDK MP vía REST), §DD-02
  - `docs/discovery/discovery.md` §C4.4 (cobros que concilian solos)

---

### [C-17] `factura-arca`
- **Estado**: `[ ]` pendiente
- **Scope**: Factura electrónica ARCA emitida en el mismo cobro (CAE), con fixtures de homologación y re-facturación; multi-comprobante como extensión posterior
- **Dependencias**: C-16
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §Registro para fases posteriores (fiscal)
  - `docs/discovery/discovery.md` §C2.7 (ARCA + MP en el mismo cobro)

---

### [C-18] `obras-sociales-liquidacion`
- **Estado**: `[ ]` pendiente
- **Scope**: Nomenclador por convenio con copago/coseguro + autorizaciones + liquidación mensual exportable + flujo Círculo → Federación; validación online contra OS (referencia DentalTec) como sub-fase 2 si no entra junta
- **Dependencias**: C-17
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §Registro para fases posteriores (fiscal/OS)
  - `knowledge-base/09_decisiones_y_supuestos.md` §SU-03 (identidad fuerte DNI/CUIL, reconciliación de pacientes)
  - `docs/discovery/discovery.md` §C2.1, §C2.2 (validación preventiva, liquidaciones)

---

### [C-19] `multisede-escala`
- **Estado**: `[ ]` pendiente
- **Scope**: Multi-sucursal plena + comisiones + laboratorio/stock/esterilización livianos + CRM/recall avanzado + portal del paciente con login + API pública + Google Calendar + IA clínica (CDSS/dictado/rx) + videoconsulta; permisos granulares reemplazando el enum de v1.0 (deuda documentada DD-03); resuelve IN-02
- **Dependencias**: C-18
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §IN-02, §Registro para fases posteriores (crecimiento)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-03 (deuda permisos), §DD-07 (multi-tenant lógico)
  - `docs/discovery/discovery.md` §D3 Para etapas posteriores

---
