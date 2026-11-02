# Propuesta: Change 03 - Gestión de Agenda y Reglas de Disponibilidad

## ¿Qué problema resuelve?
El sistema odontológico actual carece de validaciones automatizadas para prevenir sobreturnos cruzados, conflictos de horarios de profesionales y solapamientos en la asignación física de sillones médicos (`chairs`).

## Solución Propuesta
- Implementar la skill `agenda-schedule-validator` para auditar la consistencia de los turnos.
- Integrar el servidor MCP de PostgreSQL para permitir al agente consultar los esquemas de bases de datos de forma segura durante el desarrollo.
- Definir las reglas de negocio para los rangos horarios de atención.