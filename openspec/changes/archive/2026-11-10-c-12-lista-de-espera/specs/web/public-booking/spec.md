# Spec Delta — web/public-booking

## ADDED Requirements

### Requirement: Anotarse en la lista de espera desde la reserva

Cuando el profesional elegido no tiene un horario que le sirva al paciente, la
página `/b/:slug` SHALL ofrecer "Anotarme en la lista de espera" desde los pasos
de día y hora, con profesional elegido o "Cualquiera", período de fechas y franja
y días opcionales, y los mismos datos y consentimientos del paso de datos de la
reserva.

#### Scenario: Sin horarios en el rango

- **WHEN** el profesional no tiene huecos en los días mostrados
- **THEN** la página ofrece anotarse en la lista de espera con ese profesional
  preseleccionado

#### Scenario: Anotación exitosa

- **WHEN** el paciente completa la anotación con datos ficticios válidos
- **THEN** ve el resumen de su anotación y que le avisarán por el canal elegido
  si se libera un hueco, con su vencimiento visible en la oferta

#### Scenario: Ya anotado

- **WHEN** la API responde `409 already_waiting`
- **THEN** la página explica que ya está en la lista y muestra el teléfono de la
  clínica para cambiar algo

#### Scenario: Errores de cupo

- **WHEN** la API responde `429 rate_limited`
- **THEN** la página explica que espere y reintente, sin perder lo cargado

#### Scenario: Sin almacenamiento de datos

- **WHEN** se completa la anotación
- **THEN** el navegador no guarda datos del paciente en `localStorage` ni
  `sessionStorage`
