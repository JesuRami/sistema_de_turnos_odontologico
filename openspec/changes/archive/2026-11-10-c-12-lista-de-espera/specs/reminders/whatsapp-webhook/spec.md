# Spec Delta — reminders/whatsapp-webhook

## ADDED Requirements

### Requirement: Respuesta a una oferta de lista de espera

Un mensaje entrante que cita el mensaje de una oferta SHALL asociarse a esa
oferta. El botón "Tomarlo" y los textos "tomarlo", "lo tomo", "sí" y "si"
SHALL interpretarse como aceptar; el botón "Paso" y los textos "paso" y "no"
como rechazar; "stop" y sus variantes conservan su prioridad. Otro texto SHALL
NOT cambiar la oferta.

#### Scenario: Botón Tomarlo

- **WHEN** el paciente toca "Tomarlo" en el mensaje de una oferta vigente
- **THEN** la oferta se acepta con actor de paciente y se crea el turno `waitlist`

#### Scenario: Texto "paso" citando la oferta

- **WHEN** el paciente responde "Paso" citando el mensaje de la oferta
- **THEN** la oferta queda `declined` y la entrada vuelve a `waiting`

#### Scenario: Stop citando la oferta

- **WHEN** el paciente responde "no me escriban más" citando la oferta
- **THEN** se registra el opt-out de WhatsApp y la oferta no cambia

#### Scenario: Texto no reconocido

- **WHEN** el paciente responde "¿con quién era?" citando la oferta
- **THEN** la oferta no cambia

### Requirement: Una respuesta sin contexto nunca acepta una oferta

Un mensaje entrante que no cita el mensaje de una oferta SHALL NOT aceptar ni
rechazar ninguna oferta y SHALL seguir las reglas de enrutamiento al turno.

#### Scenario: "Si" suelto con oferta pendiente

- **WHEN** el paciente tiene una oferta pendiente y un turno vigente y escribe
  "si" sin citar mensaje
- **THEN** la oferta no cambia y se aplica el enrutamiento al turno

### Requirement: Respuestas del sistema a una oferta

Tras procesar la respuesta a una oferta, el sistema SHALL contestar dentro de la
ventana de 24 h con un mensaje libre que diga el resultado: turno confirmado con
fecha, hora y link de gestión; rechazo registrado; hueco ocupado con el aviso de
prioridad; oferta vencida o cerrada; o paciente con otro turno a esa hora.

#### Scenario: Aceptación respondida

- **WHEN** el paciente acepta por botón y se crea el turno
- **THEN** recibe un mensaje con la fecha, la hora y el link de gestión del turno

#### Scenario: Oferta vencida respondida

- **WHEN** el paciente toca "Tomarlo" después del vencimiento
- **THEN** la oferta no cambia y recibe un mensaje de oferta vencida

#### Scenario: Reenvío del mismo botón por Meta

- **WHEN** Meta reenvía el mismo mensaje entrante de aceptación
- **THEN** no se crea un segundo turno ni una segunda respuesta

### Requirement: Registro del entrante de una oferta

El mensaje entrante asociado a una oferta SHALL registrarse con la clínica, el
paciente, la oferta y la intención, sin texto ni teléfono, y SHALL contar para
la ventana de 24 h del paciente.

#### Scenario: Entrante registrado

- **WHEN** el paciente responde a una oferta
- **THEN** existe un registro del entrante con el id de la oferta y la intención,
  sin contenido del mensaje
