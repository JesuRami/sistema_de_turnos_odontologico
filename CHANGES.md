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
  - `Dockerfile` backend (api + worker) + `docker-compose.yml` con servicios `api`, `db`, `redis`, `worker`, `frontend` + Postgres gestionado por tenant (DD-07: 1 DB por clínica)
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
- **Estado**: `[ ]` pendiente
- **Scope**: Entidades base + migraciones iniciales + seed mínimo (sin turnos todavía)
  - Modelos: `Clinic` (slug único, timezone, `cancellation_window_hours=24`, `reminder_steps` jsonb), `Professional`, `Chair`, `ScheduleRule`, `Patient` (liviano: nombre + teléfono E.164/email, `whatsapp_opt_in`, DNI opcional no único — SU-03), `User` (enum `admin/recepcion/odontologo`, argon2id, `professional_id` nullable)
  - `clinic_id` obligatorio en todas las tablas operativas (partición lógica futura, DD-07)
  - Migración 001: tablas core + índices (`slug`, `(clinic_id, active)`, `(clinic_id, phone_e164)`, trigram en `full_name`)
  - Seed por clínica: 1 clinic + 1 admin + 1 chair "Sillón 1" + 1 professional ejemplo inactivo + 3 `notification_template` placeholder + catálogo de motivos de bloqueo
  - Tests: constraints de unicidad, match de paciente por teléfono normalizado
- **Dependencias**: C-01
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §clinic, §professional, §chair, §schedule_rule, §patient, §user / role, §Seed data inicial
  - `knowledge-base/08_arquitectura_propuesta.md` §Configuración por clínica
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-07, §SU-03, §SU-04

---

### [C-03] `auth-rbac`
- **Estado**: `[ ]` pendiente
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
- **Estado**: `[ ]` pendiente
- **Scope**: Configuración de agenda por la clínica — backend (US-001 a US-004)
  - Modelos/CRUD: `GET/POST/PUT /professionals`, `/chairs`, `/schedules`, `/blocks` (admin CRUD; recepción R; odontólogo R propios)
  - `ScheduleRule` por (professional, chair, weekday) con vigencia desde/hasta; rechazo de reglas solapadas (RN-AG-05)
  - `Block` con al menos un objetivo (RN-BL-01); creación que pisa turnos vigentes exige resolución explícita en la misma transacción (RN-BL-02); pasados inmutables (RN-BL-03); feriados como bloqueo manual multi-recurso (RN-BL-04)
  - Políticas de clínica editables: ventana de cancelación (default 24 h), pasos de recordatorio (72/24/3 h), tope sobreturnos (default 2), expiración de ofertas (default 4 h); cambios solo afectan turnos futuros (US-004 CA-2)
  - Desactivar profesional/sillón impide nuevas reservas, conserva historial (US-001 CA-1)
  - Migración 003: `schedule_rule`, `block`, columnas de política en `clinic`
  - Tests: solapamiento de reglas, bloqueo con turnos afectados, cambio de políticas no toca jobs programados
- **Dependencias**: C-03
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §schedule_rule, §block
  - `knowledge-base/05_reglas_de_negocio.md` §RN-AG-05, §RN-BL-01 a §RN-BL-04
  - `knowledge-base/06_funcionalidades.md` §Épica 1 (US-001 a US-004)

---

### [C-05] `appointments-core`
- **Estado**: `[ ]` pendiente
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
- **Estado**: `[ ]` pendiente
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
- **Estado**: `[ ]` pendiente
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

---

### [C-08] `gestion-por-token`
- **Estado**: `[ ]` pendiente
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
- **Estado**: `[ ]` pendiente
- **Scope**: Reminder engine persistente sobre Postgres — scheduler + sender (US-030 backend, Flujo 3, DD-06)
  - `reminder_job` (`scheduled_for` en zona de la clínica, idempotencia única `(appointment_id, step, channel)`), `notification_template` (72/24/3 h + alta de turno), `delivery_event`
  - Worker tick 60 s con `FOR UPDATE SKIP LOCKED LIMIT 100`; pre-envío: turno vigente (si no → `cancelled`, RN-CX-03), opt-in del canal (RN-WA-01), plantilla activa, ventana 24 h de Meta
  - Reprogramar recalcula pendientes; cancelar marca `cancelled`; anti-ruido: solo pasos futuros si el turno se crea cerca del inicio; tope: jamás enviar de un turno ya iniciado (→ `skipped`)
  - Email como respaldo/escalado tras 3 fallos con backoff (5 min → 30 min → 2 h → `failed`); `provider_message_id` guardado; costo atribuible por clínica y paso (RN-WA-05)
  - Migración 005: `reminder_job`, `delivery_event`, `notification_template`, `consent`
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
- **Estado**: `[ ]` pendiente
- **Scope**: Canal WhatsApp oficial bidireccional — envío Cloud API + webhook de respuestas (US-031, DD-05)
  - Alta de turno + plantillas `es_AR` categoría `utility` (`turno_creado_v1`, `recordatorio_72h_v1`, `recordatorio_24h_v1`, `recordatorio_3h_v1`) con botones Confirmar/Cambiar, SÍ/NO; fecha/hora formato argentino explícito
  - `POST /webhooks/whatsapp` con verificación `X-Hub-Signature-256` (401 + log sin firma); deduplicación por `provider_event_id`; estados `delivered/read/failed` actualizan el job
  - "SÍ" confirma (misma transición que el link, idempotente); "NO"/reprogramar → link de gestión o clínica según ventana; "STOP"/BAJA bloquea el canal de inmediato con confirmación (RN-WA-01/03)
  - Opt-in en reserva o cargado por recepción; cada cambio de consentimiento auditado con fuente
  - Proceso operativo de alta de plantillas por clínica + decisión número propio vs compartido (pregunta abierta Alta en `10`) antes del piloto
- **Dependencias**: C-08, C-09
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/05_reglas_de_negocio.md` §RN-WA-01 a §RN-WA-05, §RN-ST-02
  - `knowledge-base/06_funcionalidades.md` §US-030, §US-031
  - `knowledge-base/11_whatsapp_y_recordatorios.md` §1. Diseño del canal, §2. Plantillas, §5. Riesgos del canal
  - `knowledge-base/10_preguntas_abiertas.md` §alta de plantillas / número WhatsApp

---

### [C-11] `timeline-recordatorios`
- **Estado**: `[ ]` pendiente
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
- **Estado**: `[ ]` pendiente
- **Scope**: Lista de espera extremo a extremo — paciente + recepción + motor automático (US-022, US-040, Flujo 5)
  - `waiting_list_entry` (una `waiting/offered` por paciente+profesional, RN-LE-01) + `waitlist_offer` con `expires_at` default 4 h (RN-LE-03); anotación con preferencia de profesional y rango
  - Cancelación (cualquier origen) dispara evaluación FIFO con tolerancia de preferencia (RN-LE-02) en la misma transacción lógica (RN-CX-03); oferta por WhatsApp/email con expiración visible; aceptar crea turno origen `waitlist` validando RN-AG-01 (no es sobreturno encubierto, RN-LE-05); rechazar conserva posición (RN-LE-04); 3 vencimientos → `expired`
  - Panel de cola ordenado por antigüedad con filtros; ofrecimiento manual/automático; ofertas pendientes/vencidas; priorización con motivo auditado (excepción a FIFO — pregunta abierta Media en `10`)
  - Carrera doble-aceptación: la primera gana, la segunda vuelve a cola prioritaria con alternativas
  - Migración 006: `waiting_list_entry`, `waitlist_offer`
  - Tests: FIFO con filtro, expiración y rotación, aceptar fuera de expiración rechazado
- **Dependencias**: C-05, C-08, C-10
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §waiting_list_entry + waitlist_offer
  - `knowledge-base/05_reglas_de_negocio.md` §RN-LE-01 a §RN-LE-05, §RN-CX-03
  - `knowledge-base/06_funcionalidades.md` §US-022, §US-040
  - `knowledge-base/07_flujos_principales.md` §Flujo 5

---

### [C-13] `reportes-admin-export`
- **Estado**: `[ ]` pendiente
- **Scope**: Reportes mínimos + administración con control y sin lock-in (US-050, US-051)
  - 4 reportes con rango de fechas + CSV: ocupación por profesional/sillón, ausentismo (`no_show` vs cancelación tardía, RN-ST-04), cancelaciones por motivo (RN-CX-04), conversión lista de espera → turno; calculados sobre `appointment_event`, nunca sobre estados mutados (US-050 CA-3)
  - Auditoría por turno (actor, antes/después, timestamp), inmutable, visible solo admin (RBAC)
  - Exportación completa (turnos, pacientes operativos, eventos) en CSV/JSON con un clic (US-051 CA-3)
  - Reporte mensual WhatsApp por clínica: enviados/entregados/leídos por paso + costo atribuido (base del pricing — RN-WA-05, archivo `11` §4)
- **Dependencias**: C-03, C-05
- **Governance**: ALTO
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 6 (US-050, US-051)
  - `knowledge-base/04_modelo_de_datos.md` §appointment_event
  - `knowledge-base/03_actores_y_roles.md` §RBAC (auditoría/exportación solo admin)
  - `knowledge-base/11_whatsapp_y_recordatorios.md` §4. Costos y transparencia

---

### [C-14] `hardening-piloto`
- **Estado**: `[ ]` pendiente
- **Scope**: Endurecimiento para piloto en 1-2 clínicas amigas (criterio: NO cadenas multi-sede — IN-02)
  - Headers seguros + CORS restrictivo + rate-limit global y estricto en booking/webhooks (Redis); validación Pydantic v2 en todos los bordes; E.164 con phonenumbers; logs sin PII (teléfonos enmascarados)
  - Backups cifrados Postgres con PITR; `MANAGE_TOKEN_TTL_H`, `BOOKING_RATE_LIMIT` calibrados; alerta de costo WhatsApp mensual por umbral (sin corte automático en v1.0)
  - Mitigación de cortes SU-06: agenda del día imprimible/cacheada + cola de reintentos en frontend (offline real es fase posterior)
  - Consentimiento/retención/portabilidad mínimos desde v1 para no re-arquitecturar en fase clínica (pregunta Alta Ley 27.706/26.529 en `10` — validar con asesor legal + PO)
  - Checklist de piloto: 6 plantillas Meta + 2 variantes listas (email cubre si alguna se rechaza), métricas de éxito cableadas (0 solapamientos, ausentismo −20 %, confirmación ≥ 60 % pre T-24 h, huecos recuperados ≥ 10 %, online ≥ 30 %)
  - Tests E2E Playwright del circuito crítico: reserva → recordatorio → confirmación → presente
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
  - `discovery/discovery.md` §D3 MVP sugerido (ficha clínica), §C4.5

---

### [C-16] `cobros-mercadopago`
- **Estado**: `[ ]` pendiente
- **Scope**: Caja diaria (ingresos/gastos/deudas/arqueo) + señas al reservar + Mercado Pago QR/link con conciliación automática en caja + cuenta corriente y cuotas
- **Dependencias**: C-15
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §Registro para fases posteriores (cobros)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-01 (stack Python/FastAPI; SDK MP vía REST), §DD-02
  - `discovery/discovery.md` §C4.4 (cobros que concilian solos)

---

### [C-17] `factura-arca`
- **Estado**: `[ ]` pendiente
- **Scope**: Factura electrónica ARCA emitida en el mismo cobro (CAE), con fixtures de homologación y re-facturación; multi-comprobante como extensión posterior
- **Dependencias**: C-16
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §Registro para fases posteriores (fiscal)
  - `discovery/discovery.md` §C2.7 (ARCA + MP en el mismo cobro)

---

### [C-18] `obras-sociales-liquidacion`
- **Estado**: `[ ]` pendiente
- **Scope**: Nomenclador por convenio con copago/coseguro + autorizaciones + liquidación mensual exportable + flujo Círculo → Federación; validación online contra OS (referencia DentalTec) como sub-fase 2 si no entra junta
- **Dependencias**: C-17
- **Governance**: CRITICO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §Registro para fases posteriores (fiscal/OS)
  - `knowledge-base/09_decisiones_y_supuestos.md` §SU-03 (identidad fuerte DNI/CUIL, reconciliación de pacientes)
  - `discovery/discovery.md` §C2.1, §C2.2 (validación preventiva, liquidaciones)

---

### [C-19] `multisede-escala`
- **Estado**: `[ ]` pendiente
- **Scope**: Multi-sucursal plena + comisiones + laboratorio/stock/esterilización livianos + CRM/recall avanzado + portal del paciente con login + API pública + Google Calendar + IA clínica (CDSS/dictado/rx) + videoconsulta; permisos granulares reemplazando el enum de v1.0 (deuda documentada DD-03); resuelve IN-02
- **Dependencias**: C-18
- **Governance**: MEDIO
- **Leer antes**:
  - `knowledge-base/10_preguntas_abiertas.md` §IN-02, §Registro para fases posteriores (crecimiento)
  - `knowledge-base/09_decisiones_y_supuestos.md` §DD-03 (deuda permisos), §DD-07 (multi-tenant lógico)
  - `discovery/discovery.md` §D3 Para etapas posteriores

---
