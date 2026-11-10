# waitlist/offer-delivery Specification

## Purpose
Hace llegar cada oferta de la lista de espera al paciente por WhatsApp o email
con el motor de envío existente, con sus garantías de idempotencia, reintentos,
consentimiento y costo, y sin enviar ofertas que ya no se pueden tomar.

## Requirements

### Requirement: Un envío por oferta

Crear una oferta SHALL programar, en la misma transacción, un único envío del
paso `waitlist_offer` disponible de inmediato, impuesto por la base por oferta y
canal. Una oferta SHALL NOT generar recordatorios de 72, 24 ni 3 h.

#### Scenario: Envío programado con la oferta

- **WHEN** una cancelación crea una oferta
- **THEN** existe un job `scheduled` del paso `waitlist_offer` para esa oferta con
  `available_at` igual al instante de creación

#### Scenario: Oferta revertida

- **WHEN** la transacción que creaba la oferta revierte
- **THEN** no queda job ni mensaje enviado

### Requirement: Elección del canal

El envío SHALL salir por WhatsApp si el paciente tiene teléfono y opt-in vigente
de WhatsApp; si no, por email si tiene dirección y no se dio de baja. Un fallo
definitivo por WhatsApp SHALL escalar a email con las mismas reglas que un
recordatorio.

#### Scenario: Paciente con opt-in

- **WHEN** el paciente tiene teléfono con opt-in y email
- **THEN** la oferta sale por WhatsApp

#### Scenario: Paciente sin opt-in

- **WHEN** el paciente tiene teléfono sin opt-in y email
- **THEN** la oferta sale por email

#### Scenario: WhatsApp falla tres veces

- **WHEN** el envío por WhatsApp agota sus intentos y el paciente tiene email
- **THEN** el job queda `failed` y se programa el envío por email de la oferta

### Requirement: Validación previa de la oferta

Antes de reclamar y justo antes de enviar, el motor SHALL verificar que la oferta
siga `pending` y sin vencer; si no, el job SHALL quedar `cancelled` con motivo
`offer_closed` sin enviar nada. Las demás validaciones del motor (consentimiento,
destinatario, plantilla activa) SHALL aplicarse igual.

#### Scenario: Oferta aceptada por recepción antes del envío

- **WHEN** recepción acepta la oferta por teléfono antes de que el worker la envíe
- **THEN** el job queda `cancelled` con `offer_closed` y el paciente no recibe el
  mensaje

#### Scenario: Oferta vencida en la cola

- **WHEN** el worker estuvo caído y reclama un envío de una oferta ya vencida
- **THEN** el job queda `cancelled` con `offer_closed`

#### Scenario: Opt-out entre la oferta y el envío

- **WHEN** el paciente se dio de baja de WhatsApp después de crearse la oferta
- **THEN** el job queda `skipped` con `no_consent` y no se envía por WhatsApp

### Requirement: Contenido del mensaje de oferta

El mensaje SHALL usar la plantilla activa del paso `waitlist_offer` del canal,
con nombre de pila, clínica, fecha, hora, profesional, hora local de vencimiento
y el link de la oferta. Por WhatsApp SHALL salir como plantilla con botones de
respuesta "Tomarlo" y "Paso". SHALL NOT incluir el link de gestión de ningún
turno ni datos de otros pacientes.

#### Scenario: Variables completas

- **WHEN** se envía una oferta del jueves 10:00 que vence a las 15:30
- **THEN** el mensaje lleva la fecha, la hora 10:00, el profesional, "15:30" como
  vencimiento y el link `/o/{token}`

#### Scenario: Plantilla inactiva

- **WHEN** la plantilla del paso `waitlist_offer` del canal está inactiva
- **THEN** el job queda `failed` con `template_inactive` y escala a email como un recordatorio

### Requirement: Estados, reintentos y costo de la oferta

El envío de la oferta SHALL registrar `sent`, `delivered`, `read` y `failed` en
`delivery_event`, reintentar con backoff y atribuir su costo a la clínica y al
paso `waitlist_offer`, igual que un recordatorio. Ningún log, evento ni
`last_error` SHALL llevar nombre, teléfono, email ni link.

#### Scenario: Entregado por Meta

- **WHEN** el webhook informa `delivered` del mensaje de la oferta
- **THEN** el job de la oferta avanza a `delivered` y se registra el evento

#### Scenario: Costo registrado

- **WHEN** se envía una oferta por WhatsApp
- **THEN** el job guarda el costo configurado del canal

### Requirement: Los envíos de oferta no se mezclan con los del turno

Los envíos de oferta SHALL NOT aparecer en el timeline de recordatorios ni en la
lista de seguimiento de ningún turno, y el recálculo de recordatorios de un
turno SHALL NOT tocarlos.

#### Scenario: Timeline del turno nuevo

- **WHEN** se abre el timeline del turno creado por la aceptación
- **THEN** muestra sus recordatorios y no el envío de la oferta

#### Scenario: Recálculo de otro turno

- **WHEN** se reprograma un turno del mismo paciente
- **THEN** el envío de la oferta pendiente no cambia
