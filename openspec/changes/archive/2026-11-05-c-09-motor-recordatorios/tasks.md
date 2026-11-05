# Tasks — C-09 `motor-recordatorios`

> TDD estricto rojo → verde: cada tarea **RED** escribe el test, lo corre y deja
> registrado que falla por la razón esperada; la **GREEN** siguiente escribe el
> mínimo código para pasarlo. Tests de invariantes y API con pytest + httpx contra
> Postgres 15 + Redis 7 reales (regla 9, sin mocks de DB). El `.venv` local no
> importa `asyncpg` (py3.14): el gate se corre en el contenedor py3.12 como CI.
> Datos solo sintéticos: nombres inventados, teléfonos `+54 11 5555-01xx`, emails
> `@example.com` (regla 13); ni teléfonos, emails ni links en logs, `last_error`
> ni `payload`. Antes de tocar archivos existentes, correr su suite como red de
> seguridad. Cada grupo deja sus tests y su documentación.

## 0. Red de seguridad

- [x] 0.1 Correr `pytest -q` en `backend/` (contenedor py3.12) y anotar el baseline
  (N passed / N failed, con las fallas de entorno preexistentes). Verifica: tabla de
  baseline al final de este archivo; nada se arregla acá.
- [x] 0.2 Confirmar contra `arq>=0.26,<0.27` la API que usa D12 (`cron`,
  `create_worker(...).async_run()`, `max_jobs`, `on_startup`) con un script
  descartable. Verifica: nota en el archivo con la firma real; si difiere, ajustar
  `design.md` D12 antes de seguir.

## 1. Configuración (D13)

- [x] 1.1 RED — `backend/tests/core/test_settings_reminders.py`: los diez settings
  nuevos tienen default; `MANAGE_LINK_SECRET` de menos de 32 bytes, o ausente con
  `ENV` distinto de `dev`, falla con `SettingsError` que no imprime el valor (en `dev`
  vacío se admite y deshabilita los links firmados);
  `REMINDER_*_PROVIDER` fuera de `disabled|fake` (`smtp` solo en email) falla;
  `REMINDER_BACKOFF_MINUTES` no numérico o vacío falla; `REMINDER_MAX_ATTEMPTS=0`
  falla; el `.env.example` contiene todas las claves. Verifica: `cd backend; pytest
  tests/core/test_settings_reminders.py -q` → falla (settings inexistentes).
- [x] 1.2 GREEN — Settings + `.env.example` con valores de ejemplo sin secretos
  (regla 6). Verifica: el test de 1.1 verde y `tests/test_env_example.py` verde.

## 2. Migración `c09_reminder_engine` y modelos (D1)

- [x] 2.1 RED — `backend/tests/models/test_reminder_tables_db.py` (Postgres real):
  la unicidad `(appointment_id, step, channel)` rechaza el duplicado; `step` con
  formato inválido, `locale <> 'es_AR'` y `attempts < 0` fallan por CHECK; una FK
  compuesta rechaza un job de la clínica B sobre un turno, plantilla o
  paciente de la A (una prueba por tabla); `UPDATE`/`DELETE` sobre `delivery_event`
  y `consent` los rechaza el trigger; `(reminder_job_id, provider_event_id)` no
  admite repetidos pero sí varios `NULL`; el drift modelo↔migración no detecta
  diferencias. Verifica: `cd backend; pytest tests/models/test_reminder_tables_db.py
  -q` → falla (tablas inexistentes).
- [x] 2.2 GREEN — Modelos `NotificationTemplate`, `ReminderJob`, `DeliveryEvent`,
  `Consent` y enums en `app/models/` (exportados en `__init__`), y revisión
  `c09_reminder_engine` (`down_revision = c08_manage_token`): enums nativos,
  tablas con FKs compuestas e índices en el `CREATE TABLE` (D1, regla 11),
  triggers append-only, `downgrade` inverso. Verifica: el test de 2.1 verde y
  `cd backend; alembic upgrade head; alembic downgrade -1; alembic upgrade head`
  limpio.
- [x] 2.3 RED — `backend/tests/test_migrations.py` (ampliar): sobre una base en
  `c08_manage_token` con dos clínicas, un paciente con `whatsapp_opt_in=true` y otro
  con `false`, `upgrade head` crea exactamente una fila `consent`
  `whatsapp/opt_in/legacy` para el primero, deja los flags intactos y crea las ocho
  plantillas por clínica; re-ejecutar el backfill no duplica. Verifica: `cd backend;
  pytest tests/test_migrations.py -q -k c09` → falla.
- [x] 2.4 GREEN — Pasos de datos idempotentes en la revisión (`INSERT … ON CONFLICT
  DO NOTHING`). Verifica: 2.3 verde.

## 3. Consentimiento (D8)

- [x] 3.1 RED — `backend/tests/modules/test_consent_service.py`: `record(opt_in)`
  agrega una fila con fuente y usuario y pone `whatsapp_opt_in=true`; repetirlo no
  agrega fila; `record(opt_out)` pone el flag en `false` y marca `skipped`
  (`no_consent`) los jobs `scheduled` de ese paciente y canal, sin tocar los de
  otro paciente ni de otra clínica ni los ya `sent`; si la transacción revierte no
  cambia nada; test de paridad: el último `consent` de WhatsApp de todo paciente
  coincide con el flag. Verifica: `cd backend; pytest
  tests/modules/test_consent_service.py -q` → falla.
- [x] 3.2 GREEN — `app/modules/reminders/consent.py` con `ConsentService.record`.
  Verifica: 3.1 verde.
- [x] 3.3 RED — `backend/tests/modules/test_consent_writers.py`: alta de paciente
  por recepción con `whatsapp_opt_in=true` crea `opt_in/reception` con el usuario;
  sin la bandera no crea filas; reserva pública nueva con opt-in crea `opt_in/booking`;
  match de paciente sin opt-in que acepta crea una fila y con opt-in previo no crea
  ninguna; la fusión de pacientes no crea ni hereda consentimiento. Verifica: `cd
  backend; pytest tests/modules/test_consent_writers.py -q` → falla.
- [x] 3.4 GREEN — `patients/service.py`, `clinic/service.py:create_patient` y
  `booking_public/service.py:_match_or_create` delegan en `ConsentService`; ningún
  otro módulo asigna `whatsapp_opt_in`. Verifica: 3.3 verde, y las suites
  `test_patients_*`, `test_booking_public_patient_match.py` y `test_patient_merge*`
  siguen verdes. Un `grep` de `whatsapp_opt_in =` en `app/` no encuentra otra
  asignación.

## 4. Plantillas y seed (D11)

- [x] 4.1 RED — `backend/tests/test_seed_templates.py`: el seed sobre base vacía crea
  ocho plantillas activas `es_AR` (cuatro por canal, una por paso) con nombres
  Meta placeholder y solo variables `{{…}}` permitidas; re-ejecutar no duplica ni
  pisa un `body_preview` editado; ninguna contiene `{{direccion}}` ni datos
  reales. Verifica: `cd backend; pytest tests/test_seed_templates.py -q` → falla.
- [x] 4.2 GREEN — `app/modules/reminders/templates.py` con el catálogo por defecto,
  reutilizado por el seed y por el backfill de 2.4 (una sola fuente de textos);
  `app/seed.py` lo invoca. Verifica: 4.1 verde y `test_seed*.py` siguen verdes.
- [x] 4.3 Documentar las variables y el flujo de alta de plantillas en
  `backend/README.md`. Verifica: el comando de seed documentado corre tal cual.

## 5. Link de gestión firmado (D9)

- [x] 5.1 RED — `backend/tests/modules/test_manage_signed_link.py`: el token
  firmado de un turno online y el de uno de recepción resuelven `200` con la vista;
  un carácter alterado, firma de otro turno, id inexistente, prefijo roto y
  longitud errónea responden el **mismo** 404 `manage_link_not_found`; un token
  aleatorio emitido por C-07 sigue resolviendo; el TTL `ends_at + 72 h` aplica
  igual (410 vencido, 200 sin acciones tras el turno); `confirm`, `cancel` y
  `reschedule` funcionan con el firmado; cabeceras `no-store`; el token no aparece
  en logs ni en 422; rate-limit por `sha256(token)`. Verifica: `cd backend; pytest
  tests/modules/test_manage_signed_link.py -q` → falla.
- [x] 5.2 GREEN — `app/modules/reminders/links.py` (`sign_manage_token`,
  `verify_manage_token`, `build_manage_url`, comparación con `hmac.compare_digest`)
  y `ManageService.resolve` aceptando `TOKEN_RE` o `SIGNED_RE`; el router decide la
  clave de rate-limit con el mismo `sha256`. Verifica: 5.1 verde y toda la suite
  `tests/modules/test_manage_*` y `test_booking_public_*` sigue verde.
- [x] 5.3 Documentar el formato del token firmado y la rotación de
  `MANAGE_LINK_SECRET` en `backend/README.md` (el spec principal lo sincroniza el
  archive). Verifica: la sección existe y sus comandos o ejemplos corren tal cual.

## 6. Programación estado-basada (D2, D3)

- [x] 6.1 RED — `backend/tests/modules/test_reminder_reconcile.py` (función directa,
  reloj fijo): turno a 5 días ⇒ 72/24/3 h; a 30 h ⇒ 24/3 h; a 2 h ⇒ ninguno;
  `reconcile` dos veces no cambia nada; mover el turno +7 días recalcula los
  `scheduled`; moverlo a 10 h cancela el de 72 h y deja el de 3 h; un job `sent` no
  se toca ni se recrea; turno `cancelled` ⇒ todos `cancelled`; online `confirmed` ⇒
  `created/72/24` cancelados y 3 h `scheduled`; recepción `confirmed` ⇒ los cuatro;
  cambiar `reminder_steps` de la clínica cancela los pasos eliminados; un job
  `sending` no se toca. Verifica: `cd backend; pytest
  tests/modules/test_reminder_reconcile.py -q` → falla.
- [x] 6.2 GREEN — `app/modules/reminders/scheduling.py` con `reconcile` y
  `schedule_created` (columnas explícitas, `INSERT … ON CONFLICT DO NOTHING`,
  `UPDATE` acotado por `clinic_id`). Verifica: 6.1 verde.
- [x] 6.3 RED — `backend/tests/modules/test_reminder_hooks_api.py` (API real): crear
  turno por recepción y por reserva pública crea los cuatro jobs; `409 slot_taken`
  no deja jobs; reprogramar por recepción y por token recalcula; cancelar por
  recepción, por bloqueo de agenda y por token cancela los pendientes; confirmar
  por token cancela 72/24; si `reconcile` lanza, la mutación revierte y el turno y
  sus jobs quedan como estaban. Verifica: `cd backend; pytest
  tests/modules/test_reminder_hooks_api.py -q` → falla.
- [x] 6.4 GREEN — Llamar `schedule_created`/`reconcile` desde
  `AppointmentsService.book`, `_reschedule` y `states.apply_transition`; reemplazar
  `get_reminder_invalidator` por `ReconcilingInvalidator`. Verifica: 6.3 verde,
  toda la suite de C-05/C-06/C-07/C-08 verde y el spy de C-08 sigue recibiendo
  una sola llamada por acción.
- [x] 6.5 RED/GREEN — `backend/tests/modules/test_reminder_tenancy.py`: reconciliar
  o cancelar jobs de la clínica A no cambia ninguno de la B; la lectura de jobs
  siempre filtra por `clinic_id`. Verifica: el test verde.
- [x] 6.6 Medir el costo en el camino caliente: `tests/modules/
  test_appointments_week_perf.py` sigue pasando y se anota la diferencia de
  consultas por mutación. Verifica: sin regresión del umbral existente.

## 7. Canales y proveedores (D10)

- [x] 7.1 RED — `backend/tests/modules/test_reminder_senders.py`: el render de la
  fecha da “jueves 9/10, 15:30” para 18:30 UTC en `America/Argentina/Buenos_Aires`
  con nombres de día en español sin depender del locale del SO; un body con
  variables faltantes falla en vez de enviar `{{x}}`; `OutboundMessage` no muestra
  destinatario ni cuerpo en `repr`/logs; el sender `fake` registra envíos y su log
  no tiene PII; `choose_message_kind(None, now)` ⇒ `template`, con un entrante de
  hace 2 h ⇒ `session`, de hace 25 h ⇒ `template`. Verifica: `cd backend; pytest
  tests/modules/test_reminder_senders.py -q` → falla.
- [x] 7.2 GREEN — `app/modules/reminders/senders/` (`base.py`, `fake.py`,
  `render.py`, `window.py`) y la selección por settings (`disabled` ⇒ canal fuera
  del reclamo). Verifica: 7.1 verde.
- [x] 7.3 RED — `backend/tests/modules/test_reminder_smtp_sender.py` contra un
  servidor `aiosmtpd` local (dev-only): llega un mensaje con asunto y cuerpo
  renderizados, remitente `EMAIL_FROM`; error de conexión ⇒ `SendError(retryable=
  True)`; destinatario rechazado ⇒ `retryable=False`; ninguna excepción lleva el
  destinatario. Verifica: `cd backend; pytest
  tests/modules/test_reminder_smtp_sender.py -q` → falla.
- [x] 7.4 GREEN — Adaptador SMTP con `smtplib` en `asyncio.to_thread`; `aiosmtpd`
  en el grupo `dev` de `pyproject.toml`. Verifica: 7.3 verde.

## 8. Despacho: tick, validación, reintentos (D4, D5, D7)

- [x] 8.1 RED — `backend/tests/modules/test_reminder_dispatch_claim.py`: dos
  `run_tick` simultáneos (`asyncio.gather`) sobre 10 jobs vencidos envían cada job
  una sola vez y no dejan `sending`; 250 vencidos se drenan por lotes de 100; un job
  futuro no se reclama; con el proveedor del canal `disabled` el job sigue
  `scheduled` y no hay evento; el lease vencido devuelve `sending` a `scheduled`
  con evento. Verifica: `cd backend; pytest
  tests/modules/test_reminder_dispatch_claim.py -q` → falla.
- [x] 8.2 GREEN — `app/modules/reminders/dispatch.py` con `run_tick(session_factory,
  senders, now)`: tx de reclamo con `FOR UPDATE SKIP LOCKED`, `sending` + `attempts`,
  semáforo de concurrencia, presupuesto de tiempo y reclamo de leases. Verifica: 8.1
  verde, 20 corridas seguidas.
- [x] 8.3 RED — `backend/tests/modules/test_reminder_dispatch_validation.py`: turno
  `cancelled` ⇒ job `cancelled` sin envío; turno iniciado ⇒ `skipped`
  (`appointment_started`) y nunca `sent`; sin opt-in ⇒ `skipped` (`no_consent`);
  email sin `opt_out` ⇒ envía, con `opt_out` ⇒ `skipped`; plantilla inactiva ⇒
  `failed` (`template_inactive`); `starts_at` distinto del snapshot ⇒ reconcilia y
  no envía con la hora vieja; turno cancelado entre el reclamo y el `send` ⇒ el
  re-chequeo evita el envío. Verifica: `cd backend; pytest
  tests/modules/test_reminder_dispatch_validation.py -q` → falla.
- [x] 8.4 GREEN — Validación previa en el orden de D5 y re-chequeo previo al `send`.
  Verifica: 8.3 verde.
- [x] 8.5 RED — `backend/tests/modules/test_reminder_dispatch_retry.py`: éxito en el
  2.º intento ⇒ `sent`, `attempts=2`; tres fallos ⇒ `failed` con backoff 5 min y
  30 min en `available_at` y reloj fijo; con email ⇒ aparece el job de email
  `scheduled` del mismo paso y sin email o con `opt_out` de email no; error no
  reintentable ⇒ `failed` al primer intento; el envío exitoso guarda
  `provider_message_id`, `sent_at` y `cost_micros` y escribe `delivery_event`; el
  costo agregado por clínica y paso suma solo la propia; `last_error` y `payload`
  no contienen nombre, teléfono, email ni link. Verifica: `cd backend; pytest
  tests/modules/test_reminder_dispatch_retry.py -q` → falla.
- [x] 8.6 GREEN — Tx de resultado, backoff, escalado a email y costos. Verifica: 8.5
  verde.
- [x] 8.7 RED/GREEN — Escenarios del change en un solo archivo
  `backend/tests/modules/test_reminder_scenarios.py`: **caída del worker** (tres
  jobs vencen con el worker detenido; al volver, envía los de turno futuro y salta
  los de turno iniciado), **doble tick** y **opt-out a mitad de secuencia** (el de
  72 h `sent`, tras la baja los de 24 h y 3 h `skipped`). Verifica: el archivo
  verde.

## 9. Runtime del worker (D12)

- [x] 9.1 RED — `backend/tests/modules/test_worker_runtime.py`: `build_worker_settings` declara un
  cron por minuto y `max_jobs = REMINDER_WORKER_CONCURRENCY`; `on_startup` arma
  engine, reloj y senders según los settings; `entrypoint.main()` falla nombrando
  las variables si faltan `REDIS_URL`/`DATABASE_URL`. Verifica: `cd backend; pytest
  tests/test_worker_runtime.py -q` → falla.
- [x] 9.2 GREEN — `app/worker/settings.py` y `entrypoint.py` reemplazando
  `idle_forever` por el worker ARQ, sin cambiar el comando de compose. Verifica: 9.1
  verde y el entrypoint real corre contra Postgres y Redis (cron al arrancar y al minuto, canales
  `ninguno` con los proveedores en `disabled`, apagado ordenado por SIGTERM). Se verificó en el
  contenedor de tests con la imagen `api` ya construida; **no** se corrió `docker compose up
  worker` porque construiría imágenes (CLAUDE.md: no buildear sin pedido).

## 10. Integración, calidad y documentación

- [x] 10.1 Prueba extremo a extremo con Postgres y Redis reales: reservar online con
  opt-in, avanzar el reloj fijo por los pasos, ver `sent` en `fake`, confirmar con
  el link firmado del mensaje y comprobar que 72/24 quedaron `cancelled` y el de
  3 h se envía. Verifica: `cd backend; pytest tests/test_reminders_e2e.py -q` verde.
- [x] 10.2 Gate de calidad por change (regla 9): `ruff`, `black --check` y `mypy`
  limpios y la suite completa verde en el contenedor py3.12; sin `any` ni cambios
  de frontend. Verifica: salida de los tres comandos y `pytest -q` sin fallas
  nuevas respecto del baseline de 0.1.
- [x] 10.3 Documentación: `backend/README.md` (variables, proveedores, cómo habilitar
  email en dev, qué hace el worker); `knowledge-base/07_flujos_principales.md` Flujo
  3 paso 5 alineado con “confirmar cancela solo los pasos que piden confirmar”;
  `knowledge-base/11_whatsapp_y_recordatorios.md` §3 con `sending`, el lease y el
  link firmado; marcar C-09 en `CHANGES.md`. Verifica: `diff AGENTS.md CLAUDE.md`
  sin diferencias y los comandos documentados corren tal cual.
- [x] 10.4 `openspec validate c-09-motor-recordatorios --strict` sin errores.
  Verifica: salida del comando.

## Workflow follow-up

- Revisar la implementación contra los specs con `/code-review` antes de archivar.
- Archivar con `/opsx:archive c-09-motor-recordatorios` (sincroniza los specs
  principales: `reminders/*` nuevos y deltas de `booking/manage-token`,
  `core/patients` y `core/seed`) y verificar el resultado.
- Dejar a C-10 las decisiones diferidas: adaptador Cloud API, plantilla de
  “turno reprogramado”, ventana de silencio y reporte de costos.

## Baseline (completar en 0.1)

| Suite | Passed | Failed | Notas |
|---|---|---|---|
| `pytest -q` (backend, py3.12, Postgres 15.8 + Redis 7.4 en contenedores) | 979 | 0 | Sin fallas de entorno; 2026-11-05 |
