# Spec Delta — reminders/whatsapp-webhook

## Purpose

Recibe los eventos de la Cloud API de Meta (estados de entrega y respuestas del
paciente) de forma autenticada e idempotente, y los convierte en cambios de
estado de los recordatorios, del turno y del consentimiento.

## ADDED Requirements

### Requirement: Verificación de suscripción

`GET /webhooks/whatsapp` SHALL responder 200 con el `hub.challenge` recibido
solo si `hub.mode` es `subscribe` y `hub.verify_token` coincide con el token de
verificación configurado; en cualquier otro caso SHALL responder 403.

#### Scenario: Handshake válido

- **WHEN** Meta llama con `hub.mode=subscribe`, el token correcto y un challenge
- **THEN** responde 200 con el challenge como texto plano

#### Scenario: Token incorrecto

- **WHEN** se llama con un token de verificación distinto
- **THEN** responde 403 sin eco del challenge

### Requirement: Firma obligatoria

`POST /webhooks/whatsapp` SHALL verificar `X-Hub-Signature-256` como HMAC-SHA256
del cuerpo crudo con el secreto de la app, en tiempo constante, antes de
interpretar el cuerpo. Sin firma o con firma inválida SHALL responder 401, no
procesar nada y registrar el intento sin PII.

#### Scenario: Sin firma

- **WHEN** llega un POST sin `X-Hub-Signature-256`
- **THEN** responde 401, no cambia ningún dato y queda un registro del intento
  sin teléfono ni contenido

#### Scenario: Cuerpo alterado

- **WHEN** llega un POST cuya firma no corresponde al cuerpo
- **THEN** responde 401 y no cambia ningún dato

#### Scenario: Firma válida

- **WHEN** llega un POST correctamente firmado
- **THEN** responde 200 y procesa sus eventos

### Requirement: Tolerancia a campos nuevos de Meta

Un payload firmado SHALL aceptarse aunque traiga campos que el sistema no
conoce, ignorándolos. Un payload firmado sin la estructura mínima o con tipos
de evento desconocidos SHALL responder 200 sin cambiar datos y dejar registro
sin PII, para que Meta no lo reintente.

#### Scenario: Campo nuevo

- **WHEN** llega un estado `delivered` firmado con un campo extra desconocido
- **THEN** el estado se procesa normalmente

#### Scenario: Evento desconocido

- **WHEN** llega un payload firmado con un tipo de cambio que el sistema no maneja
- **THEN** responde 200 y no cambia ningún dato

### Requirement: Deduplicación de eventos

Cada evento de Meta SHALL procesarse a lo sumo una vez: un estado por
`(id de mensaje, estado)` y un mensaje entrante por su id. Un reenvío del mismo
evento SHALL responder 200 sin efectos.

#### Scenario: Estado repetido

- **WHEN** Meta envía dos veces el mismo `delivered` de un mensaje
- **THEN** existe un solo evento `delivered` para ese job

#### Scenario: Respuesta repetida

- **WHEN** Meta reenvía la misma respuesta "SÍ" del paciente
- **THEN** el turno se confirma una vez y el reenvío no agrega eventos de turno

### Requirement: Estados de entrega monótonos

Los estados `delivered` y `read` de un mensaje enviado SHALL registrarse en
`delivery_event` y avanzar el job en el orden `sent → delivered → read`, sin
retroceder. Un estado de un mensaje desconocido SHALL ignorarse.

#### Scenario: Entregado y leído

- **WHEN** llegan `delivered` y luego `read` de un job `sent`
- **THEN** el job queda `read` con un evento por cada estado

#### Scenario: Llegan desordenados

- **WHEN** llega `read` y después `delivered` del mismo mensaje
- **THEN** el job queda `read` y ambos eventos quedan registrados

#### Scenario: Mensaje ajeno

- **WHEN** llega un estado de un id de mensaje que no corresponde a ningún job
- **THEN** responde 200 sin cambiar datos

### Requirement: Falla informada por Meta

Un estado `failed` de un mensaje ya aceptado SHALL dejar el job `failed` con un
código estable sin PII y SHALL escalar a email con las mismas reglas que una
falla de envío.

#### Scenario: Falla después de aceptado

- **WHEN** llega `failed` de un job `sent` de un paciente con email sin baja
- **THEN** el job queda `failed` y existe el job de email del mismo paso

#### Scenario: Falla tardía de un mensaje ya entregado

- **WHEN** llega `failed` de un job que ya está `delivered`
- **THEN** el evento se registra y el job no cambia de estado

### Requirement: Interpretación de la respuesta del paciente

Un mensaje entrante SHALL clasificarse en una intención: `confirm` (botón
confirmar, "sí", "si", "confirmo"), `change` (botón cambiar o cancelar, "no",
"reprogramar", "cambiar", "cancelar"), `stop` ("stop", "baja", "no me escriban",
"no quiero más") o `unknown`, sin distinguir mayúsculas, tildes ni signos.

#### Scenario: Variantes de sí

- **WHEN** el paciente escribe "Sí!", "si" o "SI" o toca el botón de confirmar
- **THEN** la intención es `confirm`

#### Scenario: Baja tiene prioridad

- **WHEN** el paciente escribe "no me escriban más"
- **THEN** la intención es `stop`, no `change`

#### Scenario: Texto no reconocido

- **WHEN** el paciente escribe "a qué hora era?"
- **THEN** la intención es `unknown`

### Requirement: Enrutamiento al turno

Una respuesta SHALL asociarse al turno del mensaje que responde. Sin ese
contexto, SHALL asociarse al único turno `pending` o `confirmed` futuro de un
paciente con ese teléfono entre las clínicas que usan el número que recibió el
mensaje; con cero o más de un candidato SHALL NOT modificar ningún turno.

#### Scenario: Respuesta a un recordatorio

- **WHEN** el paciente responde "SÍ" citando el recordatorio de 24 h
- **THEN** se confirma el turno de ese recordatorio

#### Scenario: Sin contexto y un solo turno

- **WHEN** el paciente escribe "si" sin citar mensaje y tiene un único turno
  futuro vigente entre las clínicas de ese número
- **THEN** se confirma ese turno

#### Scenario: Sin contexto y ambiguo

- **WHEN** el teléfono tiene turnos futuros en dos clínicas que comparten número
  y escribe "si" sin citar mensaje
- **THEN** ningún turno cambia y el paciente recibe una respuesta que lo deriva a
  su link de gestión

#### Scenario: Aislamiento entre clínicas

- **WHEN** un paciente responde citando un mensaje de la clínica A
- **THEN** no se lee ni se modifica ningún dato de la clínica B

### Requirement: SÍ confirma el turno

La intención `confirm` sobre un turno `pending` futuro SHALL ejecutar la misma
transición que el link de gestión (`pending → confirmed`, actor de paciente,
fuente `whatsapp`) en una sola transacción, con su evento de auditoría y la
reconciliación de recordatorios. Sobre un turno ya confirmado SHALL ser un no-op
auditado.

#### Scenario: Confirmación por WhatsApp

- **WHEN** el paciente responde "SÍ" a un turno online `pending`
- **THEN** el turno queda `confirmed`, existe un evento `confirmed` con fuente
  `whatsapp` y los jobs de 72 h y 24 h pendientes quedan `cancelled`

#### Scenario: Ya confirmado

- **WHEN** el paciente responde "SÍ" a un turno ya `confirmed`
- **THEN** el estado no cambia y queda un evento de no-op auditado

#### Scenario: Turno ya iniciado o cancelado

- **WHEN** el paciente responde "SÍ" a un turno cancelado o que ya empezó
- **THEN** el turno no cambia y el paciente recibe un mensaje que lo deriva a la
  clínica

### Requirement: NO o cambiar deriva sin cancelar

La intención `change` SHALL NOT cambiar el turno. SHALL responder con el link de
gestión del turno si la ventana de cancelación sigue abierta, o con el teléfono
de contacto de la clínica si cerró.

#### Scenario: Dentro de la ventana

- **WHEN** el paciente responde "NO" 48 h antes de un turno con ventana de 24 h
- **THEN** el turno no cambia y recibe un mensaje con su link de gestión

#### Scenario: Fuera de la ventana

- **WHEN** el paciente responde "NO" 3 h antes de un turno con ventana de 24 h
- **THEN** el turno no cambia y recibe un mensaje con el teléfono de la clínica

### Requirement: STOP da de baja el canal

La intención `stop` SHALL registrar un opt-out de WhatsApp con fuente
`whatsapp_reply` en cada paciente con ese teléfono entre las clínicas del número
receptor (o del turno citado), con efecto inmediato sobre sus jobs pendientes, y
SHALL enviar una única confirmación de la baja.

#### Scenario: Baja con contexto

- **WHEN** el paciente responde "BAJA" citando un recordatorio
- **THEN** queda `whatsapp_opt_in=false` con un consentimiento `opt_out` de
  fuente `whatsapp_reply`, sus jobs de WhatsApp pendientes quedan `skipped` y
  recibe una confirmación

#### Scenario: Baja ambigua

- **WHEN** el teléfono tiene fichas en dos clínicas que comparten número y
  escribe "STOP" sin citar mensaje
- **THEN** ambas fichas quedan con opt-out

#### Scenario: Baja repetida

- **WHEN** el paciente ya dado de baja vuelve a escribir "STOP"
- **THEN** no se agrega consentimiento y no se envía otra confirmación

### Requirement: Respuestas solo dentro de la ventana de 24 h

Toda respuesta del sistema a un mensaje entrante SHALL enviarse como mensaje
libre solo dentro de las 24 h posteriores a ese mensaje; vencida la ventana,
SHALL descartarse sin enviar. Las respuestas SHALL enviarse fuera de la request
del webhook, con reintentos.

#### Scenario: Respuesta a tiempo

- **WHEN** el paciente escribe "NO" y el worker procesa la respuesta 1 minuto
  después
- **THEN** la respuesta se envía como mensaje libre

#### Scenario: Ventana vencida

- **WHEN** una respuesta pendiente no pudo enviarse en 24 h
- **THEN** queda descartada con un motivo y no se envía

#### Scenario: Paciente dado de baja

- **WHEN** el paciente escribió "SI" y antes de enviarle la respuesta se dio de baja
- **THEN** la respuesta de confirmación no se envía; solo la confirmación de baja

### Requirement: Registro de mensajes entrantes sin contenido

Cada mensaje entrante procesado SHALL registrarse con clínica, intención, id del
proveedor, instante y, si se resolvieron, paciente y turno; SHALL NOT guardarse
el texto ni el teléfono en claro. Los mensajes que no se asocian a ninguna
clínica SHALL contarse sin persistir datos del remitente.

#### Scenario: Texto libre del paciente

- **WHEN** el paciente escribe un texto con su DNI
- **THEN** el registro guarda la intención `unknown` y no el texto

#### Scenario: Remitente desconocido

- **WHEN** escribe un número que no corresponde a ningún paciente
- **THEN** responde 200, no se crea ningún registro con su teléfono y aumenta un
  contador de no enrutados
