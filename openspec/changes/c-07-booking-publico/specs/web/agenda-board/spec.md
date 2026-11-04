# Spec Delta — web/agenda-board

## ADDED Requirements

### Requirement: La agenda refleja reservas online sin recargar

La agenda abierta SHALL volver a pedir los turnos del rango visible a intervalos
regulares (como máximo cada 30 segundos mientras la pestaña está visible) y al
recuperar el foco, de modo que un turno reservado online aparezca, distinguido
como pendiente, sin recargar la página.

#### Scenario: Reserva online mientras recepción mira la agenda

- **WHEN** recepción tiene abierta la vista día y un paciente reserva online un hueco de ese día
- **THEN** a lo sumo 30 segundos después el turno aparece como pendiente sin recargar

#### Scenario: Pestaña oculta

- **WHEN** la pestaña de la agenda está oculta
- **THEN** no se hacen pedidos periódicos hasta que vuelve a estar visible
