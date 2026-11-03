# Design — C-04 `agenda-config`

## Context

C-02 creó `clinic`, `professional`, `chair` y `schedule_rule` (solo estructura +
CHECKs). C-03 dejó `require_roles`, `scope_by_professional` y
`get_one_scoped_or_404` como única puerta de autorización y alcance. C-04 agrega
la API de configuración sobre esas piezas, el anti-solape de reglas en la base,
los bloqueos, las políticas y su auditoría. Todavía no existen `appointment`
(C-05) ni `reminder_job` (C-09).

## Decisions

### D1. Anti-solape de `schedule_rule` con EXCLUDE (RN-AG-05, regla 1)

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE schedule_rule ADD CONSTRAINT ex_schedule_rule_no_overlap
  EXCLUDE USING gist (
    clinic_id WITH =, professional_id WITH =, chair_id WITH =, weekday WITH =,
    tsrange(DATE '2000-01-01' + start_time, DATE '2000-01-01' + end_time) WITH &&,
    daterange(valid_from, valid_to, '[]') WITH &&
  ) WHERE (active);
```

- PostgreSQL no tiene `timerange`: la franja se proyecta sobre una fecha fija
  (`date + time` es inmutable, apto para índice). Rango `[)` → 09-13 y 13-17 no
  colisionan.
- `daterange(valid_from, valid_to, '[]')`: `valid_to` es inclusivo y `NULL` =
  vigencia abierta.
- Solo reglas `active`: desactivar una regla libera la franja.
- El servicio traduce `ExclusionViolation` a `409 schedule_overlap` y adjunta los
  ids de las reglas que colisionan (consulta con el mismo predicado). No hay
  pre-chequeo en Python que pueda competir con la base.
- Se compara el par (profesional, sillón), como pide US-002 CA-2. Que un
  profesional atienda dos sillones a la vez es un patrón válido en odontología;
  la doble ocupación real la impide el EXCLUDE de `appointment` (C-05).

### D2. Excepción acotada a la regla 11

`EXCLUDE` no admite `NOT VALID` ni creación `CONCURRENTLY` (son exclusivos de
CHECK/FK e índices simples). `ADD CONSTRAINT … EXCLUDE` toma `ACCESS EXCLUSIVE`
mientras construye el índice. Se acepta porque `schedule_rule` es una tabla de
configuración (decenas de filas por clínica) y el sistema está pre-piloto; si ya
hubiera datos solapados la migración falla en vez de corromper (fail-fast). Las
columnas nuevas de `clinic` sí siguen la regla: `ADD COLUMN … DEFAULT` constante
(metadata-only en PG11+) + `CHECK … NOT VALID` → `VALIDATE`. `block` y
`agenda_config_event` son tablas nuevas: sus índices se crean junto a la tabla
(mismo criterio que C-02/C-03).

### D3. Bloqueos (RN-BL-01/03/04)

Tabla `block`: `id, clinic_id, professional_id NULL, chair_id NULL, starts_at,
ends_at (timestamptz), reason block_reason, notes text NULL (≤500),
created_by_user_id, removed_at NULL, removed_by_user_id NULL, created_at,
updated_at`.

- `CHECK (professional_id IS NOT NULL OR chair_id IS NOT NULL)` (RN-BL-01) y
  `CHECK (ends_at > starts_at)`. FKs compuestas `(clinic_id, *_id)` intra-tenant.
- `reason` es ENUM PG (`vacaciones, feriado, mantenimiento, reunion, otro`, KB
  `04_modelo_de_datos.md`): catálogo cerrado y chico; ampliar = migración.
- Índice `(clinic_id, starts_at)` para listados por rango. El índice gist para
  disponibilidad llega con su consumidor (C-07).
- **Inmutabilidad (RN-BL-03)**: un bloqueo que ya terminó (`ends_at <= now`) no
  admite cambios (`409 block_immutable`). Uno en curso (`starts_at <= now <
  ends_at`) solo admite mover `ends_at` a un valor `>= now`. Uno futuro se edita
  o se retira. No se crea un bloqueo que termine en el pasado (`422`).
- **Retiro**: `DELETE` = baja lógica (`removed_at`, `removed_by_user_id`); el
  listado excluye retirados. Nunca borrado físico.
- **Cierre de clínica / feriado (RN-BL-04)**: `POST /api/blocks/closure` crea un
  bloqueo por cada sillón activo (todo turno ocupa un sillón, así que cubre la
  clínica entera) en una única transacción. Solo admin.
- **RN-BL-02 diferida a C-05** (ver proposal): no se agrega un stub
  especulativo; C-05 suma el chequeo a `BlocksService.create/update`.

### D4. Políticas de clínica (US-004)

Columnas nuevas en `clinic`: `max_overbookings_per_day int NOT NULL DEFAULT 2
CHECK >= 0` (RN-SB-03) y `waitlist_offer_ttl_hours int NOT NULL DEFAULT 4 CHECK
> 0` (RN-LE-03). Se usan **horas**, coherentes con `cancellation_window_hours`
existente. `reminder_steps` se valida con `ReminderStep` (C-02) + 1..5 pasos y
offsets únicos. `PATCH` parcial; cada cambio audita valores anterior/nuevo.

Contrato para C-09 (US-004 CA-2): el `reminder_job` copia `offset_h/channel` al
programarse y no relee la política. C-04 no puede probarlo (no hay jobs); queda
escrito en CHANGES.

### D5. Auditoría de configuración (US-001 CA-3)

`agenda_config_event` append-only, análoga a `auth_event`: `id, clinic_id,
actor_user_id, entity (professional|chair|schedule_rule|block|clinic_policy),
entity_id, action (created|updated|deactivated|reactivated|removed), changes
jsonb ({campo: [anterior, nuevo]}), created_at`. Trigger `BEFORE UPDATE OR
DELETE` que levanta excepción. Se escribe en la misma transacción que la
mutación: si falla la auditoría, falla la mutación (espíritu de RN-GL-01).
`appointment_event` sigue siendo exclusivo de turnos (C-05).

### D6. API, RBAC y alcance

- Routers finos → servicios; todo filtro por `principal.clinic_id` (el body nunca
  trae `clinic_id`: `extra='forbid'` lo rechaza con 422).
- Odontólogo: `scope_by_professional` sobre `professional.id`,
  `schedule_rule.professional_id` y `block.professional_id`. Pedir por id una
  fila ajena → `404` (no `403`). Bloqueos solo-sillón no son "propios".
- `professional_id`/`chair_id` de otra clínica en el body → `422` (sin revelar
  existencia), igual que `UsersService._assert_professional`.
- Crear regla o bloqueo sobre profesional/sillón inactivo → `422
  resource_inactive`.
- Listados con paginación por cursor (regla 8). `encode/decode_cursor` de
  `users.service` se mueven a `app/common/pagination.py` y se reutilizan.
- `PATCH` en lugar de `PUT` (coherente con `/api/users`).

## Risks / Trade-offs

- **Lock de la migración EXCLUDE** → aceptado pre-piloto (D2).
- **Bloqueos solapados entre sí**: se permiten (dos motivos sobre el mismo rango
  no son un error de negocio).
- **Sillones nuevos tras un feriado cargado** quedan sin bloquear: el admin carga
  el cierre después de dar de alta sillones; se documenta en el README.

## Migration Plan

`c04_agenda_config` (revises `c03_auth_rbac`): btree_gist → EXCLUDE en
`schedule_rule` → columnas + CHECK NOT VALID/VALIDATE en `clinic` → enums →
`block` → `agenda_config_event` + trigger. Downgrade en orden inverso (pierde
bloqueos y auditoría de configuración; se advierte en el README, como C-03).
CI ya corre `upgrade → downgrade -1 → upgrade`.
