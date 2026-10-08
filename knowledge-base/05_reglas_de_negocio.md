# Reglas de Negocio

Cada regla tiene código único `RN-{DOMINIO}-{NN}` para trazabilidad desde historias (`06`) y flujos (`07`). Donde la regla admite excepción, la excepción también está codificada: lo no escrito no existe.

## Dominio: Agenda y solapamientos (RN-AG)

- **RN-AG-01**: Un turno vigente (`pending`, `confirmed`, `present`) ocupa el intervalo `[starts_at, ends_at)` del profesional Y del sillón simultáneamente. Dos turnos vigentes nunca comparten profesional ni sillón en intervalos intersectados. — Es la invariante del sistema; se garantiza en DB (exclusion constraint), no solo en backend.
- **RN-AG-02**: Los turnos `cancelled` y `no_show` liberan el hueco y no participan en la exclusión. El historial se conserva para reportes.
- **RN-AG-03**: La duración del turno la determina el tipo de práctica / `slot_duration_min` de la regla de horario, no el paciente. La reserva online solo elige entre huecos pre-calculados; nunca envía duración libre.
- **RN-AG-04**: Todo turno nace con `buffer` posterior si el profesional lo tiene configurado (`buffer_min`); el buffer integra el rango excluido aunque no se muestre como "turno" en la UI.
- **RN-AG-05**: La agenda respeta `schedule_rule` + `block`: fuera de horario o dentro de un bloqueo no existen huecos ofrecibles por ningún canal. Sin regla de horario vigente, el profesional no es reservable.
- **RN-AG-06**: Cambiar `starts_at/ends_at` (reprogramar) es una operación atómica que revalida RN-AG-01 sobre el nuevo intervalo; si colisiona, la operación entera falla y el turno conserva su horario original.

## Dominio: Sobreturnos / overbooking (RN-SB)

- **RN-SB-01**: El sobreturno nunca es silencioso: exige flag `is_overbooking=true` explícito en la request y rol `admin` o `recepcion`. El paciente online jamás puede generar un sobreturno.
- **RN-SB-02**: El sobreturno se registra en auditoría con actor, motivo obligatorio y turno/s con los que colisiona. Sin motivo no se persiste.
- **RN-SB-03**: Máximo configurable de sobreturnos por profesional y día (default 2, configurable por clínica). Superarlo exige rol `admin`. **Suposición:** el default 2 es operativo, no clínico; validar en piloto.
- **RN-SB-04**: Un sobreturno no genera jobs de recordatorio adicionales fuera del flujo normal; el paciente del sobreturno recibe el mismo circuito que cualquier turno.

## Dominio: Bloqueos (RN-BL)

- **RN-BL-01**: Un bloqueo puede ser por profesional, por sillón o por ambos; al menos uno debe estar presente. El bloqueo por profesional sin sillón bloquea a la persona en todos los sillones; el bloqueo por sillón sin profesional bloquea el recurso para todos.
- **RN-BL-02**: No se crea un bloqueo que pise turnos vigentes salvo que esos turnos se reprogramen o cancelen primero en la misma operación (transacción). El sistema lista los turnos afectados y exige resolución explícita; nunca los borra ni los mueve solo.
- **RN-BL-03**: Los bloqueos pasados son inmutables (solo lectura). Los futuros pueden editarse/eliminarse con auditoría. Eliminar un bloqueo no crea turnos: solo reabre huecos.
- **RN-BL-04**: Los feriados y cierres de clínica se modelan como bloqueo de todos los profesionales/sillones en el rango (generados por el admin, no por calendario automático nacional en v1.0). **Suposición:** no se integra calendario oficial de feriados AR en el MVP; es lista manual.

## Dominio: Lista de espera (RN-LE)

- **RN-LE-01**: Una persona tiene como máximo una entrada `waiting/offered` por profesional (o "cualquiera") a la vez. Duplicados se rechazan con mensaje que ofrece gestionar la existente.
- **RN-LE-02**: Al liberarse un hueco (cancelación), el sistema propone automáticamente a la primera entrada compatible por orden FIFO con tolerancia de preferencia horaria (`preferred_from/to`). FIFO con filtro, no FIFO puro ciego.
- **RN-LE-03**: La oferta tiene expiración (`expires_at`, default 4 h configurable). Vencida sin respuesta, pasa al siguiente de la cola y la entrada vuelve a `waiting`. Tres ofertas vencidas consecutivas marcan la entrada como `expired` para no bloquear la cola con contactos muertos.
- **RN-LE-04**: Aceptar la oferta crea el turno (origen `waitlist`) y cancela las demás ofertas pendientes de esa entrada. Rechazarla no penaliza: la entrada conserva su posición.
- **RN-LE-05**: La lista de espera es por hueco liberado, no es sobreturno encubierto: aceptar una oferta valida RN-AG-01 normalmente.

## Dominio: Cancelación y reprogramación (RN-CX)

- **RN-CX-01**: Ventana de cancelación libre configurable por clínica (default 24 h antes del turno). Dentro de la ventana, el paciente online puede cancelar; fuera de ella (menos de 24 h), la cancelación online se bloquea y se deriva a contactar a la clínica (recepción puede hacerlo igual).
- **RN-CX-02**: Reprogramar conserva el `appointment_id` y emite evento de auditoría con horario anterior/nuevo. Reprogramar fuera de la ventana sigue RN-CX-01 (bloqueo online, permitido a recepción).
- **RN-CX-03**: Cancelar un turno cancela sus `reminder_job` pendientes (pasan a `cancelled`) y dispara evaluación de lista de espera (RN-LE-02) en la misma transacción lógica.
- **RN-CX-04**: El motivo de cancelación es obligatorio para recepción/admin y opcional (lista cerrada + "otro") para el paciente. Los motivos alimentan el reporte de cancelaciones.
- **RN-CX-05**: Un turno `present` o pasado no puede cancelarse; se corrige con evento administrativo auditado, no con cambio de estado normal.

## Dominio: Estados del turno (RN-ST)

- **RN-ST-01**: Máquina de estados permitida: `pending → confirmed → present → (done implícito)`; `pending/confirmed → cancelled`; `confirmed → absent/no_show` (post-horario, solo personal). `cancelled`, `absent` y `no_show` son terminales.
- **RN-ST-02**: La reserva online nace en `pending` y pasa a `confirmed` por confirmación (click en token, respuesta SÍ por WhatsApp, o confirmación manual de recepción). La reserva de recepción nace `confirmed` directamente (el contacto ya ocurrió).
- **RN-ST-03**: Solo personal marca `present/absent/no_show`, y solo el día del turno o después. El paciente nunca se auto-marca presente.
- **RN-ST-04**: `no_show` (ausente sin aviso) vs `cancelled` tardío se distinguen por si hubo aviso antes del inicio. La distinción alimenta métricas distintas (ausentismo real vs. cancelación).

## Dominio: Reserva online pública (RN-ON)

- **RN-ON-01**: La disponibilidad pública expone solo huecos libres (fecha/hora/profesional), nunca datos de otros pacientes ni el nivel de ocupación real.
- **RN-ON-02**: Toda reserva online exige nombre + al menos un contacto (teléfono o email) + opt-in explícito de WhatsApp si deja teléfono. Sin contacto no hay turno (un turno sin canal de recordatorio es un ausente programado).
- **RN-ON-03**: Rate-limit por IP y por slug (valores a calibrar en diseño; default propuesto 10 reservas/hora/IP) + protección anti-enumeración en el endpoint de disponibilidad.
- **RN-ON-04**: El link de gestión (`manage_token`) tiene TTL (default 72 h post-turno, luego expira) y es de un solo turno. Rotar el token en cada reprogramación es opcional de seguridad (a decidir; ver `10_preguntas_abiertas.md`).
- **RN-ON-05**: Si el paciente reserva con un teléfono ya registrado, se reutiliza el `patient_id` existente (match por teléfono normalizado E.164); no se crean duplicados silenciosos.

## Dominio: WhatsApp y consentimiento (RN-WA)

- **RN-WA-01**: Sin `whatsapp_opt_in=true` no se envía ningún mensaje por WhatsApp. El opt-in se recoge en la reserva o lo carga recepción; el opt-out (`STOP`, "no quiero más") se procesa por webhook y bloquea el canal inmediatamente.
- **RN-WA-02**: Solo plantillas aprobadas por Meta, en `es_AR`. Ningún texto libre promocional por API en v1.0. Los recordatorios son utilitarios (categoría utility).
- **RN-WA-03**: Ventana de 24 h de Meta: fuera de ella solo plantillas; las respuestas del paciente (SÍ/NO) dentro de la ventana permiten mensajes de seguimiento sin plantilla.
- **RN-WA-04**: Cada envío es idempotente por `(appointment_id, step, channel)`. Reintentos con backoff ante fallos del proveedor; tras N fallos (default 3) el job pasa a `failed` y escala a email si hay dirección.
- **RN-WA-05**: El costo por mensaje es atribuible por clínica y por paso (base para facturación/transparencia futura). Desde v1.0 se registra `provider_message_id` y estado de entrega por job.

## Dominio: Excepciones globales

- **RN-GL-01**: Toda mutación de agenda escribe `appointment_event` en la misma transacción. Si la auditoría no se puede escribir, la mutación falla. Sin excepciones.
- **RN-GL-02**: Ninguna operación automática (recordatorio, oferta de lista de espera, expiración) cambia el horario de un turno existente. Las automatizaciones proponen; los humanos (o el paciente con su token) disponen.
- **RN-GL-03**: Zona horaria única por clínica (`America/Argentina/Buenos_Aires` por defecto). Todos los `timestamptz` se interpretan en la zona de la clínica; el frontend nunca hace aritmética de zonas.
- **RN-GL-04**: Borrado lógico en agenda: los turnos no se eliminan físicamente jamás (restricción de reporte y disputa). La "eliminación" es cancelación con motivo.
