# Design — C-13 `reportes-admin-export`

## Context

- `appointment_event` (C-05) es append-only (trigger), con `event`, `from_status`,
  `to_status`, `actor_*`, `payload` JSONB y `created_at`. El evento `cancelled`
  ya lleva `payload.reason` y `payload.late` (calculado con la ventana de la
  clínica, RN-CX-01); `created` lleva recursos y horario; `rescheduled` lleva
  `before/after` solo de los campos cambiados.
- El estado actual de un turno no se puede leer de `appointment` para reportes
  (US-050 CA-3). Hay que reconstruirlo desde eventos.
- Índices existentes: `(appointment_id, created_at)` y `(clinic_id, created_at)`.
  Ninguno sirve para filtrar por la fecha del turno.
- Los routers son finos y delegan en servicios; RBAC con `require_roles`;
  paginación por cursor en `app/common/pagination.py`; errores `DomainError`.

## Goals / Non-Goals

**Goals:** reportes exactos y reproducibles desde eventos; consultas indexadas;
export completo sin cargar todo en memoria; solo admin; sin PII en logs ni en
errores.
**Non-Goals:** WhatsApp y lista de espera (ver proposal), tiempo real, BI.

## Decisions

### D1. Estado final de un turno = su último evento

Un reporte toma, por turno, el último evento (`DISTINCT ON (appointment_id)
ORDER BY appointment_id, created_at DESC, id DESC`) y usa su `to_status`
(o `from_status` si el evento no cambia estado, como `rescheduled`/`updated`;
ambos coinciden en ese caso). Nunca se consulta `appointment.status`.
*Alternativa descartada:* leer `appointment` y cruzar con eventos — incumple
US-050 CA-3.

### D2. Instantánea del horario en cada evento (columnas, no solo JSON)

`record_event` recibe el `Appointment` ya mutado, así que puede sellar
`slot_starts_at`, `slot_ends_at`, `professional_id` y `chair_id` sin tocar a
los llamadores. Se eligen columnas (no `payload`) porque Postgres no permite
indexar el cast texto→`timestamptz` del JSON (no es `IMMUTABLE`) y el rango de
fechas del turno es el filtro de todos los reportes.
*Alternativas descartadas:* (a) reconstruir el horario mezclando `created` +
`rescheduled.after` en SQL: frágil y lento; (b) índice por `created_at`: filtra
por cuándo ocurrió el evento, no por el día del turno.

### D3. Qué significa el rango de fechas

Todos los reportes filtran por **fecha del turno** (`slot_starts_at` del último
evento) en la zona de la clínica (RN-GL-03), `[desde, hasta]` inclusive por día
local, máximo 366 días (`422 range_too_large`). Para la auditoría, en cambio,
el rango es el momento del evento (`created_at`).

### D4. Definiciones de métricas (a confirmar con el PO)

- *Minutos reservados*: duración (`slot_ends_at − slot_starts_at`) de los turnos
  cuyo estado final es `pending`, `confirmed` o `present`. Sobreturnos cuentan
  aparte (`overbooking_count`) y no suman minutos para no superar el 100 %.
- *Capacidad*: minutos de `schedule_rule` activas del recurso dentro del rango,
  en hora local, menos solapes con `block`. Se calcula en Python con las reglas
  **actuales** (son pocas filas); no reconstruye cambios de horario pasados.
  *Limitación declarada* en la respuesta (`capacity_basis: "current_schedule"`).
- *Sobreturno*: turno cuyo alta fue `overbooking_created`. Si un turno normal se
  reprograma después como sobreturno, cuenta como normal (limitación conocida).
- *Ocupación* = reservados / capacidad (0 si capacidad 0).
- *Ausentismo*: `outcomes = present + absent + no_show + late_cancellations`;
  `no_show_rate = no_show / outcomes`, ídem `absent_rate` y
  `late_cancellation_rate`. `no_show` (no vino y no avisó) y `absent` (avisó
  tarde) no se mezclan con cancelación (RN-ST-04). Las cancelaciones en
  ventana no entran en el denominador.
- *Cancelaciones por motivo*: conteo por `payload.reason` (catálogo RN-CX-04),
  con `late` / `in_window`.

### D5. Consultas

Primero se buscan los turnos con *algún* evento dentro del rango (usa el índice),
luego se toma el último evento de cada uno y se vuelve a filtrar por su horario
final (un turno reprogramado fuera del rango no debe contarse). Una pasada
agregada por reporte (`GROUP BY`), con `clinic_id` primero en
el `WHERE`, columnas listadas (nada de `SELECT *`, regla 8) y el índice
`(clinic_id, slot_starts_at)` (D2). Se verifica con `EXPLAIN` en un test de
rendimiento con volumen sintético (patrón de `test_appointments_week_perf`). El `cancelled` más reciente de cada
turno aporta `reason` y `late`, porque un `updated` posterior (p. ej. fusión de
pacientes) no debe taparlos.

### D6. Auditoría de la clínica

`GET /api/audit/appointments` pagina con `paginate_entities` por
`(created_at, id)` con límite 1–200. Filtros: `appointment_id`, `actor_user_id`,
`event`, `from`, `to`. Devuelve los mismos campos que `AppointmentEventRead`
más `appointment_id`; el payload ya está libre de PII (C-05). Solo admin.

### D7. Exportación completa

`GET /api/exports/full?format=csv|json` responde un ZIP (`StreamingResponse`)
con `appointments`, `patients` y `appointment_events`. Cada tabla se lee por
lotes con cursor (batch fijo) y se escribe al flujo sin cargarla entera.
Pacientes: solo campos operativos (`id`, nombre, teléfono, email, DNI,
`whatsapp_opt_in`, consentimiento, archivado); nada de notas clínicas (no
existen en v1). Las celdas CSV que empiezan con `=`, `+`, `-` o `@` se
prefijan con `'` (inyección de fórmulas). Todo filtrado por `clinic_id`.

### D8. Traza de la exportación

Exportar datos personales es una acción sensible: se registra en `auth_event`
con un valor nuevo `data_exported` (con `format` y conteos en el payload, sin
datos de pacientes). Requiere `ALTER TYPE … ADD VALUE` en la migración, fuera
de transacción (bloque autocommit de Alembic). Si el PO prefiere no tocar el
enum, la alternativa es un log estructurado sin PII; se decide en la
aprobación.

### D9. RBAC y errores

Todos los endpoints nuevos usan `require_roles(UserRole.ADMIN)`; recepción y
odontólogo reciben `403 forbidden_role`; otra clínica nunca ve datos (el filtro
`clinic_id` sale del `Principal`, no de la request). Schemas de entrada con
`extra='forbid'` (regla 2). Errores: `422 invalid_range`, `422
range_too_large`, `422 invalid_format`.

### D10. Frontend

`features/reports`: una página con pestañas y un hook de datos por reporte; el
rango por defecto es el mes en curso en hora de la clínica (`GET /api/clinic`
da la zona). El CSV se descarga con la sesión del usuario (sin tokens en la
URL). Tipos explícitos en los bordes, sin `any` (regla 5). La ruta se protege
con el guard de rol admin existente en `shared/auth/guards.tsx`.

## Risks / Trade-offs

- **Eventos previos a C-13 sin instantánea** quedan fuera de los reportes. No
  hay datos de producción todavía (piloto en C-14); los datos de desarrollo se
  regeneran con el seed. Si fuera necesario, un reporte "turnos sin
  instantánea" lo hace visible en vez de ocultarlo.
- **Capacidad con la plantilla actual** distorsiona rangos históricos si el
  horario cambió; está declarado en la respuesta y en la UI.
- **`ALTER TYPE ADD VALUE`** no es reversible en `downgrade`; se documenta en
  el encabezado de la migración.
- **Export grande**: lectura por lotes y flujo; el límite práctico lo da el
  timeout del proxy, no la memoria. Se mide en el test de volumen.

## Migration Plan

1. `c13_event_slot`: columnas nulables → FKs `NOT VALID` → `VALIDATE` →
   `CREATE INDEX CONCURRENTLY` → valor de enum.
2. Desplegar backend (sellado de instantáneas) antes del frontend.
3. Rollback: `downgrade` quita índice, FKs y columnas; el valor de enum queda.

## Open Questions

1. ¿Confirmás las definiciones de D4 (sobre todo el denominador del
   ausentismo)? La métrica de éxito "ausentismo −20 %" de `01_vision` depende
   de ella.
2. ¿Aceptás `data_exported` en `auth_event` (D8)?
