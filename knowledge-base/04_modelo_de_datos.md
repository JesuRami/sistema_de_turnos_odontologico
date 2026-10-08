# Modelo de Datos

## Dominios

El MVP tiene un solo dominio funcional (agenda) más dos dominios de soporte:

1. **Agenda** (core): clínicas, profesionales, sillones, horarios, bloqueos, turnos, lista de espera.
2. **Identidad y acceso** (soporte): usuarios del personal, roles, tokens de paciente, auditoría.
3. **Notificaciones** (soporte): jobs de recordatorio, plantillas, eventos de entrega, opt-outs.

No hay dominios clínico, financiero ni fiscal en v1.0. Las tablas llevan `clinic_id` como partición lógica preparando multi-tenant futuro, aunque físicamente haya una DB por clínica.

## ERD (Entity Relationship Diagram)

```
clinic 1───* professional 1───* schedule_rule
clinic 1───* chair
clinic 1───* user (*───1 professional, nullable: recepción/admin sin profesional)
clinic 1───* patient (registro liviano: nombre + teléfono + email, sin HC)

professional *───* chair  (vía availability: qué profesional atiende en qué sillón y cuándo)
schedule_rule ──► (weekly template por professional+chair)

appointment *───1 professional, *───1 chair, *───1 patient, *───1 clinic
appointment 1───* appointment_event (auditoría inmutable)
appointment 1───* reminder_job (1 por step programado)

block *───1 clinic, nullable professional_id, nullable chair_id (bloqueo global o parcial)
waiting_list_entry *───1 clinic, nullable professional_id, *───1 patient
waiting_list_entry 1───* waitlist_offer (hueco ofrecido con expiración)

notification_template 1───* reminder_job
delivery_event *───1 reminder_job
consent/opt_out *───1 patient (canal whatsapp/email)
```

## Entidades

### clinic
- Atributos: `id (uuid)`, `name`, `slug (unique, para /b/:slug)`, `timezone (default America/Argentina/Buenos_Aires)`, `booking_enabled (bool)`, `cancellation_window_hours (int, default 24)`, `reminder_steps (jsonb: [{offset_h, channel}])`, `created_at`.
- Relaciones: 1─* con todo lo operativo.
- Constraints: `slug` único global (es URL pública).
- Índices: `slug`.

### professional
- Atributos: `id`, `clinic_id`, `display_name`, `color (agenda UI)`, `default_duration_min`, `buffer_min (default 0)`, `booking_enabled (bool)`, `active (bool)`.
- Relaciones: *─1 clinic; 1─* schedule_rule, appointment, block (parciales).
- Constraints: `active=false` impide nuevas reservas pero conserva historial.
- Índices: `(clinic_id, active)`.

### chair (sillón/box)
- Atributos: `id`, `clinic_id`, `name` ("Sillón 1"), `active (bool)`.
- Relaciones: *─1 clinic; aparece en appointments y blocks.
- **Suposición:** el sillón es recurso reservable independiente del profesional. En consultorios de 1 sillón habrá exactamente 1 fila; el modelo no colapsa profesional=sillón para no impedir el crecimiento a multi-sillón sin migración.

### schedule_rule (plantilla semanal de disponibilidad)
- Atributos: `id`, `clinic_id`, `professional_id`, `chair_id`, `weekday (0-6)`, `start_time`, `end_time`, `slot_duration_min`, `valid_from`, `valid_to (nullable)`, `active`.
- Relaciones: define la grilla sobre la que se calculan huecos.
- Constraints: `start_time < end_time`; no se permiten reglas solapadas para el mismo (professional, chair, weekday) con vigencias intersectadas (validación en servicio FastAPI + constraint).
- Nota SQLAlchemy: `Time`/`Date` nativos, `valid_from/valid_to` como `DateTime(timezone=True)`; unicidad parcial y `CheckConstraint("start_time < end_time")` en el modelo; migraciones con Alembic.
- Índices: `(professional_id, chair_id, weekday)`.

### patient (registro liviano, NO historia clínica)
- Atributos: `id`, `clinic_id`, `full_name`, `phone_e164 (nullable)`, `email (nullable)`, `dni (nullable, no único: **Suposición** — el DNI no es identificador confiable en esta fase; duplicados se resuelven por teléfono), `whatsapp_opt_in (bool, default false)`, `created_at`.
- Relaciones: 1─* appointment, waiting_list_entry.
- Constraints: al menos uno de (phone, email) no nulo (si no, no hay cómo recordarle nada y el turno nace ciego).
- Índices: `(clinic_id, phone_e164)`, `(clinic_id, full_name)` trigram para búsqueda de recepción.

### appointment (turno — tabla crítica)
- Atributos: `id`, `clinic_id`, `professional_id`, `chair_id`, `patient_id`, `starts_at (timestamptz)`, `ends_at (timestamptz)`, `duration_range (tstzrange, generado)`, `status (enum: pending, confirmed, present, absent, cancelled, no_show)`, `origin (enum: reception, online, waitlist)`, `is_overbooking (bool default false)`, `cancelled_at`, `cancellation_reason`, `manage_token_hash (unique, nullable hasta confirmar)`, `notes_operativas (texto libre, NO clínicas)`, `created_by_user_id`, `created_at`, `updated_at`.
- Relaciones: *─1 professional/chair/patient/clinic; 1─* appointment_event, reminder_job.
- Nota SQLAlchemy: todos los timestamps como `DateTime(timezone=True)`; `status`/`origin` como `Enum` nativo de Postgres; `duration_range` como columna `TSRANGE` generada; `AsyncSession` en FastAPI; migraciones y seed con Alembic.
- Constraints:
  - `ends_at > starts_at`.
  - **Exclusión anti-solapamiento** (la invariante del sistema):
    `EXCLUDE USING gist (professional_id WITH =, duration_range WITH &&) WHERE (status NOT IN ('cancelled','no_show'))`
    y análogo por `chair_id`. Los turnos cancelados/ausentes liberan el hueco y no participan en la exclusión.
  - Nota SQLAlchemy: el `EXCLUDE` no tiene constructo ORM nativo; se declara vía `DDL` en la migración Alembic (`ALTER TABLE ... ADD CONSTRAINT ... EXCLUDE USING gist ...`) y se refleja en el modelo con `__table_args__`. Alternativa documentada: `CheckConstraint` para `ends_at > starts_at` + DDL para exclusión.
  - Sobreturno: solo permitido con `is_overbooking=true` explícito + rol autorizado; el constraint de exclusión se aplica igual salvo flag (implementado como predicado parcial o tabla hija — a definir en diseño detallado, pero la regla es: el sobreturno nunca es silencioso).
  - `manage_token_hash` único; el token en claro solo viaja por URL/WhatsApp una vez.
- Índices: `(clinic_id, starts_at)`, `(professional_id, starts_at)`, `(patient_id, starts_at)`, GIST en `duration_range`.

### block (bloqueo de agenda)
- Atributos: `id`, `clinic_id`, `professional_id (nullable)`, `chair_id (nullable)`, `starts_at`, `ends_at`, `reason (enum: vacaciones, feriado, mantenimiento, reunión, otro)`, `notes`, `created_by_user_id`.
- Relaciones: bloquea la grilla; la disponibilidad lo resta antes de ofrecer huecos.
- Constraints: `ends_at > starts_at`; al menos uno de (professional_id, chair_id) no nulo (un bloqueo totalmente global se modela como cierre de clínica por rango, no como block huérfano).
- Regla dura: no se puede crear un bloqueo que pise turnos vigentes (pending/confirmed) salvo con reprogramación explícita previa de los afectados (ver RN-BL-02).

### waiting_list_entry + waitlist_offer
- Entry: `id`, `clinic_id`, `patient_id`, `professional_id (nullable = cualquiera)`, `preferred_from`, `preferred_to`, `notes`, `status (waiting, offered, converted, expired, withdrawn)`, `created_at`.
- Offer: `id`, `entry_id`, `appointment_slot (starts_at/ends_at propuestos)`, `expires_at`, `status (pending, accepted, declined, expired)`.
- Constraints: una entry `waiting/offered` por (patient, professional_nullable) — evita duplicados de la misma persona en la misma cola.

### user / role
- `user`: `id`, `clinic_id`, `email (unique por clínica)`, `password_hash (argon2)`, `role (enum: admin, recepcion, odontologo)`, `professional_id (nullable, obligatorio si role=odontologo)`, `active`, `last_login_at`.
- Sin tabla de permisos fina en v1.0: el enum de rol es la matriz (ver archivo 03). Escalar a permisos granulares es fase posterior.

### appointment_event (auditoría inmutable)
- `id`, `appointment_id`, `actor_type (user, patient_token, system)`, `actor_id`, `event (created, confirmed, rescheduled, cancelled, no_show, overbooking_created, ...)`, `from_state`, `to_state`, `payload (jsonb)`, `created_at`.
- Sin UPDATE ni DELETE (revocado a nivel de rol DB). Es la base de los reportes y de cualquier disputa ("¿quién movió mi turno?").
- Nota SQLAlchemy: modelo solo-`insert` en la capa de servicios FastAPI (sin métodos update/delete); `payload` como `JSONB`; `created_at` `DateTime(timezone=True, server_default=func.now())`; enforcement en DB con `REVOKE UPDATE, DELETE ON appointment_event FROM app_writer` en migración Alembic.

### reminder_job + delivery_event + notification_template
- `reminder_job`: `id`, `appointment_id`, `step (t_72h, t_24h, t_3h u offsets configurados)`, `channel (whatsapp, email)`, `scheduled_for`, `status (scheduled, sent, delivered, read, failed, skipped, cancelled)`, `template_id`, `idempotency_key (unique: appointment_id+step+channel)`, `attempts`, `last_error`.
- `delivery_event`: `id`, `reminder_job_id`, `provider_event_id`, `event_type`, `payload`, `received_at` (webhooks de Meta).
- `notification_template`: `id`, `clinic_id`, `channel`, `step`, `meta_template_name`, `locale (es_AR)`, `body_preview`, `active`.
- Ver diseño del motor en `11_whatsapp_y_recordatorios.md`.

### consent (opt-in/opt-out por canal)
- `patient_id`, `channel`, `status (opt_in, opt_out)`, `changed_at`, `source (booking, whatsapp_reply, reception)`.
- Regla: sin `opt_in` de WhatsApp no se envía nada por ese canal (ver RN-WA-01). El email es respaldo con opt-out simple.

## Seed data inicial (vía Alembic + script async)

Por clínica nueva (tenant), ejecutado con `AsyncSession` en migración de datos o script `seed.py` idempotente:

- 1 `clinic` con `slug` provisorio, timezone `America/Argentina/Buenos_Aires`, `cancellation_window_hours=24`, `reminder_steps=[{72h whatsapp},{24h whatsapp},{3h whatsapp}]`.
- 1 `user` admin inicial (credenciales provisorias con cambio obligatorio).
- 1 `chair` ("Sillón 1") y 1 `professional` de ejemplo inactivo (para que el admin edite, no para usar directo).
- 3 `notification_template` (paso 72h/24h/3h) con nombres de plantilla Meta placeholder hasta aprobación.
- Catálogo de `reason` de bloqueos y estados iniciales. Sin pacientes de ejemplo (datos personales sintéticos prohibidos en seed).
