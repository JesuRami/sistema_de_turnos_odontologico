# Proposal — C-13 `reportes-admin-export`

## Why

C-05 dejó una auditoría inmutable (`appointment_event`) pero nadie la puede
leer en conjunto: hoy el administrador solo ve el historial de un turno a la vez
y no puede responder "¿cuánto se ocupa cada sillón?", "¿cuánto es ausentismo
real y cuánto cancelación tardía?" ni llevarse sus datos. C-13 convierte la
auditoría en decisiones (US-050) y en control sin lock-in (US-051), siempre
calculando sobre eventos y nunca sobre estados mutados (US-050 CA-3, regla 8).

Dependencias verificadas: C-03 (RBAC) y C-05 (turnos y eventos) están
archivadas; C-04 (recursos y plantilla horaria) también, y se usa para la
capacidad de la ocupación.

## What Changes

- **Instantánea de turno en cada evento.** `record_event` (único punto de
  escritura de `appointment_event`) pasa a sellar en cada evento nuevo el
  horario y los recursos vigentes del turno: columnas `slot_starts_at`,
  `slot_ends_at`, `professional_id`, `chair_id` (nulables, solo ids y fechas,
  sin datos del paciente, regla 13). Así el último evento de un turno describe
  su estado final sin leer `appointment`.
- **Migración `c13_event_slot`** (una sola revisión, regla 3): agrega las
  columnas, FKs compuestas `NOT VALID` → `VALIDATE` y el índice
  `(clinic_id, slot_starts_at)` con `CONCURRENTLY` (regla 11). El trigger de
  inmutabilidad no se toca.
- **Tres reportes** con rango de fechas, solo admin, en JSON o CSV
  (`GET /api/reports/occupancy`, `/absenteeism`, `/cancellations`):
  - *Ocupación* por profesional o por sillón: minutos reservados sobre
    capacidad (plantilla activa menos bloqueos).
  - *Ausentismo*: `no_show`, `absent` y cancelación tardía por separado
    (RN-ST-04), con tasas.
  - *Cancelaciones por motivo* (RN-CX-04), con el corte tardía / en ventana.
- **Auditoría de la clínica**: `GET /api/audit/appointments` (solo admin) con
  filtros por turno, actor, tipo de evento y rango, paginada por cursor. El
  historial por turno de C-05 (`/appointments/{id}/events`) se mantiene.
- **Exportación completa** con un clic: `GET /api/exports/full?format=csv|json`
  devuelve un ZIP con turnos, pacientes operativos y eventos. Se lee por lotes
  y cada ejecución queda registrada en `auth_event` (`data_exported`).
- **Frontend** (`features/reports`, ruta `/admin/reportes`, solo admin): pestañas
  Ocupación, Ausentismo, Cancelaciones y Auditoría, selector de rango, botón
  "Descargar CSV" por reporte y "Exportar todos mis datos".

## Out of scope (explícito)

- **Reporte mensual de WhatsApp** (enviados/entregados/leídos y costo por paso,
  RN-WA-05): necesita `reminder_job` y `delivery_event`, que nacen en
  C-09/C-10. Queda para un change posterior a ellos.
- **Conversión lista de espera → turno**: necesita `waiting_list_entry` y el
  origen `waitlist` (C-12). Queda para después de C-12.
- Ambos puntos figuran hoy en el scope de C-13 en `CHANGES.md`; hay que
  actualizar esa ficha (tarea 7.1) para no perder el compromiso.
- Backfill de eventos anteriores a C-13: `appointment_event` es inmutable. Los
  eventos sin instantánea quedan fuera de los reportes (ver riesgos en
  `design.md`).
- Reportes para recepción u odontólogo (la matriz RBAC los deja para después),
  gráficos avanzados, programación de envíos y alta/baja de usuarios (C-03).
- Rol de base `app_writer` separado (diferido a C-14).
