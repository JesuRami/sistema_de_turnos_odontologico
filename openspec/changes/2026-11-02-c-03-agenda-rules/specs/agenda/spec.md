# Especificación: Módulo de Agenda y Disponibilidad

## Requisitos de Comportamiento
1. El sistema debe impedir la asignación de un turno si el intervalo horario coincide parcialmente con un turno previo confirmado para el mismo profesional.
2. El sistema debe validar que el sillón odontológico (`chair_id`) seleccionado no posea otra ocupación activa en el mismo rango de tiempo.
3. Las reglas de disponibilidad deben ser evaluadas mediante la skill de validación antes de confirmar la transacción en la base de datos PostgreSQL.