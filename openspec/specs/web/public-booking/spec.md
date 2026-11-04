# web/public-booking Specification

## Purpose

Define la página pública `/b/:slug` con la que un paciente sin cuenta reserva un
turno desde el celular, en pocos pasos y con mensajes claros ante cada error.

## Requirements

### Requirement: Reserva en cuatro pasos

La página `/b/:slug` SHALL guiar la reserva en a lo sumo cuatro pasos —
profesional, día, hora, datos — y SHALL permitir volver al paso anterior sin
perder lo elegido. Con un solo profesional reservable SHALL saltear el primer
paso.

#### Scenario: Flujo completo

- **WHEN** un paciente abre `/b/clinica-demo`, elige profesional, día, hora y completa sus datos ficticios
- **THEN** llega a la pantalla de confirmación habiendo pasado por cuatro pasos como máximo

#### Scenario: Un solo profesional

- **WHEN** la clínica tiene un único profesional reservable
- **THEN** la página arranca en la elección de día

#### Scenario: Volver atrás

- **WHEN** el paciente está en el paso de datos y vuelve al paso de hora
- **THEN** sigue viendo el profesional y el día elegidos

### Requirement: Diseño mobile-first y accesible

La página SHALL ser usable en un viewport de 360 px de ancho sin scroll
horizontal, con controles táctiles de al menos 44 px, foco de teclado visible,
etiquetas en todos los campos y horarios en la zona de la clínica.

#### Scenario: Celular angosto

- **WHEN** se abre la página en un viewport de 360×740
- **THEN** no hay scroll horizontal y cada horario es un botón de al menos 44 px de alto

#### Scenario: Navegación por teclado

- **WHEN** se recorre el formulario con Tab
- **THEN** cada control recibe foco visible y tiene nombre accesible

#### Scenario: Horario en la zona de la clínica

- **WHEN** el navegador está en otra zona horaria
- **THEN** los horarios se muestran en la zona horaria de la clínica

### Requirement: Datos del paciente con consentimientos explícitos

El paso de datos SHALL pedir nombre, teléfono y/o email, una casilla de opt-in de
WhatsApp sin marcar por defecto visible cuando hay teléfono, y la aceptación de
la política de privacidad; SHALL impedir enviar sin nombre, sin contacto o sin
aceptar la privacidad.

#### Scenario: Casilla de WhatsApp sin marcar

- **WHEN** el paciente escribe un teléfono
- **THEN** aparece la casilla de opt-in de WhatsApp sin marcar

#### Scenario: Envío sin contacto bloqueado

- **WHEN** el paciente intenta confirmar sin teléfono ni email
- **THEN** el formulario indica que falta un contacto y no envía la reserva

### Requirement: Confirmación con link de gestión

Tras una reserva exitosa la página SHALL mostrar profesional, fecha y hora en la
zona de la clínica, el estado pendiente de confirmación, el canal de
recordatorios y el link de gestión para guardar, y SHALL mostrar el aviso de
canal email cuando la API lo indique.

#### Scenario: Confirmación por WhatsApp

- **WHEN** la API responde 201 con `channel=whatsapp`
- **THEN** la pantalla muestra el turno, indica que los recordatorios llegarán por WhatsApp y ofrece el link de gestión

#### Scenario: Aviso de canal email

- **WHEN** la API responde 201 con el aviso `phone_invalid_email_channel`
- **THEN** la pantalla explica que el teléfono no sirve para WhatsApp y que los avisos llegarán por email

### Requirement: Errores de la reserva comprensibles

La página SHALL traducir cada error de la API a un mensaje que diga qué pasó y
qué hacer: `409 slot_taken` ofrece los alternativos como botones, `422` marca el
campo afectado, `429` indica cuándo reintentar, `404` informa que la reserva no
está disponible y `503` invita a reintentar más tarde.

#### Scenario: Hueco tomado mientras completaba los datos

- **WHEN** la API responde `409 slot_taken` con alternativos
- **THEN** la página muestra "Ese horario se acaba de ocupar", lista los alternativos y elegir uno conserva los datos cargados

#### Scenario: Demasiados intentos

- **WHEN** la API responde `429` con `Retry-After: 600`
- **THEN** la página indica que se puede reintentar en 10 minutos

#### Scenario: Link inexistente

- **WHEN** se abre `/b/slug-que-no-existe`
- **THEN** la página informa que la reserva online no está disponible para ese link

### Requirement: Página pública sin sesión ni almacenamiento del token

La página SHALL funcionar sin sesión del personal, SHALL enviar sus pedidos sin
credenciales y SHALL NOT guardar el token de gestión ni los datos del paciente en
almacenamiento del navegador.

#### Scenario: Sin credenciales

- **WHEN** la página consulta la API pública
- **THEN** los pedidos no llevan cookies ni cabecera de autorización

#### Scenario: Nada persiste en el navegador

- **WHEN** termina una reserva
- **THEN** `localStorage` y `sessionStorage` no contienen el token ni datos del paciente
