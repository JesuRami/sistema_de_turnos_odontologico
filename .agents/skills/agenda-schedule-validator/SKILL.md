# Agenda Schedule Validator Skill

## Propósito
Esta skill inspecciona y valida las reglas horarios, disponibilidad de sillones odontológicos y detección de solapamiento de turnos.

## Cuándo se activa
Se activa al preparar o verificar cambios en los módulos de agenda, turnos o reglas de atención profesional.

## Procedimiento
1. Revisar los modelos de datos de `ScheduleRule` y `Appointment`.
2. Verificar que el intervalo de turno sea exactamente múltiplo del slot mínimo (ej. 15, 30, 45 mins).
3. Comprobar la ausencia de solapamiento de horario para un mismo profesional o un mismo sillón (`chair_id`).
4. Generar informe de inconsistencias si existen solapamientos.

## Criterios de Revisión
- Cero solapamientos en un mismo sillón en el mismo rango horario.
- Mensajes de error claros sin filtrado de PII (información sensible del paciente).