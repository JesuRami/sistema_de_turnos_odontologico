# waitlist/offer-link Specification

## Purpose
Permite que el paciente vea, acepte o rechace una oferta de la lista de espera
sin cuenta, con un link firmado de una sola oferta, acotado a su clínica y sin
exponer datos de otros pacientes.

## Requirements

### Requirement: Credencial firmada de la oferta

El link de una oferta SHALL llevar una credencial firmada con un secreto del
servidor que identifica solo esa oferta, sin estado en la base, con un contexto
de firma distinto del link de gestión del turno: una credencial de oferta SHALL
NOT servir como link de gestión ni al revés. Cualquier credencial inválida,
alterada o de una oferta inexistente SHALL responder `404 offer_not_found` con
el mismo cuerpo.

#### Scenario: Credencial alterada

- **WHEN** se cambia un carácter de la credencial
- **THEN** responde `404 offer_not_found`

#### Scenario: Link de gestión usado como oferta

- **WHEN** se usa el token firmado de gestión de un turno en `/api/waitlist-offer/{token}`
- **THEN** responde `404 offer_not_found`

#### Scenario: Secreto sin configurar

- **WHEN** el secreto de los links firmados está vacío
- **THEN** no se arma ningún link de oferta y el envío falla con un código de
  configuración, sin enviar un link inválido

### Requirement: Vista de la oferta

`GET /api/waitlist-offer/{token}` SHALL devolver nombre y teléfono de contacto de
la clínica, su zona horaria, el nombre de pila del paciente, profesional, fecha,
hora de inicio y fin, `expires_at` y el estado de la oferta. SHALL NOT devolver
ids internos del paciente, teléfono, email ni datos de otros pacientes.

#### Scenario: Oferta pendiente

- **WHEN** el paciente abre el link de una oferta pendiente
- **THEN** ve el hueco, el vencimiento y el estado `pending`

#### Scenario: Oferta ya resuelta

- **WHEN** abre el link de una oferta `accepted`
- **THEN** ve el estado `accepted` y el horario de su turno

#### Scenario: Oferta vencida al abrir

- **WHEN** abre el link después de `expires_at` y antes del tick
- **THEN** la vista informa `expired`

### Requirement: Aceptar y rechazar por link

`POST /api/waitlist-offer/{token}/accept` y `POST
/api/waitlist-offer/{token}/decline` (con `leave_list` opcional) SHALL aplicar
las reglas de aceptación y rechazo de la oferta con actor de tipo paciente y
SHALL devolver la vista actualizada. Los cuerpos SHALL rechazar campos
desconocidos.

#### Scenario: Aceptar por link

- **WHEN** el paciente acepta por el link una oferta vigente
- **THEN** responde `200` con la vista `accepted`, fecha y hora del turno nuevo y
  su link de gestión

#### Scenario: Campo desconocido

- **WHEN** el cuerpo del rechazo trae un campo no previsto
- **THEN** responde `422` y la oferta no cambia

### Requirement: Validez del link

El link SHALL servir para ver la oferta hasta 72 h después del fin del hueco
ofrecido; después SHALL responder `404 offer_not_found`. Aceptar o rechazar
SHALL depender solo del estado y del vencimiento de la oferta.

#### Scenario: Link viejo

- **WHEN** se abre el link 4 días después del hueco ofrecido
- **THEN** responde `404 offer_not_found`

### Requirement: Rate-limit del link de oferta

Las lecturas y las acciones SHALL limitarse por hash de la credencial y por IP,
con `429 rate_limited` y `Retry-After` al excederse, sin mutar nada, y `503` si
el almacenamiento del cupo no está disponible.

#### Scenario: Muchas aceptaciones

- **WHEN** una IP supera el cupo de acciones
- **THEN** responde `429 rate_limited` y la oferta no cambia

### Requirement: Respuestas sin rastro del token

Las respuestas del link SHALL llevar `Cache-Control: no-store` y
`Referrer-Policy: no-referrer`. La credencial SHALL NOT aparecer en logs, en
eventos ni en cuerpos de error.

#### Scenario: Cabeceras de la vista

- **WHEN** se pide la vista de una oferta
- **THEN** la respuesta lleva `Cache-Control: no-store` y `Referrer-Policy: no-referrer`

#### Scenario: Log de una aceptación

- **WHEN** se acepta una oferta por link
- **THEN** ningún log ni evento contiene la credencial ni el teléfono del paciente

### Requirement: Aislamiento del link

Todo lo resuelto con una credencial de oferta SHALL limitarse a la clínica de esa
oferta: la vista, el turno creado y los alternativos.

#### Scenario: Alternativos de la misma clínica

- **WHEN** una aceptación pierde la carrera
- **THEN** los alternativos son solo del mismo profesional en la misma clínica
