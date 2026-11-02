# Diseño Técnico: Change 03 - Gestión de Agenda

## Arquitectura de Solución
1. **Validación con Skill:** La skill `.agents/skills/agenda-schedule-validator/SKILL.md` verificará las restricciones de horario antes de insertar registros en la base de datos.
2. **Inspección MCP:** Utilización del servidor MCP de PostgreSQL para verificar la integridad referencial entre las tablas `schedules`, `appointments` y `chairs`.
3. **Restricciones del Dominio:**
   - Duración de turnos en múltiplos exactos de los slots permitidos.
   - Restricción de unicidad para evitar que un mismo sillón sea asignado a dos pacientes en el mismo intervalo temporal.