# WhatsApp y Recordatorios (extra — núcleo del MVP)

> Archivo extra `11_*`: complementa los 10 canónicos. Si el MVP tiene un solo diferencial técnico, es este: **recordatorios que llegan, se miden y convierten en asistencia**.

## 1. Diseño del canal

- **Proveedor único**: Meta WhatsApp Cloud API. Sin gateways no oficiales, sin números personales automatizados (riesgo de ban y sin estados de entrega).
- **Identidad**: un número por clínica (preferido: la clínica aporta su Business Manager; alternativa transitoria: número compartido con remitente identificado — ver pregunta abierta en `10`). Los templates se aprueban por número/remitente.
- **Categoría de mensajes**: `utility` (recordatorios, confirmaciones, ofertas de lista de espera). Nada promocional por este canal en v1.0.
- **Idioma**: `es_AR` en todas las plantillas. Fecha/hora en formato argentino explícito ("jueves 9/10, 15:30") para evitar ambigüedad.
- **Opt-in/opt-out**: opt-in en reserva o cargado por recepción; opt-out por palabra (STOP, BAJA, "no me escriban") procesado en webhook y efectivo de inmediato. Sin opt-in no hay envío (RN-WA-01). Cada cambio de consentimiento se audita con fuente. Una baja sin mensaje citado, en un número compartido por varias clínicas, da de baja **todas** las fichas con ese teléfono (ante la duda, no escribir; decisión 2026-11-06); recepción puede reactivar el canal (`PUT /api/patients/{id}/consent/{canal}`). Las respuestas se asocian al turno por el mensaje citado y, sin él, solo si hay un único turno futuro vigente para ese teléfono; si no, no se toca ningún turno.

## 2. Plantillas (a aprobar en Meta antes del piloto)

| Paso | Nombre sugerido | Contenido (preview) | Botones |
|------|-----------------|---------------------|---------|
| Alta de turno | `turno_creado_v1` | "Hola {{nombre}}, tu turno en {{clinica}} es el {{fecha}} a las {{hora}} con {{profesional}}. Confirmalo acá: {{link}}" | Confirmar / Cambiar |
| T-72 h | `recordatorio_72h_v1` | "Hola {{nombre}}, te recordamos tu turno del {{fecha}} {{hora}} con {{profesional}}. ¿Confirmás? {{link}}" | Sí, confirmo / Reprogramar |
| T-24 h | `recordatorio_24h_v1` | "Mañana {{hora}} tenés turno con {{profesional}} en {{clinica}}. Respondé SÍ para confirmar o tocá para cambiar: {{link}}" | SÍ / Cambiar |
| T-3 h | `recordatorio_3h_v1` | "Hoy {{hora}} te esperamos en {{clinica}} ({{direccion}}). Llegá 10 min antes. {{link}}" | Cómo llegar / Cancelar |
| Oferta lista de espera | `hueco_lista_espera_v1` | "Se liberó un turno: {{fecha}} {{hora}} con {{profesional}}. Tenés {{horas}} h para tomarlo: {{link}}" | Tomarlo / Paso |
| Post-ausencia (recall suave) | `ausencia_recall_v1` | "Ayer no pudimos verte en {{clinica}}. ¿Reprogramamos? {{link}}" | Reprogramar |

**Suposición:** 6 plantillas cubren el MVP. El recall post-ausencia es deliberadamente suave (una sola, sin insistencia) hasta medir tolerancia.

## 3. Motor de recordatorios (reminder engine)

### Programación
- Al crear un turno vigente se insertan el job de alta de turno (`created`) y N `reminder_job` (default 3: T-72/24/3 h) con `scheduled_for = starts_at − offset` (la zona de la clínica solo interviene al mostrar fecha y hora). Reprogramar recalcula los pendientes; cancelar los marca `cancelled`. La programación es **estado-basada** (`reconcile`): se recalcula contra el estado actual del turno, así que es idempotente y la dispara el núcleo de escritura de turnos (C-05), no cada caller.
- Confirmar un turno online cancela solo los pasos que piden confirmar (alta, 72 h y 24 h, `offset_h ≥ 24`); el de 3 h sigue. Un turno de recepción nace `confirmed` y recibe todos los pasos.
- Regla anti-ruido: si el turno se crea a menos de X horas del inicio, solo se programan los pasos cuya `scheduled_for` quede en el futuro (nunca enviar "recordatorio 72 h" 2 h antes del turno).

### Ejecución (worker)
1. Tick cada 60 s (cron de ARQ): `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 100` sobre jobs vencidos en estado `scheduled`; los jobs válidos pasan a `sending` (**lease** de 5 min: si el worker muere, vuelven a `scheduled`) y el envío ocurre **fuera** de la transacción, con un re-chequeo del turno justo antes.
2. Validaciones previas al envío: turno vigente y no iniciado, horario vigente (`starts_at` igual al del job), opt-in del canal, destinatario, plantilla activa, ventana 24 h de Meta (elige plantilla vs. seguimiento libre para respuestas; C-09 siempre envía plantilla porque aún no hay mensajes entrantes).
3. Envío + guardado de `provider_message_id`; job → `sent`.
4. Webhooks (`delivered`, `read`, `failed`, respuesta del paciente) actualizan el job (en orden `sent → delivered → read`, sin retroceder) y `delivery_event`. "SÍ" ejecuta la misma transición que el link (`pending → confirmed`, idempotente); **"NO"/cambiar nunca cancela**: responde con el link de gestión si la ventana de cancelación sigue abierta o con el teléfono de la clínica si cerró (decisión 2026-11-06). Las respuestas no salen desde el webhook: van a un outbox (`whatsapp_outbound_reply`) que el worker envía como texto libre dentro de la ventana de 24 h. Cada evento de Meta se deduplica (estado por `(mensaje, estado)`, entrante por su id y clínica). Ver C-10.
5. Reintentos con backoff (5 min → 30 min; `REMINDER_BACKOFF_MINUTES=5,30,120`); tras 3 intentos (`REMINDER_MAX_ATTEMPTS`) → `failed` + escalado a email si hay dirección y no hay baja de ese canal (se crea el job de email del mismo paso). La alerta visible a recepción queda para una UI posterior.

### Idempotencia y seguridad del motor
- Clave de idempotencia `(appointment_id, step, channel)` única en DB: el doble-tick no duplica mensajes.
- Eventos de Meta deduplicados por `provider_event_id`.
- Tope de antigüedad: jamás enviar recordatorio de un turno ya iniciado (jobs vencidos de turnos pasados → `skipped`, no `sent`).
- Firma `X-Hub-Signature-256` obligatoria en webhook; sin firma se responde 401 y se registra intento.
- Link de gestión de los mensajes: token **firmado** (HMAC con `MANAGE_LINK_SECRET`), estable por turno y aceptado por `/api/manage/{token}` además del token aleatorio de C-07 (la base solo guarda el hash de ese token y los turnos de recepción no tienen uno).
- Garantía de entrega al menos una vez: si el worker muere entre el envío y el registro del resultado, el lease reenvía el job.

## 4. Costos y transparencia (RN-WA-05)

- Cada job guarda `provider_message_id` y estados; el costo por mensaje (según pricing Meta vigente por categoría/país) se registra o se estima por tabla configurable.
- Reporte mensual por clínica: mensajes enviados/entregados/leídos por paso + costo atribuido. Este reporte es la base del pricing del módulo (incluido con tope vs. costo variable) y debe existir antes de escalar del piloto.
- Alerta configurable: si el costo mensual supera el umbral de la clínica, el admin recibe aviso (no se corta el servicio en v1.0 sin decisión explícita del dueño — ver pregunta abierta de pricing en `10`).

## 5. Riesgos del canal (lectura de arquitecto)

1. **Aprobación de plantillas**: Meta puede rechazar textos; tener los 6 textos + 2 variantes listos antes del piloto y no atar el go-live a la última plantilla (el email cubre).
2. **Ventana 24 h**: fuera de ella solo plantillas — el flujo conversacional (reprogramar por chat libre) debe diseñarse dentro de esa restricción o derivar al link.
3. **Opt-out masivo**: si la cadencia 72/24/3 genera bajas, el canal se erosiona. Medir opt-out por paso desde el día 1 y estar dispuesto a recortar a 24/3 h.
4. **Número compartido vs. propio**: el compartido acelera el piloto pero mezcla reputación y complica portabilidad; el propio es lo correcto a 90 días. Decidir antes del tercer tenant.
