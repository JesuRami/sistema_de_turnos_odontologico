# Design — C-09 `motor-recordatorios`

Motivación y alcance: `proposal.md`. Comportamiento exigido: `specs/`.

## Context

- **Cabeza de Alembic**: `c08_manage_token` (la cadena es
  `c06 → c13_event_slot → c07 → c08`). CHANGES.md habla de “migración 005”; el
  repo nombra las revisiones por change, así que esta es `c09_reminder_engine`.
- `clinic.reminder_steps` (jsonb, default 72/24/3 h por WhatsApp) y
  `clinic.timezone` ya existen (C-02/C-04). `patient.whatsapp_opt_in` ya existe y
  lo escriben tres sitios: `booking_public/service.py` (`_match_or_create`),
  `patients/service.py` (alta del personal) y `clinic/service.py:create_patient`.
- **Toda mutación de turno pasa por tres funciones** de C-05: `AppointmentsService.book`
  (alta), `AppointmentsService._reschedule` y `states.apply_transition`. Las usan
  recepción, la reserva pública (C-07), el bloqueo de agenda con cancelación
  (`agenda/blocks.py`) y la gestión por token (C-08). C-10 las reutilizará para
  “SÍ/NO”.
- `modules/reminders/invalidation.py` (C-08) define el puerto
  `ReminderInvalidator` y un `NoopReminderInvalidator`; `manage/service.py` lo
  llama tras confirmar, cancelar y reprogramar.
- `appointment_event` y `auth_event` ya usan un trigger `BEFORE UPDATE OR DELETE`
  para ser append-only (patrón a repetir).
- El worker (`app/worker/entrypoint.py`) verifica Redis y Postgres, abre un pool
  ARQ sin funciones y queda ocioso. `arq>=0.26` y `redis` ya son dependencias.
- **La base solo guarda el SHA-256 del token de gestión** (C-07 D8) y un turno de
  recepción no tiene token. Un mensaje necesita el link en claro.
- `.env.example` ya declara `WHATSAPP_TOKEN`, `META_*`, `EMAIL_*` y
  `REMINDER_WORKER_CONCURRENCY` sin que nada los lea todavía.

## Goals / Non-Goals

**Goals:**
- Que un mensaje nunca salga de un turno inexistente, iniciado o movido, ni de un
  paciente sin consentimiento, aun si falla una de las defensas.
- Que reiniciar, duplicar o escalar el worker no pierda ni repita mensajes
  (salvo el caso acotado de la sección Riesgos).
- Un solo punto de verdad para “qué jobs corresponden a este turno”,
  independiente de quién mutó el turno.
- Que C-10 enchufe el envío real y el webhook sin tocar el motor.

**Non-Goals:**
- Webhook, estados `delivered/read`, “SÍ/NO/STOP”, adaptador Cloud API,
  reporte de costos, UI de alertas (ver `proposal.md` → Fuera de alcance).
- Horario de silencio nocturno: los pasos salen a `starts_at − offset` aunque
  caigan de madrugada (ver Open Questions).

## Decisions

### D1. Modelo de datos (migración única `c09_reminder_engine`)

```
notification_template  (clinic_id, channel, step) UNIQUE;  id ⟷ (clinic_id,id) UNIQUE
reminder_job           UNIQUE (appointment_id, step, channel)
delivery_event         append-only; UNIQUE (reminder_job_id, provider_event_id) WHERE NOT NULL
consent                append-only
```

| Tabla | Columnas clave |
|---|---|
| `notification_template` | `id`, `clinic_id`, `channel`, `step`, `meta_template_name`, `locale` (`es_AR`, CHECK), `body_preview`, `active`, timestamps |
| `reminder_job` | `id`, `clinic_id`, `appointment_id`, `step`, `channel`, `scheduled_for`, `available_at`, `starts_at_snapshot`, `status`, `reason`, `template_id`, `attempts`, `claimed_at`, `sent_at`, `provider_message_id`, `cost_micros`, `last_error`, timestamps |
| `delivery_event` | `id`, `clinic_id`, `reminder_job_id`, `event_type`, `provider_event_id`, `payload` (jsonb, **sin PII**), `occurred_at`, `received_at` |
| `consent` | `id`, `clinic_id`, `patient_id`, `channel`, `status`, `source`, `changed_by_user_id`, `changed_at` |

- Enums nativos de Postgres (creados por la migración, no por `create_all`, como en
  C-05): `reminder_status`, `reminder_channel`, `consent_status`,
  `consent_source`, `delivery_event_type`.
- `reminder_status`: `scheduled, sending, sent, delivered, read, failed, skipped,
  cancelled`. **`sending` no está en la KB**: es el lease del reclamo (D4);
  `delivered/read` los escribe C-10.
- `step` es `text` con CHECK `^(created|t_[0-9]+h)$` (los pasos son offsets
  configurables, no un conjunto cerrado). `reason` es `text` con un catálogo
  cerrado en Python (`no_consent, no_recipient, appointment_started,
  appointment_inactive, step_elapsed, step_removed, rescheduled, confirmed,
  template_inactive, provider_rejected, send_failed, lease_expired`) validado
  por test, no por CHECK, para poder ampliarlo sin migración.
- `scheduled_for` es el instante calculado; `available_at` es cuándo se puede
  reclamar (arranca igual y el backoff lo empuja). Así se conserva la hora
  original para reportes. `starts_at_snapshot` es el `starts_at` con el que se
  calculó el job (D6).
- **Regla 4**: todas con `clinic_id NOT NULL` y FK **compuesta**
  `(clinic_id, appointment_id)`, `(clinic_id, patient_id)`,
  `(clinic_id, template_id)`, `(clinic_id, reminder_job_id)`; test de
  aislamiento cross-tenant por tabla.
- **Regla 11**: son tablas nuevas y vacías, así que los índices y FK se crean en
  el `CREATE TABLE`, sin `CONCURRENTLY` ni `NOT VALID`. Índices:
  `reminder_job (available_at) WHERE status='scheduled'` (cola),
  `reminder_job (appointment_id)`, `reminder_job (clinic_id, step, sent_at)`
  (agregado de costo), `consent (patient_id, channel, changed_at DESC)`.
- **Regla 7/8**: nada se borra; los triggers `BEFORE UPDATE OR DELETE` de
  `delivery_event` y `consent` repiten el patrón de `appointment_event`. Las
  consultas nombran columnas.
- **Backfill** (en la misma revisión, idempotente): una fila `consent`
  `whatsapp/opt_in/legacy` por paciente con `whatsapp_opt_in = true`, y las ocho
  plantillas por defecto (D11) para cada clínica existente.

**Alternativa descartada**: guardar `delivery_event` como columna jsonb de
`reminder_job` — rompe el append-only y el dedup por `provider_event_id` que
necesita C-10.

### D2. Programación estado-basada, no acción-basada

Una sola función `reconcile(session, appointment, now)` calcula el conjunto
deseado de jobs a partir del **estado actual** del turno y lo compara con las
filas existentes:

1. Si el turno no está `pending|confirmed` → cancelar todos los `scheduled`
   (`reason=appointment_inactive`).
2. Si no, para cada paso de `clinic.reminder_steps` (`scheduled_for = starts_at −
   offset_h`): es *deseado* si `scheduled_for > now`. Si el turno es **online y
   está `confirmed`**, se excluyen los pasos que *piden confirmar* (`created` y
   `offset_h ≥ 24`, constante `CONFIRM_REQUEST_MIN_OFFSET_H`).
3. Por cada `(step, channel)`:
   - fila `scheduled` y deseado → actualizar `scheduled_for/available_at/
     starts_at_snapshot` si cambiaron;
   - fila `scheduled` y no deseado → `cancelled` con `reason` (`confirmed`,
     `step_elapsed` o `rescheduled`);
   - sin fila y deseado → `INSERT … ON CONFLICT (appointment_id, step, channel) DO
     NOTHING`;
   - fila en cualquier otro estado → intacta.

Es idempotente por construcción (llamarla dos veces no cambia nada la segunda),
lo que hace inocuo cualquier doble disparo y cubre “reprogramar”, “confirmar” y
“cambió la configuración de pasos” con el mismo código. El job `created` lo crea
una función aparte, `schedule_created(...)`, solo desde `book()`, con
`scheduled_for = now`, y `reconcile` nunca lo inserta.

**Por qué “online + confirmed” y no un flag**: un turno de recepción nace
`confirmed` (RN-ST-02) y debe recibir los tres pasos; el único turno que pasa de
`pending` a `confirmed` es el online, así que `origin + status` distingue los dos
casos sin guardar historia ni mirar `appointment_event`.

**Alternativa descartada**: despachar por acción (`create/confirm/cancel/…`) con
una rama por caso. Duplica lógica, obliga a que cada caller pase la acción
correcta y no se autocorrige si un caller se olvida.

### D3. Dónde se engancha: en el núcleo, no en los callers

`reconcile` se invoca desde las **tres funciones de escritura de C-05**:
`book()` (tras escribir turno y evento), `_reschedule()` (si hubo cambio) y
`apply_transition()` (tras mutar). Eso cubre sin tocar más código recepción,
reserva pública, bloqueo de agenda con cancelación, gestión por token y el
“SÍ/NO” de C-10. Todo corre en la transacción de la mutación (sin commit
propio): si falla, la mutación revierte.

`reconcile` es una función pura sobre `AsyncSession` (importa solo modelos), así
que `states.py` puede importarla sin ciclos ni inyección. Se pasa `now`, que esas
funciones ya reciben.

**Puerto de C-08**: `get_reminder_invalidator()` devuelve
`ReconcilingInvalidator`, que delega en `reconcile`. Como el núcleo ya reconcilia,
la llamada de `manage` es redundante pero **no hace nada la segunda vez**
(idempotencia de D2) — cuesta una consulta y mantiene intactos el contrato, el spy
de los tests de C-08 y la superficie pública. No se saca la llamada de `manage`
porque eso cambiaría el contrato que C-08 cerró.

**Alternativa descartada**: que solo el puerto reconcilie y agregar la llamada en
cada caller. Es la superficie de olvido que el spec de C-08 intentó evitar y
dejaría fuera a bloqueos y a C-10.

### D4. Reclamo con lease y envío fuera de la transacción

Enviar por HTTP con 100 locks de fila abiertos bloquea reprogramaciones y
cancelaciones durante segundos. El tick en cambio:

1. **Tx corta de reclamo**: `SELECT … FROM reminder_job WHERE status='scheduled'
   AND available_at <= now AND channel = ANY(:canales_habilitados) ORDER BY
   available_at LIMIT 100 FOR UPDATE SKIP LOCKED`. Carga en una consulta el
   contexto (turno, paciente, profesional, clínica, plantilla, consentimiento) y
   aplica la validación previa (D5). Por job: cancela/salta/falla, o lo pasa a
   `sending` con `claimed_at = now` y `attempts + 1`. Commit.
2. **Re-chequeo y envío** (concurrencia acotada por `REMINDER_WORKER_CONCURRENCY`,
   semáforo): una lectura del turno justo antes del `send`; si ya no está activo
   o empezó, el job se cancela/salta y no se envía.
3. **Tx de resultado** por job: `sent` + `provider_message_id` + `sent_at` +
   `cost_micros` + `delivery_event`, o falla (D7).
4. **Lease**: al inicio del tick, `sending` con `claimed_at < now − 5 min` vuelve
   a `scheduled` (`reason=lease_expired`, el intento ya contó) y se registra el
   evento. Cubre worker caído a mitad de lote.

El worker **no toma locks sobre `appointment`**: la mutación bloquea el turno y
después actualiza jobs; si el worker bloqueara jobs y luego turnos habría un
deadlock por orden invertido. Se acepta la ventana descripta en Riesgos.

Un tick procesa lotes hasta vaciar lo vencido o agotar un presupuesto de 50 s
(`REMINDER_TICK_BUDGET_S`), para no solaparse con el siguiente.

**Alternativa descartada**: mantener la transacción abierta durante el envío.
Más simple, pero ata los locks a la latencia del proveedor.

### D5. Validación previa (red de seguridad)

En orden, y el primer fallo decide el destino del job:

| # | Condición | Destino |
|---|---|---|
| 1 | turno `cancelled/absent/no_show/present` | `cancelled` (`appointment_inactive`) |
| 2 | `now ≥ starts_at` | `skipped` (`appointment_started`) |
| 3 | `starts_at ≠ starts_at_snapshot` | se llama a `reconcile` y el job se libera (no se envía con la hora vieja) |
| 4 | sin consentimiento vigente del canal (D8) | `skipped` (`no_consent`) |
| 5 | plantilla ausente o inactiva | `failed` (`template_inactive`) + escalado |

Las filas 1–3 existen aunque `reconcile` ya mantenga el estado: son la defensa si
un camino de escritura futuro olvida el enganche (D3) o alguien toca la base a
mano. Un job que llegó a `sending` ya pasó las cinco.

**Ventana de 24 h de Meta** (RN-WA-03): `choose_message_kind(last_inbound_at,
now)` devuelve `template` o `session`. Todo recordatorio proactivo es `template`
(la ventana solo habilita seguimientos libres a una respuesta). C-09 no tiene
mensajes entrantes (los trae C-10), así que siempre pasa `None`; la función y su
test quedan listos y el sender acepta ambos tipos.

### D6. `starts_at_snapshot` y la hora de la clínica

`scheduled_for = starts_at − offset_h` se calcula con aritmética de instantes
(`timestamptz`), que es independiente de la zona. La zona de la clínica interviene
solo al **renderizar** fecha y hora (“jueves 9/10, 15:30”, `ZoneInfo(clinic.timezone)`,
nombres de día en español sin depender del locale del SO). El snapshot permite
detectar el caso 3 de D5 sin comparar horas calculadas.

### D7. Reintentos, escalado y errores no reintentables

- Máximo `REMINDER_MAX_ATTEMPTS = 3` (RN-WA-04: “N fallos, default 3”). Backoff
  `REMINDER_BACKOFF_MINUTES = 5,30,120`: tras el 1.º fallo `available_at = now+5 min`,
  tras el 2.º `now+30 min`, tras el 3.º `failed`. El tercer valor (2 h) es el que
  usa la KB para describir la escalera y solo entra en juego si se sube el máximo.
- El puerto de envío lanza `SendError(retryable: bool, code: str)`. Los
  `retryable=False` (destinatario inválido, plantilla rechazada) fallan de
  inmediato sin consumir la escalera.
- **Escalado**: al quedar `failed` un job de WhatsApp, si el paciente tiene email y
  no tiene `opt_out` de email, se inserta (ON CONFLICT DO NOTHING) el job
  `(appointment, step, email)` con `available_at = now` y la plantilla de email
  del paso. La clave `(appointment, step, channel)` ya permite un job por canal
  y paso, así que no hace falta otra tabla ni otro estado.
- `last_error` guarda solo un **código** (`timeout`, `http_5xx`, `rejected`…),
  nunca el mensaje del proveedor, que puede traer el teléfono (regla 13).

### D8. Consentimiento: un escritor, un dato que leer

`ConsentService.record(session, patient, channel, status, source, user_id=None)`
es el único camino que escribe `consent` **y** `patient.whatsapp_opt_in`, en la
misma transacción; si el estado ya es el pedido, no hace nada (evita ruido en un
log que es auditoría). Los tres escritores actuales pasan por él (en
`create_patient` el parámetro `whatsapp_opt_in` sigue existiendo y delega).

- **Lectura del motor**: `patient.whatsapp_opt_in` para WhatsApp (un booleano en
  la fila ya cargada); para email, `NOT EXISTS (opt_out vigente)`. `consent` es el
  historial auditable; el flag es su proyección. Un test de paridad verifica que
  el último `consent` de WhatsApp de cada paciente coincide con el flag.
- **Efecto inmediato**: `record(... opt_out)` marca `skipped` (`no_consent`) los
  jobs `scheduled` del paciente y canal en la misma transacción
  (`UPDATE … FROM appointment WHERE patient_id = …`). No se reviven al volver a
  dar opt-in: el próximo `reconcile` no los recrea porque la fila ya existe, y
  eso es deliberado (una baja y un alta en horas no justifica reabrir una
  secuencia).
- Fusión de pacientes (C-06): no hereda el opt-in; el conservado mantiene el suyo
  y el destinatario de un job se lee del turno al enviar, así que un turno movido
  de ficha usa el consentimiento de la ficha nueva.

### D9. Link de gestión reproducible: token firmado sin estado

Problema: para escribir `{{link}}` el motor necesita el token en claro, y la base
solo tiene su hash. Rotar el token al enviar cada mensaje mataría el link del
mensaje anterior y el de la página de reserva; guardarlo cifrado contradice C-07
D8; y los turnos de recepción no tienen token.

Decisión: un **segundo formato de credencial**, aceptado por el mismo endpoint:

```
token   = "v1." + base64url( appointment_id[16] ‖ HMAC-SHA256(MANAGE_LINK_SECRET,
                              "manage-link/v1" ‖ appointment_id)[:16] )      # 46 chars
url     = {FRONTEND_PUBLIC_URL}/g/{token}
```

- `ManageService.resolve` acepta `TOKEN_RE` (43 caracteres, hash) **o** `SIGNED_RE`
  (`v1.` + 43). El punto `.` no está en el alfabeto del token aleatorio, así que
  no hay colisión ni ambigüedad.
- Un token firmado se verifica con `hmac.compare_digest`; si la firma es válida se
  carga el turno **por id** y se aplican exactamente las mismas guardas de C-08
  (TTL `ends_at + 72 h`, vista mínima, ventana de cancelación, rate-limit por
  `sha256(token)`, 404 uniforme, `Cache-Control: no-store`). Firma inválida,
  formato roto o id inexistente → el mismo `404 manage_link_not_found`.
- Los links ya emitidos (aleatorios, hash en `appointment`) siguen funcionando: no
  se rota nada ni se toca `manage_token_hash`.
- **Forma canónica**: el último carácter de 32 bytes en base64url lleva 2 bits de
  relleno, así que cambiarlo daría otra cadena para el mismo token. `verify`
  re-firma y exige igualdad con la cadena recibida; si no, el cupo por
  `sha256(token)` se esquivaría con 4 variantes del mismo link (hallado por la
  suite completa durante la implementación).
- `MANAGE_LINK_SECRET`: ≥ 32 bytes, validado al arrancar como `JWT_SECRET`
  (mismo `SettingsError`, que no imprime el valor); regla 6.

**Consecuencias asumidas**: el link firmado de un turno es estable (no se puede
revocar uno suelto; el límite es el TTL absoluto, el mismo riesgo ya aceptado en
DD-04) y rotar el secreto invalida los links firmados vivos.

**Alternativas descartadas**: (a) rotar el token por mensaje — mata links
anteriores; (b) cifrar el token en la fila — contradice C-07 D8 y agrega una
clave a gestionar igual; (c) tabla de “links de recordatorio” con hash propio —
resuelve lo mismo con más estado y un join extra en cada resolución.

### D10. Puerto de envío y proveedores

```python
class OutboundMessage:  # sin __repr__: lleva PII
    channel; to: str; template_name: str; locale: str; params: Mapping[str, str]; body: str
class ReminderSender(Protocol):
    channel: ReminderChannel
    async def send(self, message: OutboundMessage) -> SendResult  # provider_message_id
```

- **Proveedores seleccionados por settings**: `REMINDER_WHATSAPP_PROVIDER =
  disabled | fake` (el valor `meta` lo agrega C-10) y `REMINDER_EMAIL_PROVIDER =
  disabled | smtp | fake`. Default `disabled` en ambos.
- `disabled` ⇒ el tick excluye ese canal del reclamo (`channel = ANY(:habilitados)`):
  los jobs quedan `scheduled`, no se marcan enviados en falso y, si el turno
  empieza antes de que se habilite, terminan `skipped` por D5-2. Se loguea una vez
  por tick el canal deshabilitado.
- `fake` guarda los envíos en memoria (para tests) y solo loguea metadatos
  (canal, job id, paso), jamás destinatario ni cuerpo.
- `smtp` usa `smtplib` de la biblioteca estándar en `asyncio.to_thread` con
  `EMAIL_HOST/PORT/USER/PASSWORD/FROM` (ya en `.env.example`), STARTTLS en 587; sin
  dependencia nueva en runtime. Se prueba contra un servidor local `aiosmtpd`
  (dev-only), no con un mock.
- **Costo** (RN-WA-05): `REMINDER_COST_WHATSAPP_MICROS` y
  `REMINDER_COST_EMAIL_MICROS` (USD × 10⁻⁶ por mensaje, default 0) se copian a
  `cost_micros` al enviar. Una tabla de precios por país/categoría queda para C-10
  junto con el reporte.

### D11. Plantillas y seed

`notification_template` por clínica y `(channel, step)`. El seed (y el backfill de
la migración) crean, con `ON CONFLICT (clinic_id, channel, step) DO NOTHING`:
`turno_creado_v1`, `recordatorio_72h_v1`, `recordatorio_24h_v1`,
`recordatorio_3h_v1` para WhatsApp (nombres de la KB, `es_AR`, `active=true`) y
cuatro cuerpos de email. `body_preview` usa solo `{{nombre}} {{clinica}} {{fecha}}
{{hora}} {{profesional}} {{link}}`. **La KB nombra también `{{direccion}}`**: la
clínica no tiene dirección todavía, así que ese placeholder queda fuera de C-09 y
de las plantillas sembradas (los textos aprobados en Meta los define C-10).

El texto del email se renderiza desde `body_preview`; el de WhatsApp se envía como
plantilla con `params` (el cuerpo aprobado vive en Meta).

### D12. Runtime del worker: ARQ con un cron por minuto

`app/worker/settings.py` arma la configuración de ARQ con
`build_worker_settings(settings)` (un diccionario que `create_worker` acepta, en
vez de una clase de módulo: se construye sin tocar el entorno y los valores se
leen una vez) con `cron(reminder_tick, second=0, run_at_startup=True)` y
`max_jobs = REMINDER_WORKER_CONCURRENCY`; `on_startup` crea engine, sessionmaker,
reloj y senders. `entrypoint.main()`
conserva `check_redis/check_postgres` y reemplaza `idle_forever` por
`create_worker(WorkerSettings).async_run()`. El comando de compose
(`python -m app.worker.entrypoint`) no cambia.

ARQ deduplica el cron entre réplicas por id de job, pero **la garantía real es
`SKIP LOCKED` + la clave única** (D1/D4); Redis solo evita ticks redundantes. La
lógica del tick vive en una función `run_tick(session_factory, senders, now)`
independiente de ARQ para testearla con Postgres real y un reloj fijo.

**Alternativa descartada**: bucle `asyncio.sleep(60)` propio. Funciona, pero
descarta la decisión ya aprobada de ARQ (docstring del entrypoint) sin ganar nada
y pierde el cron deduplicado entre réplicas.

### D13. Configuración nueva (`.env.example`, test de claves)

`MANAGE_LINK_SECRET`, `REMINDER_WHATSAPP_PROVIDER`, `REMINDER_EMAIL_PROVIDER`,
`REMINDER_MAX_ATTEMPTS`, `REMINDER_BACKOFF_MINUTES`, `REMINDER_LEASE_MINUTES`,
`REMINDER_TICK_BUDGET_S`, `REMINDER_BATCH_SIZE`, `REMINDER_COST_WHATSAPP_MICROS`,
`REMINDER_COST_EMAIL_MICROS`. Valores de ejemplo no secretos salvo
`MANAGE_LINK_SECRET` (placeholder obviamente falso, como `JWT_SECRET`);
`test_env_example.py` ya exige que toda clave de `Settings` esté en el archivo.
`MANAGE_LINK_SECRET` es obligatorio (≥ 32 bytes) salvo con `ENV=dev`, donde vacío
deshabilita los links firmados: así no se rompen las construcciones de `Settings`
de tests y CI que no lo declaran, y producción falla rápido si falta.

## Risks / Trade-offs

- **Envío duplicado si el worker muere entre el `send` y la transacción de
  resultado** (at-least-once) → el lease devuelve el job a `scheduled` y se
  reenvía. Se acepta: un recordatorio repetido es menos grave que uno perdido;
  `attempts` y `delivery_event` lo dejan visible. C-10 puede deduplicar con el id
  del proveedor.
- **Ventana de milisegundos**: una cancelación que llega entre el re-chequeo y el
  `send` envía un mensaje de un turno cancelado → el re-chequeo de D4 la reduce a
  la latencia del proveedor; no hay lock que la cierre sin el deadlock descripto.
- **Link firmado estable** → no revocable individualmente (ver D9); mitigado por
  TTL absoluto, 404 uniforme y rate-limit por token; la rotación de
  `MANAGE_LINK_SECRET` es la palanca de emergencia.
- **Jobs ya `sent` no se reenvían al reprogramar** → el paciente que recibió el
  aviso de 72 h con la fecha vieja no recibe uno nuevo. Hace falta una plantilla
  “turno reprogramado” (C-10).
- **Madrugada**: un paso de 72 h de un turno a las 8:00 sale a las 8:00 de hace tres
  días, pero uno de 3 h para un turno de 8:00 sale a las 5:00 → candidato a
  ventana de silencio (Open Questions).
- **Conflicto con la KB**: Flujo 3 paso 5 dice que confirmar cancela *todos* los
  jobs futuros; el usuario eligió cancelar solo los que piden confirmar. Hay que
  actualizar `07_flujos_principales.md` al archivar.
- **`reconcile` en el camino caliente** de crear/mover/cancelar → son dos
  consultas por mutación (jobs del turno + configuración de pasos, ya cargada en
  `load_policy`); se mide en la prueba de la semana de agenda existente
  (`test_appointments_week_perf.py`).
- **Backfill con `legacy`** → el origen real del opt-in previo no se conoce;
  `legacy` lo dice en vez de inventar `booking` (queda auditable).

## Migration Plan

1. `alembic upgrade head` aplica `c09_reminder_engine` (tablas nuevas, triggers,
   backfill de consentimiento y plantillas). No toca columnas existentes.
2. Desplegar `api` y `worker` con la misma imagen. Con los proveedores en
   `disabled` el motor programa pero no envía: se puede desplegar sin riesgo.
3. Habilitar `REMINDER_EMAIL_PROVIDER=smtp` o `fake` por entorno; WhatsApp queda
   `disabled` hasta C-10.
4. **Rollback**: `alembic downgrade c08_manage_token` borra las cuatro tablas, los
   triggers y los enums; el flag `patient.whatsapp_opt_in` se conserva (nunca se
   tocó su valor). Los links firmados ya enviados dejarían de resolver en el
   código viejo; no hay mensajes reales antes de C-10.

## Open Questions

- ¿Ventana de silencio nocturno (p. ej. no enviar entre 22:00 y 08:00 locales,
  difiriendo a la mañana)? No cambia el modelo ni los specs: sería un filtro más
  sobre `available_at`.
- ¿Costos reales por país/categoría de Meta y umbral de alerta por clínica? Es el
  reporte de C-10.
- ¿El adaptador de email definitivo es SMTP o la API de un proveedor? El puerto
  permite cambiarlo sin tocar el motor.
