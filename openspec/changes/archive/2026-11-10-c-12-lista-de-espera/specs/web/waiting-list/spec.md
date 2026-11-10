# Spec Delta — web/waiting-list

## Purpose

Da a recepción una pantalla para ver la cola de la lista de espera, anotar y
retirar pacientes, ofrecer huecos a mano, priorizar con motivo y seguir las
ofertas pendientes y vencidas del día.

## ADDED Requirements

### Requirement: Página de la lista de espera

La SPA SHALL ofrecer `/lista-de-espera` a admin, recepción y odontólogo, con la
cola ordenada como la devuelve la API, filtros por profesional, estado y
período, y paginación incremental ("Cargar más"). Cada fila SHALL mostrar
paciente, profesional o "Cualquiera", período, franja, días, antigüedad, marca
de prioridad con su motivo y la oferta pendiente con su vencimiento.

#### Scenario: Recepción abre la cola

- **WHEN** recepción abre `/lista-de-espera`
- **THEN** ve las entradas `waiting` y `offered` en el orden de la API con sus
  filtros

#### Scenario: Cola vacía

- **WHEN** no hay entradas que cumplan los filtros
- **THEN** la página muestra un mensaje de vacío y cómo anotar a alguien

#### Scenario: Error de red

- **WHEN** la API no responde
- **THEN** la página muestra qué pasó y un botón para reintentar

### Requirement: Alta y edición desde el panel

Admin y recepción SHALL anotar a un paciente buscándolo por nombre o teléfono y
eligiendo profesional o "Cualquiera", período, franja y días opcionales y nota,
y SHALL editar o retirar una entrada. Ante `409 already_waiting` la SPA SHALL
ofrecer abrir la entrada existente.

#### Scenario: Anotar a un paciente

- **WHEN** recepción completa el formulario con datos válidos
- **THEN** la entrada aparece en la cola sin recargar la página

#### Scenario: Duplicado

- **WHEN** la API responde `409 already_waiting`
- **THEN** la SPA explica que ya está anotado y ofrece ir a esa entrada

#### Scenario: Retirar con confirmación

- **WHEN** recepción retira una entrada
- **THEN** la SPA pide confirmación y, al confirmar, la entrada sale de la cola

### Requirement: Oferta manual y prioridad desde el panel

Admin y recepción SHALL ofrecer un hueco a una entrada eligiendo profesional,
sillón, día y hora entre los horarios libres, y SHALL priorizar o quitar la
prioridad con un motivo. Ante `422 fifo_skip_reason_required` la SPA SHALL pedir
el motivo de excepción a FIFO y reintentar con él.

#### Scenario: Ofrecer saltando la cola

- **WHEN** recepción ofrece un hueco a una entrada que no es la primera
  compatible
- **THEN** la SPA pide el motivo y, al confirmarlo, la oferta queda pendiente

#### Scenario: Priorizar

- **WHEN** recepción prioriza con motivo
- **THEN** la entrada sube al principio y muestra la marca y el motivo

### Requirement: Seguimiento de ofertas

El panel SHALL mostrar a admin y recepción las ofertas pendientes con el tiempo
restante y las vencidas, rechazadas y cerradas del día, y SHALL permitir aceptar
o rechazar en nombre del paciente y retirar una oferta pendiente. Los datos
SHALL refrescarse como máximo cada 30 segundos mientras la pestaña está visible.

#### Scenario: Aceptar por teléfono

- **WHEN** recepción acepta una oferta en nombre del paciente
- **THEN** la SPA muestra el turno creado con su fecha y hora y un acceso a la
  agenda de ese día

#### Scenario: Hueco ocupado al aceptar

- **WHEN** la API responde `409 slot_taken`
- **THEN** la SPA explica que el hueco se ocupó y que la entrada quedó prioritaria

#### Scenario: Oferta vence en pantalla

- **WHEN** pasa el vencimiento de una oferta con la página abierta
- **THEN** tras el refresco la oferta figura como vencida

### Requirement: Vista del odontólogo

El odontólogo SHALL ver la cola de su profesional y de "Cualquiera" sin
teléfono, email ni notas y SHALL NOT ver los controles de alta, edición, retiro,
oferta, prioridad ni respuesta.

#### Scenario: Odontólogo sin acciones

- **WHEN** un odontólogo abre `/lista-de-espera`
- **THEN** ve las entradas sin datos de contacto ni botones de acción

### Requirement: Mensajes de error de la lista

Cada `detail` de la API de la lista SHALL mostrarse con un mensaje en español
que diga qué pasó y qué hacer; un `detail` desconocido SHALL mostrar un mensaje
genérico. Ningún mensaje SHALL incluir datos del paciente.

#### Scenario: Entrada ofrecida no editable

- **WHEN** la API responde `409 entry_offered` al editar
- **THEN** la SPA explica que tiene una oferta pendiente y que primero hay que
  esperar la respuesta o retirarla
