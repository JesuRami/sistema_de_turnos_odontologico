# Spec Delta — web/agenda-board

## Purpose

Define la agenda operativa del personal en la SPA: cómo se ven los turnos del
día y de la semana, cómo se crean, mueven, cancelan y marcan, y cómo se
resuelven los pacientes duplicados, siempre con la API como única autoridad.

## ADDED Requirements

### Requirement: Vista día y semana en la zona de la clínica

La agenda SHALL abrir en la vista día de hoy, con una columna por sillón activo,
y SHALL ofrecer la vista semana. Horarios y días SHALL mostrarse en la zona
horaria de la clínica, no en la del navegador.

#### Scenario: Apertura por defecto

- **WHEN** recepción abre la agenda
- **THEN** ve el día de hoy de la clínica con una columna por sillón activo

#### Scenario: Navegador en otra zona horaria

- **WHEN** la clínica es de Buenos Aires, el navegador está en UTC y hay un turno a las 10:00 locales
- **THEN** el turno se dibuja a las 10:00

#### Scenario: Vista semana

- **WHEN** recepción cambia a la vista semana
- **THEN** ve los siete días de la semana de la clínica con sus turnos

### Requirement: Filtros y distintivos visuales

La agenda SHALL filtrar por profesional, sillón y estado. Cada turno SHALL
llevar el color de su profesional, un distintivo de estado y uno de
sobreturno; los bloqueos SHALL dibujarse como franjas no reservables. Los
turnos `pending` que empiezan en menos de 24 h SHALL destacarse.

#### Scenario: Filtro por profesional

- **WHEN** recepción filtra por una profesional ficticia
- **THEN** solo ve los turnos de esa profesional

#### Scenario: Sobreturno y bloqueo visibles

- **WHEN** en el día hay un sobreturno y un bloqueo de mantenimiento
- **THEN** el sobreturno lleva su distintivo y el bloqueo se ve como franja no reservable

#### Scenario: Pendiente próximo destacado

- **WHEN** un turno `pending` empieza en 5 horas
- **THEN** aparece destacado como pendiente sin confirmar

### Requirement: Rendimiento de la semana

La vista semana con 500 turnos SHALL quedar visible en menos de 2 segundos
desde que se pide, contra la API real.

#### Scenario: Semana cargada

- **WHEN** la clínica tiene 500 turnos en la semana y recepción abre la vista semana
- **THEN** los turnos están visibles en menos de 2 segundos

### Requirement: Crear turno buscando o dando de alta al paciente

Admin y recepción SHALL crear un turno eligiendo un hueco de la grilla o
indicando profesional, sillón y hora, y buscando al paciente por nombre o
teléfono; si no existe, SHALL poder darlo de alta con nombre y un contacto sin
salir del formulario.

#### Scenario: Turno para un paciente existente

- **WHEN** recepción busca "ana prueba", elige a la paciente ficticia y confirma un hueco libre
- **THEN** el turno aparece en la grilla como confirmado

#### Scenario: Alta rápida dentro del formulario

- **WHEN** la búsqueda no encuentra al paciente y recepción carga nombre y teléfono ficticios
- **THEN** el paciente se crea y queda seleccionado para el turno

#### Scenario: Duplicado detectado en el alta

- **WHEN** el alta responde `409 patient_duplicate`
- **THEN** la SPA ofrece usar el paciente existente

### Requirement: Colisión con alternativos o sobreturno explícito

Ante `409 slot_taken`, la SPA SHALL mostrar los horarios alternativos que
devuelve la API para elegir uno y, solo a admin y recepción, la opción de
crear un sobreturno indicando el motivo. SHALL NOT mostrar datos de los turnos
en conflicto más allá de su horario.

#### Scenario: Elegir un alternativo

- **WHEN** el hueco está ocupado y recepción elige el primer alternativo
- **THEN** el turno se crea en ese horario

#### Scenario: Sobreturno con motivo

- **WHEN** recepción elige sobreturno y escribe un motivo
- **THEN** el turno se crea marcado como sobreturno

#### Scenario: Tope de sobreturnos

- **WHEN** la API responde `409 overbooking_limit`
- **THEN** la SPA informa que se alcanzó el tope diario y que solo un admin puede excederlo

### Requirement: Reprogramar, cancelar y confirmar

Admin y recepción SHALL reprogramar un turno a otro horario, sillón o
profesional, cancelarlo con un motivo del catálogo y nota opcional, y
confirmar un turno pendiente. Si la API rechaza la operación, la grilla SHALL
seguir mostrando el turno como estaba.

#### Scenario: Reprogramación exitosa

- **WHEN** recepción mueve un turno de las 10:00 a las 11:00
- **THEN** la grilla lo muestra a las 11:00

#### Scenario: Reprogramación rechazada

- **WHEN** la API responde `409 slot_taken` a una reprogramación
- **THEN** la SPA muestra los alternativos y el turno sigue a las 10:00

#### Scenario: Cancelación sin motivo

- **WHEN** recepción intenta cancelar sin elegir motivo
- **THEN** la SPA no envía la operación y pide el motivo

### Requirement: Asistencia del día

La SPA SHALL ofrecer marcar presente en los turnos confirmados del día, y
ausente o no-show desde la hora de inicio, explicando la diferencia: ausente
avisó, no-show no avisó. Los turnos futuros SHALL NOT ofrecer esas acciones.

#### Scenario: Paciente llega

- **WHEN** recepción marca presente un turno confirmado de hoy
- **THEN** el turno pasa a presente en la grilla

#### Scenario: Turno de mañana

- **WHEN** recepción abre un turno de mañana
- **THEN** no ve las acciones de presente, ausente ni no-show

### Requirement: Vista restringida del odontólogo

El odontólogo SHALL ver solo sus turnos, sin teléfono ni email del paciente, y
solo SHALL ver las acciones de asistencia sobre ellos. SHALL NOT ver los
controles de crear, reprogramar, cancelar, confirmar ni fusionar.

#### Scenario: Agenda del odontólogo

- **WHEN** un odontólogo ficticio abre la agenda del día
- **THEN** ve solo sus turnos, sin datos de contacto y sin botón de nuevo turno

### Requirement: Errores de dominio comprensibles

Cada error de la API SHALL mostrarse con un mensaje en español asociado a su
`detail`; un `detail` desconocido SHALL mostrar un mensaje genérico. Los
mensajes SHALL NOT incluir datos personales del paciente.

#### Scenario: Turno fuera de horario

- **WHEN** la API responde `422 outside_schedule`
- **THEN** la SPA muestra "El horario está fuera de la atención del profesional"

#### Scenario: Error desconocido

- **WHEN** la API responde un `detail` que la SPA no conoce
- **THEN** la SPA muestra "No se pudo completar la operación" sin datos del paciente

### Requirement: Fusión asistida de pacientes duplicados

Admin y recepción SHALL fusionar dos fichas del mismo paciente desde la SPA:
elegir cuál se conserva, ver ambas fichas y la cantidad de turnos que se
mueven, y confirmar. La SPA SHALL advertir que la operación no se deshace.

#### Scenario: Fusión confirmada

- **WHEN** recepción fusiona una ficha duplicada con 2 turnos en la que se conserva
- **THEN** la SPA informa 2 turnos movidos y la ficha duplicada deja de aparecer en la búsqueda

#### Scenario: Fusión rechazada

- **WHEN** la API responde `422` porque una de las fichas ya está archivada
- **THEN** la SPA muestra el motivo y no cambia nada
