# Design — C-05 `appointments-core`

## Context

C-02 creó `patient` (con índice trigram en `full_name`) y los recursos; C-03
dejó `require_roles`, `scope_by_professional` y `get_one_scoped_or_404` como
única puerta de autorización y alcance; C-04 dejó `schedule_rule` con EXCLUDE,
`block`, las políticas de clínica (`cancellation_window_hours`,
`max_overbookings_per_day`) y el patrón de auditoría append-only con trigger y
`clock_timestamp()`. `btree_gist` y `pg_trgm` ya están instaladas. La app se
conecta a Postgres como owner de la base. Motivación y alcance: ver
`proposal.md`.

## Goals / Non-Goals

**Goals:**
- Que ninguna combinación de requests concurrentes pueda dejar dos turnos
  vigentes no sobreturno solapados (la base decide, el servicio solo traduce).
- Un único punto que define las transiciones de estado y escribe la auditoría.
- Dejar el servicio de alta y el cálculo de alternativos reutilizables por C-07.

**Non-Goals:**
- Endpoints públicos, `manage_token`, jobs de recordatorio, lista de espera.
- Optimizar el listado de agenda más allá de los índices: el objetivo de US-010
  CA-3 (< 2 s, 500 turnos/semana) se mide en C-06.

## Decisions

### D1. Rango ocupado explícito (`occupied_until`) en vez de columna generada

La KB propone `duration_range` generada. No es viable: `timestamptz + interval`
es `STABLE` (depende de la zona para días/meses), y una columna generada o un
índice exigen expresiones `IMMUTABLE`. Además el buffer vive en `professional`,
y una columna generada no puede leer otra tabla.

Se guarda `occupied_until timestamptz NOT NULL`, calculada por el servicio como
`ends_at + buffer_min` del profesional al crear o reprogramar (snapshot: cambiar
el buffer después no altera turnos existentes), con `CHECK (occupied_until >=
ends_at)`. Los EXCLUDE usan `tstzrange(starts_at, occupied_until, '[)')`, cuyo
constructor sí es inmutable.

### D2. Dos EXCLUDE con predicado de vigencia (regla dura 1)

```sql
EXCLUDE USING gist (clinic_id WITH =, professional_id WITH =,
                    tstzrange(starts_at, occupied_until, '[)') WITH &&)
  WHERE (status IN ('pending','confirmed','present') AND NOT is_overbooking)
-- y el análogo con chair_id
```

- La KB escribe `status NOT IN ('cancelled','no_show')`, pero RN-AG-01 define
  vigente como `pending/confirmed/present` y US-013 CA-2 dice que marcar ausente
  libera el recurso: se usa la lista positiva, que deja `absent` fuera.
- La tabla es nueva: los constraints se crean junto a ella, sin lock sobre datos
  existentes (no hace falta excepción a la regla 11).
- El servicio captura la `ExclusionViolation` (SQLSTATE `23P01`), identifica el
  constraint por nombre y responde `409 slot_taken`. No hay pre-chequeo que
  compita con la base: la consulta de conflictos solo arma el cuerpo del 409.

### D3. Sobreturnos: fuera del EXCLUDE, controlados por el servicio bajo lock

La KB deja abierto "predicado parcial o tabla hija". Se elige el predicado
parcial (`AND NOT is_overbooking`): una tabla hija duplicaría el modelo y todas
las consultas de agenda.

Consecuencia: la base no impide que un turno normal caiga sobre un sobreturno
vigente (por ejemplo, si se cancela el turno con el que colisionaba). Eso lo
impide el servicio, que dentro del lock de D4 considera también los sobreturnos
vigentes como ocupación al validar un turno normal. Reglas del servicio:
`is_overbooking=true` exige motivo (≤ 500), rol admin o recepción y colisión
real con un turno vigente (si no colisiona: `422 overbooking_not_needed`). El
tope diario (RN-SB-03) cuenta sobreturnos vigentes del profesional en el día
local de la clínica. Refuerzos en la base: `CHECK (NOT is_overbooking OR
overbooking_reason IS NOT NULL)` y `CHECK (origin <> 'online' OR NOT
is_overbooking)`.

Alternativa descartada: promover el sobreturno a turno normal al cancelar el
original. Con dos sobreturnos sobre el mismo hueco no hay elección
determinística, y RN-GL-02 prohíbe que una automatización reacomode la agenda.

### D4. Serialización por recurso con `SELECT … FOR UPDATE`

Lo que el EXCLUDE no cubre (bloqueos vs. turnos, sobreturnos, tope diario) se
serializa tomando lock de fila sobre `professional` y `chair` involucrados,
siempre ordenados por `(tabla, id)` para evitar deadlocks:

- Alta y reprogramación de turno: el profesional y el sillón (en una
  reprogramación, los de origen y destino).
- Alta y edición de bloqueo: su profesional y/o sillón; el cierre de clínica,
  todos los sillones activos.

Con el lock tomado, el servicio valida en este orden: recursos activos → regla
semanal → bloqueos → colisiones (incluye sobreturnos) → tope → `INSERT/UPDATE`
→ evento. El EXCLUDE sigue siendo la última barrera ante cualquier camino que
no tome el lock. **Contrato para C-07**: el booking público usa el mismo
servicio y, por lo tanto, el mismo lock.

### D5. Validación de horario en la zona de la clínica (RN-GL-03)

`starts_at/ends_at` llegan como `datetime` con zona; si no traen zona se
responde 422 (nunca se asume UTC). Con `ZoneInfo(clinic.timezone)` se calculan
el día de semana y las horas locales; el turno debe caer completo en una
`schedule_rule` activa del par (profesional, sillón) con `valid_from <= fecha
<= valid_to`. El buffer puede exceder el fin de la franja (limpieza fuera de
horario). Duración: `duration_min` opcional (5..480); por defecto, el
`slot_duration_min` de la regla que contiene el inicio. No se permiten turnos
en un día local anterior a hoy (`422 appointment_in_past`); hoy sí, para
registrar a un paciente que ya llegó.

### D6. Máquina de estados declarativa

Una tabla `ALLOWED: dict[(from, to), Guard]` en `appointments/states.py` es la
única fuente de verdad; el endpoint `POST /api/appointments/{id}/transitions`
recibe `{to, reason?, note?}`. Guardas:

| Transición | Roles | Guarda temporal |
|---|---|---|
| `pending→confirmed` | admin, recepción | turno no empezado |
| `confirmed→present` | admin, recepción, odontólogo (propio) | día local ≥ día del turno |
| `confirmed→absent/no_show` | admin, recepción, odontólogo (propio) | `now >= starts_at` |
| `pending/confirmed→cancelled` | admin, recepción | `now < starts_at`; motivo obligatorio |

Un turno `pending` al que el paciente llega se confirma y luego se marca
presente (dos eventos). `cancelled_at` y `cancellation_reason` solo se escriben
al cancelar (`CHECK` de coherencia con `status`). `late` se calcula al cancelar
(`starts_at - now < cancellation_window_hours`) y queda en el payload del
evento, sin columna nueva: lo leen los reportes de C-13 desde los eventos.

Catálogo `cancellation_reason` (enum PG): `paciente, profesional, clinica,
bloqueo, otro`, más `cancellation_note` opcional (≤ 500). El paciente online
(C-08) usará el mismo catálogo.

Se usa un endpoint de transiciones en vez de un `PATCH status` porque las
transiciones llevan datos propios (motivo, nota) y guardas distintas de la
edición de horario. `PATCH /api/appointments/{id}` queda para reprogramar
(`starts_at`, `duration_min`, `professional_id`, `chair_id`, `is_overbooking`,
`overbooking_reason`) y editar `notes`.

### D7. `appointment_event` append-only

Columnas: `id, clinic_id, appointment_id, actor_type (user|patient_token|system),
actor_user_id NULL, event (created, overbooking_created, confirmed, rescheduled,
cancelled, present, absent, no_show, updated), from_status NULL, to_status NULL,
payload jsonb, created_at DEFAULT clock_timestamp()`. FK compuesta `(clinic_id,
appointment_id)` (regla 4), `CHECK (actor_type <> 'user' OR actor_user_id IS
NOT NULL)`, índice `(appointment_id, created_at)`.

Trigger `BEFORE UPDATE OR DELETE` que levanta excepción, igual que `auth_event`
y `agenda_config_event`. El servicio inserta el evento con flush en la misma
transacción que la mutación: si falla, falla todo (RN-GL-01). El `payload` lleva
antes/después de los campos cambiados, ids de colisión y motivo, y nunca nombre,
teléfono ni email del paciente (regla 13).

**Rol `app_writer`** (pedido por CHANGES): sin efecto mientras la app use el
owner. Se difiere a C-14 (separar `MIGRATION_DATABASE_URL` del usuario de la
app, con `GRANT SELECT, INSERT` sobre los eventos); queda registrado en CHANGES.

### D8. Alternativos (regla dura 1)

Función pura `suggest_slots(rules, blocks, busy, desde, n=3, horizonte=14d)` en
`agenda/availability.py`: genera la grilla `start_time + k·slot_duration_min` de
cada regla vigente del par en zona local, descarta lo pasado, lo bloqueado y lo
que intersecta rangos ocupados (incluye sobreturnos y buffers) y devuelve los
primeros `n` desde el horario pedido. La consulta trae solo columnas necesarias
del rango (sin `SELECT *`, regla 8). C-07 la reutiliza para la disponibilidad
pública.

### D9. Cuerpo de errores

`409 slot_taken {conflicts: [ids], alternatives: [{starts_at, ends_at,
professional_id, chair_id}]}`, `409 slot_blocked {blocks: [ids]}`, `409
block_conflicts {appointments: [ids]}`. Solo ids y horarios: nada que
identifique a otros pacientes. `DomainError.extra` ya soporta estas claves.

### D10. Bloqueos sobre turnos (RN-BL-02)

`BlockCreate`/`BlockUpdate` suman `cancel_appointments: list[{appointment_id,
reason, note?}]` (default vacío). Con lock (D4), el servicio busca turnos
`pending/confirmed` del objetivo que intersectan el rango (un bloqueo solo de
profesional afecta sus turnos en cualquier sillón, y viceversa). El conjunto
indicado debe cubrir exactamente a los afectados; si falta alguno, `409
block_conflicts` con los faltantes. Si sobra alguno (no afectado), `422`.
Cancelar exige rol admin o recepción (`403` al odontólogo). Cada cancelación
pasa por la misma máquina de estados (D6) y escribe su evento; el bloqueo y su
`agenda_config_event`, en la misma transacción.

### D11. Pacientes

`app/modules/patients` (router + servicio), solo admin y recepción.

- `GET /api/patients?q=` (3..100 caracteres): si `q` se normaliza como teléfono
  válido, reutiliza `find_patients_by_phone` (C-02); si no, `similarity(full_name,
  q) > 0.3` ordenado por similitud desc. El operador `%` usa el índice GIN
  trigram existente. Máximo 20 resultados: es una búsqueda por relevancia, no un
  listado paginable.
- `POST /api/patients`: nombre, teléfono y/o email, DNI opcional,
  `whatsapp_opt_in`. Duplicado = mismo `phone_e164` y mismo
  `lower(btrim(full_name))` (sin quitar acentos: `unaccent` no está instalada)
  → `409 patient_duplicate {patient_id}`.
  Sin cambios de schema: el CHECK de contacto ya existe en la base.
- Los errores de teléfono reutilizan los mensajes genéricos de `clinic/service`
  (sin el valor recibido).

### D12. Vistas por rol

`AppointmentRead` incluye `patient: {id, full_name, phone_e164, email}` para
admin y recepción; para el odontólogo, `patient: {id, full_name}` (decisión de la
pregunta abierta Media sobre privacidad entre profesionales: vista mínima por
defecto). El listado exige `from` y `to` (≤ 31 días), filtra `starts_at < to AND
occupied_until > from`, ordena por `(starts_at, id)` con el cursor de
`app/common/pagination.py` y `limit` ≤ 500. La agenda lee el estado actual de
`appointment`; los reportes históricos (C-13) leen `appointment_event`
(regla 8).

## Risks / Trade-offs

- [Un camino nuevo que no tome el lock de D4 podría crear un turno normal sobre
  un sobreturno] → el servicio de turnos es el único punto de escritura;
  contrato escrito para C-07 y test que verifica la detección.
- [Lock de fila sobre `professional` serializa todas las reservas de un
  profesional] → contención baja (< 50 concurrentes por tenant, KB 08); el lock
  dura una transacción corta.
- [Snapshot del buffer] → cambiar `buffer_min` no reacomoda turnos existentes:
  es lo esperado (RN-GL-02), queda documentado.
- [`absent` vs. `no_show` difiere de la letra de la KB] → decisión del usuario
  (2026-11-03) registrada aquí y en la spec.
- [Inmutabilidad sin rol DB] → un superusuario puede deshabilitar el trigger;
  se cierra en C-14.

## Migration Plan

`c05_appointments_core` (revises `c04_agenda_config`): enums → `appointment`
(CHECKs, FKs compuestas, 2 EXCLUDE, índices `(clinic_id, starts_at)`,
`(professional_id, starts_at)`, `(patient_id, starts_at)`) → `appointment_event`
(+ función y trigger). Downgrade en orden inverso: pierde turnos y eventos (se
advierte en el README, como C-03/C-04); no elimina `btree_gist`. CI ya corre
`upgrade → downgrade -1 → upgrade`.
