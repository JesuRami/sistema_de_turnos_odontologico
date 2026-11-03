# Proposal — C-04 `agenda-config`

> Rehecha el 2026-11-03. La versión archivada el 2026-11-02 se desarchivó: tenía
> 0/40 tasks, proponía DDL imposible en PostgreSQL (`EXCLUDE … NOT VALID` y
> `CONCURRENTLY`), ignoraba el modelo real de C-02 (`schedule_rule` con
> `start_time/end_time` + `valid_from/valid_to`; `clinic` ya con
> `cancellation_window_hours` y `reminder_steps`), interpretaba el "objetivo" de
> RN-BL-01 como texto libre e incluía alcance de otros changes (token de
> paciente → C-08, re-verificación JWT → C-03). Sus specs fusionados en
> `openspec/specs/` (`core/schedule`, `identity/agenda`) se retiraron.

## Why

La clínica necesita cargar sus recursos reales (profesionales, sillones), la
plantilla semanal sobre la que se calculan huecos, los bloqueos (vacaciones,
feriados, mantenimiento) y sus políticas operativas (US-001 a US-004). Sin esto
no hay agenda que reservar: C-05 (`appointments-core`) y C-07 (booking público)
dependen de que `schedule_rule` y `block` existan y sean consistentes.

## What Changes

- **API de configuración** (prefijo `/api`, RBAC según la matriz de
  `03_actores_y_roles.md`):
  - `GET/POST/PATCH /api/professionals` y `/api/chairs` — admin CRUD; recepción
    R; odontólogo R solo su propio profesional (sillones: lectura para todo el
    personal, no tienen dueño). La baja es `PATCH active=false` (sin borrado).
  - `GET/POST/PATCH /api/schedules` — plantilla semanal; admin CRUD; recepción R;
    odontólogo R propias.
  - `GET/POST/PATCH/DELETE /api/blocks` + `POST /api/blocks/closure` — admin CRUD;
    recepción y odontólogo CR (odontólogo solo con su `professional_id`); cierre
    de clínica/feriado solo admin.
  - `GET/PATCH /api/clinic/policies` — admin RU; recepción R.
- **Anti-solape de reglas (RN-AG-05, US-002 CA-2) en la base**: `EXCLUDE USING
  gist` sobre `(clinic_id, professional_id, chair_id, weekday)` con franja horaria
  y vigencia intersectadas, solo entre reglas activas. Colisión → `409
  schedule_overlap` con los ids en conflicto.
- **Bloqueos (RN-BL-01/03/04)**: tabla `block` con profesional y/o sillón
  (CHECK al menos uno), rango `timestamptz`, motivo de catálogo cerrado
  (`vacaciones, feriado, mantenimiento, reunion, otro`) y notas opcionales.
  Bloqueos con inicio pasado son inmutables (solo se puede mover el fin de uno en
  curso); los futuros se editan o se retiran con baja lógica. Feriado/cierre =
  un bloqueo por sillón activo en una sola transacción.
- **Políticas de clínica (US-004)**: se agregan `max_overbookings_per_day`
  (default 2) y `waitlist_offer_ttl_hours` (default 4) junto a las existentes
  `cancellation_window_hours` (24) y `reminder_steps` (72/24/3 h).
- **Auditoría de configuración (US-001 CA-3)**: tabla append-only
  `agenda_config_event` (trigger que rechaza UPDATE/DELETE) escrita en la misma
  transacción que cada mutación.
- **Migración `c04_agenda_config`** (una sola revisión, regla 3).

## Out of scope (explícito)

- **RN-BL-02 (bloqueo que pisa turnos vigentes)**: la tabla `appointment` nace en
  C-05. C-04 deja el bloqueo creable sin esa verificación y C-05 agrega el
  chequeo + resolución en la misma transacción (registrado en CHANGES y design).
- **"Desactivar impide nuevas reservas" (US-001 CA-1) del lado de la reserva**:
  C-04 garantiza `active=false` + historial intacto; el rechazo `409` al reservar
  lo implementan C-05 (recepción) y C-07 (online).
- **US-004 CA-2 (cambiar pasos no toca jobs ya programados)**: no hay jobs hasta
  C-09. Contrato para C-09: el job copia el paso al programarse y nunca relee la
  política.
- Cálculo de huecos / disponibilidad (C-07), UI de agenda (C-06), feriados
  nacionales automáticos (RN-BL-04: lista manual en v1.0).

## Capabilities

### New Capabilities

- `agenda/config`: recursos, plantilla semanal, bloqueos, políticas y auditoría
  de configuración de agenda por clínica.

### Modified Capabilities

- (ninguna: `core/clinic-resources` ya cubre la estructura base y no cambia su
  comportamiento)

## Impact

- Backend: módulo `app/modules/agenda` (hoy stub) pasa a tener routers/servicios
  de configuración; `app/modules/clinic` suma políticas. Schemas Pydantic v2 con
  `extra='forbid'` (regla 2).
- DB: `btree_gist` (extensión *trusted* PG13+), constraint EXCLUDE en
  `schedule_rule`, columnas nuevas en `clinic`, tablas `block` y
  `agenda_config_event`. Excepción acotada a la regla 11 documentada en el design.
- Tests: Postgres + Redis reales (regla 9), aislamiento cross-tenant (regla 4),
  datos sintéticos (regla 13).
- Governance: **MEDIO**.
