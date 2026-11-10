# Spec Delta — web/waitlist-offer

## Purpose

Página pública y mobile-first donde el paciente ve el hueco que le ofrecen,
cuánto tiempo tiene para tomarlo, y lo acepta o lo rechaza sin cuenta.

## ADDED Requirements

### Requirement: Página de la oferta

La página `/o/:token` SHALL mostrar clínica, profesional, fecha, hora y la hora
local de vencimiento en la zona de la clínica, con los botones "Tomar el turno",
"No me sirve" y "No me sirve y salir de la lista" mientras la oferta está
pendiente y vigente.

#### Scenario: Oferta pendiente

- **WHEN** el paciente abre el link de una oferta vigente
- **THEN** ve el hueco, "Tenés hasta las HH:MM" y los tres botones

#### Scenario: Oferta vencida

- **WHEN** abre el link de una oferta vencida
- **THEN** ve que venció, que sigue en la lista si corresponde y el teléfono de
  la clínica, sin botones de acción

### Requirement: Resultado de la respuesta

Tras aceptar, la página SHALL mostrar el turno confirmado con fecha y hora y su
link de gestión. Tras rechazar, SHALL confirmar que sigue en la lista o que
salió de ella. Cada botón SHALL deshabilitarse mientras la request está en
curso.

#### Scenario: Aceptar

- **WHEN** el paciente toca "Tomar el turno"
- **THEN** ve "Turno confirmado" con fecha, hora y el link para gestionarlo

#### Scenario: Doble toque

- **WHEN** toca "Tomar el turno" dos veces seguidas
- **THEN** se envía una sola request

### Requirement: Errores de la oferta comprensibles

La página SHALL traducir cada error a un mensaje que diga qué pasó y qué hacer:
`409 slot_taken` explica que el hueco se ocupó, que sigue en la lista con
prioridad y muestra los alternativos informados con un acceso a la reserva
online si existe; `409 offer_expired`, `409 patient_busy`, `404
offer_not_found`, `429` y errores de red tienen su propio mensaje.

#### Scenario: Hueco ocupado

- **WHEN** la API responde `409 slot_taken` con dos alternativos
- **THEN** la página muestra el aviso, los dos horarios y el acceso a reservar

#### Scenario: Link inválido

- **WHEN** la API responde `404 offer_not_found`
- **THEN** la página dice que el link no es válido o venció y muestra cómo
  contactar a la clínica si la conoce

### Requirement: Página pública mobile-first y sin almacenamiento

La página SHALL ser usable en 360 px de ancho sin scroll horizontal, con
controles de al menos 44 px y foco visible, SHALL funcionar sin sesión del
personal, enviar sus pedidos sin credenciales y SHALL NOT guardar el token ni
datos del paciente en el navegador.

#### Scenario: Sin almacenamiento

- **WHEN** se abre y se acepta una oferta
- **THEN** `localStorage` y `sessionStorage` no contienen el token ni datos del
  paciente

#### Scenario: Viewport chico

- **WHEN** se abre en 360 px de ancho
- **THEN** no hay scroll horizontal y los botones miden al menos 44 px
