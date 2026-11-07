# Spec Delta — web/agenda-board

## ADDED Requirements

### Requirement: Timeline de recordatorios en el detalle del turno

El detalle del turno en la agenda SHALL mostrar, para admin, recepción y
odontólogo, el timeline de recordatorios por paso y canal con su estado
efectivo, fechas, intentos, último error y eventos. El odontólogo SHOULD verlo
solo en sus propios turnos y sin botones de acción. Un error de la API SHALL
mostrarse con un mensaje en español sin datos personales.

#### Scenario: Recepción abre un turno con recordatorios

- **WHEN** recepción abre el detalle de un turno con los pasos de 72 h, 24 h y
  3 h
- **THEN** ve cada paso con su estado, la hora programada y sus eventos

#### Scenario: Odontólogo abre su turno

- **WHEN** un odontólogo abre el detalle de un turno propio
- **THEN** ve el timeline sin el botón "Reenviar" ni el de confirmar

#### Scenario: Error al cargar el timeline

- **WHEN** la API del timeline responde un error
- **THEN** el detalle muestra un mensaje claro y conserva el resto de los datos
  del turno

### Requirement: Reenvío manual desde el detalle

Admin y recepción SHALL poder reenviar un paso accionable desde el timeline. El
botón SHALL deshabilitarse mientras la request está en curso y SHALL respetar
`can_resend` y `resend_blocked_reason` que devuelve la API. Un `202` SHALL
mostrar "Reenvío en cola" y refrescar el timeline; un `409` SHALL mostrar el
motivo (`resend_cooldown`, `resend_limit`, `no_consent`, etc.) sin perder el
estado del turno.

#### Scenario: Reenvío aceptado

- **WHEN** recepción reenvía el paso de 24 h y la API responde `202`
- **THEN** la SPA muestra "Reenvío en cola" y el paso pasa a `scheduled`

#### Scenario: Reenvío en cooldown

- **WHEN** recepción hace doble clic y la API responde `409 resend_cooldown`
- **THEN** la SPA muestra cuántos segundos faltan y no repite la request

#### Scenario: Paso no accionable

- **WHEN** un paso está `scheduled` para más adelante o el paciente no tiene
  opt-in
- **THEN** el botón "Reenviar" no se muestra o aparece deshabilitado con el
  motivo

### Requirement: Panel de seguimiento en la agenda

La agenda del día SHALL mostrar a admin y recepción un panel con la cantidad de
turnos "sin confirmar" y con "fallos de envío", y un control para filtrar la
grilla por esos turnos. El odontólogo SHALL NOT ver el panel ni el control. El
panel SHALL actualizarse con el mismo refresco periódico de la agenda.

#### Scenario: Panel con turnos pendientes

- **WHEN** recepción abre la agenda del día con 3 turnos sin confirmar y 1 con
  fallo de envío
- **THEN** el panel muestra 3 y 1, y el filtro deja solo esos turnos en la grilla

#### Scenario: Sin turnos para llamar

- **WHEN** no hay turnos sin confirmar ni fallos en el rango
- **THEN** el panel muestra 0 y el filtro no cambia la grilla

#### Scenario: Odontólogo en la agenda

- **WHEN** un odontólogo abre la agenda
- **THEN** no ve el panel de seguimiento ni el control de filtro

### Requirement: Confirmación manual desde el detalle

El detalle SHALL mantener el botón "Confirmar" para admin y recepción sobre un
turno `pending` no iniciado, usando la transición existente. Al confirmar, la
grilla SHALL refrescar el turno y el timeline SHALL reflejar el estado
`confirmed` sin duplicar el evento de auditoría.

#### Scenario: Confirmar desde el detalle

- **WHEN** recepción confirma un turno `pending` desde el detalle
- **THEN** el turno pasa a `confirmed` en la grilla y el timeline deja de
  marcarlo como pendiente de confirmar

#### Scenario: Odontólogo no confirma

- **WHEN** un odontólogo abre un turno `pending` propio
- **THEN** no ve el botón "Confirmar"
